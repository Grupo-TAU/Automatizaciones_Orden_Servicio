"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  SCRIPT: generar_informe.py  —  PASO 3 de 3                                 ║
║  Descripción: Lee los datos de una OS ya registrada en inspecciones_OS,      ║
║               renombra las fotos de la carpeta, captura el mapa y genera     ║
║               el informe HTML listo para imprimir.                           ║
║  Uso: Consola Python de QGIS  (ejecutar cuando Estado = "Listo")             ║
║  Autor: Grupo TAU – DICA                                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

Columnas de inspecciones_OS usadas:
  Lectura (paso 1):  N___OS, N___trabajo, Name, Fecha_Ingreso,
                     Tipo_de_Inspecci__n, Observaciones_prev_, RUTA
  Escritura (paso 3): Operario, Estado_Inspecci__n, LIMPIEZA,
                      Fecha_inspeccionado, Fecha_entrega, METRAJE,
                      Observaciones_adic_, Estado, RUTA
"""

import os
import glob
import base64
from datetime import datetime
from qgis.core import (
    QgsProject,
    QgsPointXY,
    QgsMapRendererParallelJob,
)
from qgis.utils import iface
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QTextEdit, QMessageBox, QComboBox, QGroupBox,
)
from PyQt5.QtGui import QFont

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

RAIZ_IMAGENES  = r"G:\Unidades compartidas\GRUPO TAU\INTENDENCIA DE MONTEVIDEO\SOMS\IMAGENES_OS"
PLANTILLA_HTML = r"C:\Users\grupo\OneDrive\Desktop\Repos\Automatizaciones_Orden_Servicio\informe_os.html"
CAPA_OS        = "inspecciones_OS"

# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES
# ─────────────────────────────────────────────────────────────────────────────

def obtener_capa(nombre):
    capas = QgsProject.instance().mapLayersByName(nombre)
    return capas[0] if capas else None


def buscar_os_en_capa(orden_servicio):
    """Devuelve (feature, QgsPointXY) buscando por N___OS, o (None, None)."""
    capa = obtener_capa(CAPA_OS)
    if capa is None:
        return None, None
    for feat in capa.getFeatures():
        if str(feat["N___OS"]).strip() == str(orden_servicio).strip():
            geom = feat.geometry()
            punto = geom.asPoint() if (geom and not geom.isNull()) else QgsPointXY(0, 0)
            return feat, punto
    return None, None


def actualizar_feature_os(feature_id, datos):
    """Actualiza los atributos del feature con los datos del dict."""
    capa = obtener_capa(CAPA_OS)
    if capa is None:
        raise ValueError(f"No se encontró la capa '{CAPA_OS}'.")
    if not capa.isEditable():
        capa.startEditing()
    for campo, valor in datos.items():
        idx = capa.fields().indexOf(campo)
        if idx >= 0:
            capa.changeAttributeValue(feature_id, idx, valor)
    capa.commitChanges()
    capa.triggerRepaint()


def listar_imagenes(carpeta):
    """
    Devuelve hasta 10 rutas de imágenes en carpeta, ordenadas alfabéticamente.
    No renombra nada — el HTML referencia los nombres originales.
    """
    carpeta = os.path.realpath(carpeta)
    extensiones = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    archivos = []
    for ext in extensiones:
        archivos.extend(glob.glob(os.path.join(carpeta, ext)))

    # Excluir el mapa (el usuario lo pone aparte como mapa.png/jpg)
    archivos = [
        p for p in archivos
        if not os.path.basename(p).lower().startswith("mapa")
    ]
    archivos.sort(key=lambda p: os.path.basename(p).lower())
    return archivos[:10]


def capturar_mapa(punto_xy, ruta_salida, escala=2000):
    """Renderiza el canvas centrado en punto_xy y guarda la imagen."""
    from PyQt5.QtWidgets import QApplication
    canvas = iface.mapCanvas()
    canvas.setCenter(punto_xy)
    canvas.zoomScale(escala)
    canvas.refresh()
    QApplication.processEvents()
    settings = canvas.mapSettings()
    settings.setOutputSize(QSize(800, 500))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(ruta_salida)


def generar_html(datos, rutas_imagenes, ruta_salida):
    """Carga la plantilla y reemplaza los marcadores {{...}} con los datos."""
    with open(PLANTILLA_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    def a_base64(ruta):
        ext = os.path.splitext(ruta)[1].lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
        with open(ruta, "rb") as f:
            return f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"

    # Mapa (archivo mapa.png/jpg dejado manualmente en la carpeta)
    img_mapa = datos.get("img_mapa", "")
    if img_mapa and os.path.exists(img_mapa):
        try:
            html = html.replace("{{IMG_MAPA}}", a_base64(img_mapa))
        except Exception:
            html = html.replace("{{IMG_MAPA}}", "")
    else:
        html = html.replace("{{IMG_MAPA}}", "")

    # Imágenes embebidas como base64
    for i in range(1, 5):
        clave = f"{{{{IMG_{i}}}}}"
        if i <= len(rutas_imagenes):
            try:
                html = html.replace(clave, a_base64(rutas_imagenes[i - 1]))
            except Exception:
                html = html.replace(clave, "")
        else:
            html = html.replace(clave, "")

    # Badge de estado
    estado = datos.get("Estado", "")
    badge_clases = {
        "Realizada":    "badge-realizada",
        "Parcial":      "badge-parcial",
        "Pendiente":    "badge-pendiente",
        "No realizada": "badge-noreali",
    }
    cls = badge_clases.get(estado, "")
    badge_html = f'<span class="badge {cls}">{estado}</span>' if estado else ""
    html = html.replace("{{BADGE_ESTADO}}", badge_html)

    # Datos textuales — columnas reales de inspecciones_OS
    reemplazos = {
        "{{NRO_TRABAJO}}":       str(datos.get("N___trabajo", "")),
        "{{ORDEN_SERVICIO}}":    str(datos.get("N___OS", "")),
        "{{SOLICITANTE}}":       "",
        "{{UBICACION}}":         datos.get("Name", ""),
        "{{FECHA_INGRESO}}":     datos.get("Fecha_Ingreso", ""),
        "{{DESCRIPCION}}":       datos.get("Tipo_de_Inspecci__n", ""),
        "{{OBSERVACIONES}}":     datos.get("Observaciones_prev_", "").replace("\n", "<br>"),
        "{{FECHA_REALIZADA}}":   datos.get("Fecha_inspeccionado", ""),
        "{{OPERARIO_CCTV}}":     datos.get("Operario", ""),
        "{{ESTADO_INSPECCION}}": datos.get("Estado_Inspecci__n", ""),
        "{{LIMPIEZA}}":          datos.get("LIMPIEZA", ""),
        "{{METRAJE}}":           datos.get("METRAJE", ""),
        "{{FECHA_ENTREGA}}":     datos.get("Fecha_entrega", ""),
        "{{OBS_ADIC}}":          datos.get("Observaciones_adic_", "").replace("\n", "<br>"),
        # Sin columna en la capa — se dejan vacíos en el HTML
        "{{CONTACTO}}":          "",
        "{{NUMERO_PROBLEMA}}":   "",
        "{{MATERIAL}}":          "",
        "{{FECHA_GENERACION}}":  datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    for marcador, valor in reemplazos.items():
        html = html.replace(marcador, valor)

    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(html)


# ─────────────────────────────────────────────────────────────────────────────
# DIÁLOGO
# ─────────────────────────────────────────────────────────────────────────────

class DialogoGenerarInforme(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generar Informe — Paso 3")
        self.setMinimumWidth(580)
        self.feature_os = None
        self.feature_id = None
        self.punto_xy   = None
        self.carpeta_os = ""
        self._build_ui()

    def _campo(self, placeholder="", readonly=False):
        w = QLineEdit()
        w.setPlaceholderText(placeholder)
        if readonly:
            w.setReadOnly(True)
            w.setStyleSheet("background:#f0f0f0; color:#555;")
        return w

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        titulo = QLabel("Generar Informe de OS")
        titulo.setFont(QFont("Arial", 13, QFont.Bold))
        layout.addWidget(titulo)

        # ── Búsqueda ──────────────────────────────────────────────────────
        grp_buscar = QGroupBox("Buscar OS registrada")
        h_buscar = QHBoxLayout(grp_buscar)
        self.f_buscar = QLineEdit()
        self.f_buscar.setPlaceholderText("Nº OS  ej: 5337775")
        self.f_buscar.returnPressed.connect(self._buscar)
        btn_buscar = QPushButton("Buscar")
        btn_buscar.clicked.connect(self._buscar)
        self.lbl_estado_busqueda = QLabel("")
        self.lbl_estado_busqueda.setStyleSheet("color:#555; font-style:italic;")
        h_buscar.addWidget(self.f_buscar, 1)
        h_buscar.addWidget(btn_buscar)
        h_buscar.addWidget(self.lbl_estado_busqueda)
        layout.addWidget(grp_buscar)

        # ── Datos del correo — solo lectura ───────────────────────────────
        grp_info = QGroupBox("Datos del correo  (solo lectura)")
        form_info = QFormLayout(grp_info)
        form_info.setSpacing(5)
        self.f_nro_trabajo    = self._campo(readonly=True)
        self.f_orden_servicio = self._campo(readonly=True)
        self.f_name           = self._campo(readonly=True)
        self.f_fecha_ingreso  = self._campo(readonly=True)
        self.f_tipo_insp      = self._campo(readonly=True)
        form_info.addRow("Nº Trabajo:",   self.f_nro_trabajo)
        form_info.addRow("N° OS:",        self.f_orden_servicio)
        form_info.addRow("Ubicación:",    self.f_name)
        form_info.addRow("Fecha ingreso:", self.f_fecha_ingreso)
        form_info.addRow("Tipo insp.:",   self.f_tipo_insp)

        # Observaciones previas — read-only multiline
        self.f_obs_prev = QTextEdit()
        self.f_obs_prev.setReadOnly(True)
        self.f_obs_prev.setFixedHeight(55)
        self.f_obs_prev.setStyleSheet("background:#f0f0f0; color:#555;")
        form_info.addRow("Obs. previas:", self.f_obs_prev)
        layout.addWidget(grp_info)

        # ── Datos de la inspección — editables ────────────────────────────
        grp_insp = QGroupBox("Datos de la inspección")
        form_insp = QFormLayout(grp_insp)
        form_insp.setSpacing(6)
        self.f_fecha_inspeccionado = self._campo("dd/mm/aaaa")
        self.f_operario            = self._campo("ej: JS")
        self.f_estado_insp         = self._campo("ej: Realizada")
        self.f_limpieza            = self._campo("ej: Sí / No")
        self.f_metraje             = self._campo("ej: 5.3 m")
        self.f_fecha_entrega       = self._campo("dd/mm/aaaa")
        self.f_estado = QComboBox()
        self.f_estado.addItems(["Pendiente", "Realizada", "Parcial", "No realizada"])
        form_insp.addRow("Fecha inspeccionado:", self.f_fecha_inspeccionado)
        form_insp.addRow("Operario:",            self.f_operario)
        form_insp.addRow("Estado inspección:",   self.f_estado_insp)
        form_insp.addRow("Limpieza:",            self.f_limpieza)
        form_insp.addRow("Metraje:",             self.f_metraje)
        form_insp.addRow("Fecha entrega:",       self.f_fecha_entrega)
        form_insp.addRow("Estado (workflow):",   self.f_estado)
        layout.addWidget(grp_insp)

        # ── Observaciones adicionales ─────────────────────────────────────
        grp_obs = QGroupBox("Observaciones adicionales")
        v_obs = QVBoxLayout(grp_obs)
        self.f_obs_adic = QTextEdit()
        self.f_obs_adic.setFixedHeight(80)
        self.f_obs_adic.setPlaceholderText(
            "Observaciones de la inspección realizada...")
        v_obs.addWidget(self.f_obs_adic)
        layout.addWidget(grp_obs)

        # ── Carpeta de la OS ──────────────────────────────────────────────
        grp_carpeta = QGroupBox("Carpeta de la OS  (correo + fotos)")
        h_carp = QHBoxLayout(grp_carpeta)
        self.lbl_carpeta = QLabel("Sin seleccionar")
        self.lbl_carpeta.setWordWrap(True)
        btn_carpeta = QPushButton("Seleccionar…")
        btn_carpeta.clicked.connect(self._seleccionar_carpeta)
        h_carp.addWidget(self.lbl_carpeta, 1)
        h_carp.addWidget(btn_carpeta)
        layout.addWidget(grp_carpeta)

        # ── Botones ───────────────────────────────────────────────────────
        hbox = QHBoxLayout()
        self.btn_generar = QPushButton("✓  Generar informe")
        btn_cancel       = QPushButton("Cancelar")
        self.btn_generar.setEnabled(False)
        self.btn_generar.setDefault(True)
        self.btn_generar.setMinimumHeight(34)
        self.btn_generar.setStyleSheet(
            "QPushButton{background:#325423;color:white;font-weight:bold;"
            "border-radius:3px;padding:0 14px;}"
            "QPushButton:hover{background:#3e6a2c;}"
            "QPushButton:disabled{background:#aaa;}"
        )
        self.btn_generar.clicked.connect(self._aceptar)
        btn_cancel.clicked.connect(self.reject)
        hbox.addStretch()
        hbox.addWidget(btn_cancel)
        hbox.addWidget(self.btn_generar)
        layout.addLayout(hbox)

    # ── Búsqueda ─────────────────────────────────────────────────────────────

    def _buscar(self):
        os_num = self.f_buscar.text().strip()
        if not os_num:
            return

        feat, punto_xy = buscar_os_en_capa(os_num)
        if feat is None:
            self.lbl_estado_busqueda.setText("✗ No encontrada")
            self.lbl_estado_busqueda.setStyleSheet("color:red;")
            self.btn_generar.setEnabled(False)
            return

        self.feature_os = feat
        self.feature_id = feat.id()
        self.punto_xy   = punto_xy

        # Pre-cargar carpeta desde RUTA si existe
        ruta_guardada = str(feat["RUTA"] or "").strip()
        if ruta_guardada and os.path.isdir(ruta_guardada):
            self.carpeta_os = ruta_guardada
            self.lbl_carpeta.setText(ruta_guardada)

        self._poblar_formulario(feat)
        self.lbl_estado_busqueda.setText("✓ Encontrada")
        self.lbl_estado_busqueda.setStyleSheet("color:green; font-weight:bold;")
        self.btn_generar.setEnabled(True)

    def _poblar_formulario(self, feat):
        def val(campo):
            v = feat[campo]
            return "" if v is None or str(v) in ("NULL", "None") else str(v)

        # Datos del correo (solo lectura)
        self.f_nro_trabajo.setText(val("N___trabajo"))
        self.f_orden_servicio.setText(val("N___OS"))
        self.f_name.setText(val("Name"))
        self.f_fecha_ingreso.setText(val("Fecha_Ingreso"))
        self.f_tipo_insp.setText(val("Tipo_de_Inspecci__n"))
        self.f_obs_prev.setPlainText(val("Observaciones_prev_"))

        # Datos de la inspección (editables)
        self.f_fecha_inspeccionado.setText(val("Fecha_inspeccionado"))
        self.f_operario.setText(val("Operario"))
        self.f_estado_insp.setText(val("Estado_Inspecci__n"))
        self.f_limpieza.setText(val("LIMPIEZA"))
        self.f_metraje.setText(val("METRAJE"))
        self.f_fecha_entrega.setText(val("Fecha_entrega"))
        self.f_obs_adic.setPlainText(val("Observaciones_adic_"))

        estado = val("Estado")
        idx = self.f_estado.findText(estado)
        if idx >= 0:
            self.f_estado.setCurrentIndex(idx)

    # ── Carpeta ───────────────────────────────────────────────────────────────

    def _seleccionar_carpeta(self):
        inicio = self.carpeta_os or RAIZ_IMAGENES
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de la OS", inicio)
        if ruta:
            self.carpeta_os = ruta
            self.lbl_carpeta.setText(ruta)

    # ── Generar ───────────────────────────────────────────────────────────────

    def _validar(self):
        errores = []
        if not self.carpeta_os or not os.path.isdir(self.carpeta_os):
            errores.append("• Seleccioná la carpeta de la OS con las fotos.")
        if not os.path.exists(PLANTILLA_HTML):
            errores.append(f"• Plantilla HTML no encontrada:\n  {PLANTILLA_HTML}")
        if errores:
            QMessageBox.warning(self, "No se puede generar", "\n".join(errores))
            return False
        return True

    def _aceptar(self):
        if not self._validar():
            return

        carpeta = self.carpeta_os

        # Dict con nombres de columna reales para QGIS y HTML
        datos = {
            # Paso 1 — del correo (solo lectura)
            "N___trabajo":          self.f_nro_trabajo.text().strip(),
            "N___OS":               self.f_orden_servicio.text().strip(),
            "Name":                self.f_name.text().strip(),
            "Fecha_Ingreso":       self.f_fecha_ingreso.text().strip(),
            "Tipo_de_Inspecci__n": self.f_tipo_insp.text().strip(),
            "Observaciones_prev_": self.f_obs_prev.toPlainText().strip(),
            # Paso 3 — de la inspección (editables)
            "Operario":            self.f_operario.text().strip(),
            "Estado_Inspecci__n":  self.f_estado_insp.text().strip(),
            "LIMPIEZA":            self.f_limpieza.text().strip(),
            "Fecha_inspeccionado": self.f_fecha_inspeccionado.text().strip(),
            "Fecha_entrega":       self.f_fecha_entrega.text().strip(),
            "METRAJE":             self.f_metraje.text().strip(),
            "Observaciones_adic_": self.f_obs_adic.toPlainText().strip(),
            "Estado":              self.f_estado.currentText(),
            "RUTA":                carpeta,
        }

        # 1. Listar imágenes
        try:
            rutas_imagenes = listar_imagenes(carpeta)
        except Exception as e:
            QMessageBox.critical(self, "Error al listar imágenes", str(e))
            return

        # 2. Buscar archivo de mapa en la carpeta (mapa.png / mapa.jpg)
        mapa_candidatos = glob.glob(os.path.join(os.path.realpath(carpeta), "mapa.*"))
        datos["img_mapa"] = mapa_candidatos[0] if mapa_candidatos else ""

        # 3. Generar HTML
        nombre_html = f"informe_OS_{datos['N___OS']}.html"
        ruta_html   = os.path.join(carpeta, nombre_html)
        try:
            generar_html(datos, rutas_imagenes, ruta_html)
        except Exception as e:
            QMessageBox.critical(self, "Error al generar HTML", str(e))
            return

        # 4. Actualizar feature en QGIS (solo columnas del paso 3)
        try:
            actualizar_feature_os(self.feature_id, {
                "Operario":            datos["Operario"],
                "Estado_Inspecci__n":  datos["Estado_Inspecci__n"],
                "LIMPIEZA":            datos["LIMPIEZA"],
                "Fecha_inspeccionado": datos["Fecha_inspeccionado"],
                "Fecha_entrega":       datos["Fecha_entrega"],
                "METRAJE":             datos["METRAJE"],
                "Observaciones_adic_": datos["Observaciones_adic_"],
                "Estado":              datos["Estado"],
                "RUTA":                carpeta,
            })
        except Exception as e:
            QMessageBox.warning(self, "Error al actualizar QGIS", str(e))

        # 5. Zoom al punto
        if self.punto_xy and self.punto_xy != QgsPointXY(0, 0):
            iface.mapCanvas().setCenter(self.punto_xy)
            iface.mapCanvas().zoomScale(2000)
            iface.mapCanvas().refresh()

        # 6. Mensaje final
        msg = (
            f"✓ Informe generado para OS {datos['N___OS']}.\n\n"
            f"  Imágenes incluidas  : {len(rutas_imagenes)}\n"
            f"  Informe HTML        : {ruta_html}\n\n"
            "¿Querés abrir el informe en el navegador?"
        )
        resp = QMessageBox.question(self, "Informe generado", msg,
                                    QMessageBox.Yes | QMessageBox.No)
        if resp == QMessageBox.Yes:
            import webbrowser
            webbrowser.open(f"file:///{ruta_html.replace(os.sep, '/')}")

        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

def main():
    dlg = DialogoGenerarInforme()
    dlg.exec_()

main()
