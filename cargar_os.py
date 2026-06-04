"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  SCRIPT: cargar_os.py                                                        ║
║  Descripción: Carga una OS (Orden de Servicio) en la capa inspecciones_OS,   ║
║               vinculándola geométricamente al Problema correspondiente en     ║
║               V_RE_PROBLEMAS_ABIERTOS_SANEA, organiza las imágenes y genera  ║
║               el HTML del informe listo para imprimir.                       ║
║  Uso: Consola Python de QGIS o como script de procesamiento.                 ║
║  Autor: Grupo TAU – DICA                                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

ESTRUCTURA DE CARPETAS (existente, seleccionada por el usuario):
  carpeta_OS/
   ├── archivo_correo.pdf        ← llega del correo
   ├── foto_original.jpg         ← imágenes antes del renombrado
   ├── figura_01.jpg             ← renombradas in situ por el script
   ├── figura_02.jpg
   └── informe_OS_<nro>.html     ← informe generado en la misma carpeta
"""

import os
import glob
import re
from datetime import datetime
from qgis.core import (
    QgsProject,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsVectorDataProvider,
    QgsField,
    QgsCoordinateReferenceSystem,
    QgsMapRendererParallelJob,
)
from PyQt5.QtCore import QVariant
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QTextEdit, QMessageBox, QComboBox, QGroupBox,
    QSizePolicy,
)
from PyQt5.QtGui import QFont

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN — ajustar según el entorno
# ─────────────────────────────────────────────────────────────────────────────

# Ruta base donde se crean las carpetas por OS
RAIZ_IMAGENES = r"G:\Unidades compartidas\GRUPO TAU\INTENDENCIA DE MONTEVIDEO\SOMS\IMAGENES_OS"

# Ruta de la plantilla HTML
PLANTILLA_HTML = r"G:\Unidades compartidas\GRUPO TAU\INTENDENCIA DE MONTEVIDEO\SOMS\informe_os.html"

# Nombre exacto de las capas en el proyecto QGIS
CAPA_PROBLEMAS = "V_RE_PROBLEMAS_ABIERTOS_SANEA"
CAPA_OS        = "inspecciones_OS"

# Campo clave en la capa de problemas
CAMPO_PROBLEMA = "NUMERO_PROBLEMA"

# Campos de la capa inspecciones_OS (deben coincidir con los que ya tenga)
CAMPOS_OS = [
    ("nro_trabajo",       QVariant.Int),
    ("orden_servicio",    QVariant.String),
    ("numero_problema",   QVariant.String),
    ("solicitante",       QVariant.String),
    ("fecha_ingreso",     QVariant.String),
    ("fecha_realizada",   QVariant.String),
    ("operario_cctv",     QVariant.String),
    ("material",          QVariant.String),
    ("descripcion",       QVariant.String),
    ("ubicacion",         QVariant.String),
    ("contacto",          QVariant.String),
    ("observaciones",     QVariant.String),
    ("estado",            QVariant.String),
    ("ruta_imagenes",     QVariant.String),
    ("ruta_html",         QVariant.String),
    ("fecha_carga",       QVariant.String),
]

# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES AUXILIARES
# ─────────────────────────────────────────────────────────────────────────────

def obtener_capa(nombre):
    """Devuelve la capa por nombre o None."""
    capas = QgsProject.instance().mapLayersByName(nombre)
    if not capas:
        return None
    return capas[0]


def buscar_problema(numero_problema):
    """
    Busca el feature en V_RE_PROBLEMAS_ABIERTOS_SANEA cuyo
    NUMERO_PROBLEMA coincida con el valor dado.
    Devuelve (feature, QgsPointXY) o (None, None).
    """
    capa = obtener_capa(CAPA_PROBLEMAS)
    if capa is None:
        return None, None

    for feat in capa.getFeatures():
        val = str(feat[CAMPO_PROBLEMA]).strip()
        if val == str(numero_problema).strip():
            geom = feat.geometry()
            if geom and not geom.isNull():
                centroide = geom.centroid().asPoint()
                return feat, centroide
    return None, None


def renombrar_imagenes(carpeta):
    """
    Renombra in situ las imágenes de carpeta como figura_01.jpg, figura_02.jpg, ...
    Usa dos pasadas para evitar conflictos cuando ya existe algún figura_XX.
    Devuelve lista con rutas absolutas de las figuras (hasta 8).
    """
    extensiones = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    archivos = []
    for ext in extensiones:
        archivos.extend(glob.glob(os.path.join(carpeta, ext)))

    archivos.sort(key=lambda p: os.path.basename(p).lower())

    # Pasada 1: renombrar a nombres temporales para evitar colisiones
    temp_rutas = []
    for i, src in enumerate(archivos[:8], start=1):
        ext = os.path.splitext(src)[1].lower().replace(".jpeg", ".jpg")
        tmp = os.path.join(carpeta, f"_tmp_{i:02d}{ext}")
        os.rename(src, tmp)
        temp_rutas.append((tmp, ext, i))

    # Pasada 2: renombrar a nombres definitivos
    rutas_finales = []
    for tmp, ext, i in temp_rutas:
        dst = os.path.join(carpeta, f"figura_{i:02d}{ext}")
        os.rename(tmp, dst)
        rutas_finales.append(dst)

    return rutas_finales


def generar_html(datos, rutas_imagenes, ruta_salida):
    """
    Carga la plantilla HTML, reemplaza los marcadores {{...}}
    con los datos de la OS y guarda el resultado en ruta_salida.
    """
    with open(PLANTILLA_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    # Mapa (ruta relativa desde el HTML)
    img_mapa = datos.get("img_mapa", "")
    html = html.replace("{{IMG_MAPA}}", os.path.basename(img_mapa) if img_mapa else "")

    # Rutas de imágenes (rutas relativas desde el HTML)
    for i in range(1, 5):
        clave = f"{{{{IMG_{i}}}}}"
        if i <= len(rutas_imagenes):
            html = html.replace(clave, os.path.basename(rutas_imagenes[i - 1]))
        else:
            html = html.replace(clave, "")

    # Badge de estado
    estado = datos.get("estado", "")
    badge_clases = {
        "Realizada":    "badge-realizada",
        "Parcial":      "badge-parcial",
        "Pendiente":    "badge-pendiente",
        "No realizada": "badge-noreali",
    }
    cls = badge_clases.get(estado, "")
    badge_html = f'<span class="badge {cls}">{estado}</span>' if estado else ""
    html = html.replace("{{BADGE_ESTADO}}", badge_html)

    # Datos textuales
    reemplazos = {
        "{{NRO_TRABAJO}}":      str(datos.get("nro_trabajo", "")),
        "{{ORDEN_SERVICIO}}":   str(datos.get("orden_servicio", "")),
        "{{NUMERO_PROBLEMA}}":  str(datos.get("numero_problema", "")),
        "{{SOLICITANTE}}":      datos.get("solicitante", ""),
        "{{FECHA_INGRESO}}":    datos.get("fecha_ingreso", ""),
        "{{FECHA_REALIZADA}}":  datos.get("fecha_realizada", ""),
        "{{OPERARIO_CCTV}}":    datos.get("operario_cctv", ""),
        "{{MATERIAL}}":         datos.get("material", ""),
        "{{DESCRIPCION}}":      datos.get("descripcion", ""),
        "{{UBICACION}}":        datos.get("ubicacion", ""),
        "{{CONTACTO}}":         datos.get("contacto", ""),
        "{{OBSERVACIONES}}":    datos.get("observaciones", "").replace("\n", "<br>"),
        "{{FECHA_GENERACION}}": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }

    for marcador, valor in reemplazos.items():
        html = html.replace(marcador, valor)

    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(html)


def agregar_feature_os(datos, punto_xy):
    """
    Agrega un nuevo feature a la capa inspecciones_OS con la
    geometría del punto vinculado al problema.
    """
    capa = obtener_capa(CAPA_OS)
    if capa is None:
        raise ValueError(f"No se encontró la capa '{CAPA_OS}' en el proyecto.")

    if not capa.isEditable():
        capa.startEditing()

    feat = QgsFeature(capa.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(punto_xy))

    for nombre_campo, _ in CAMPOS_OS:
        if nombre_campo in datos and capa.fields().indexOf(nombre_campo) >= 0:
            feat.setAttribute(nombre_campo, datos[nombre_campo])

    feat.setAttribute("fecha_carga", datetime.now().strftime("%Y-%m-%d %H:%M"))

    capa.addFeature(feat)
    capa.commitChanges()
    capa.triggerRepaint()


def capturar_mapa(punto_xy, ruta_salida, escala=2000):
    """
    Renderiza el canvas centrado en punto_xy a escala dada y guarda la imagen.
    Usa QgsMapRendererParallelJob para no depender del estado visual de la ventana.
    """
    from PyQt5.QtCore import QSize
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


# ─────────────────────────────────────────────────────────────────────────────
# DIÁLOGO DE CARGA
# ─────────────────────────────────────────────────────────────────────────────

class DialogoCargaOS(QDialog):
    """
    Diálogo para ingresar los datos de la OS manualmente
    o importándolos de un PDF/mail ya parseado.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cargar Orden de Servicio — Grupo TAU")
        self.setMinimumWidth(560)
        self.carpeta_imagenes_src = ""
        self._build_ui()

    def _campo(self, placeholder=""):
        w = QLineEdit()
        w.setPlaceholderText(placeholder)
        return w

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Título ──
        titulo = QLabel("Nueva Orden de Servicio")
        titulo.setFont(QFont("Arial", 13, QFont.Bold))
        layout.addWidget(titulo)

        # ── Grupo: Información General ──
        grp1 = QGroupBox("Información general")
        form1 = QFormLayout(grp1)
        form1.setSpacing(6)

        self.f_nro_trabajo    = self._campo("ej: 1")
        self.f_orden_servicio = self._campo("ej: 5337775")
        self.f_numero_problema = self._campo("ej: 12345  ← vincula con el Problema en QGIS")
        self.f_solicitante    = self._campo("ej: SOMS - Intendencia de Montevideo")
        self.f_fecha_ingreso  = self._campo("dd/mm/aaaa")
        self.f_ubicacion      = self._campo("ej: 25 DE MAYO Nº 259")
        self.f_contacto       = self._campo("ej: Tel: 098105237")
        self.f_descripcion    = self._campo("ej: Inspección de conexión")

        form1.addRow("Nº Trabajo:",        self.f_nro_trabajo)
        form1.addRow("Orden de Servicio:", self.f_orden_servicio)
        form1.addRow("Nº Problema:",       self.f_numero_problema)
        form1.addRow("Solicitante:",       self.f_solicitante)
        form1.addRow("Fecha ingreso:",     self.f_fecha_ingreso)
        form1.addRow("Ubicación:",         self.f_ubicacion)
        form1.addRow("Contacto:",          self.f_contacto)
        form1.addRow("Descripción:",       self.f_descripcion)
        layout.addWidget(grp1)

        # ── Grupo: Datos de la Inspección ──
        grp2 = QGroupBox("Datos de la inspección")
        form2 = QFormLayout(grp2)
        form2.setSpacing(6)

        self.f_fecha_realizada = self._campo("dd/mm/aaaa")
        self.f_operario        = self._campo("ej: JS")
        self.f_material        = self._campo("ej: Hormigón")

        self.f_estado = QComboBox()
        self.f_estado.addItems(["Realizada", "Parcial", "Pendiente", "No realizada"])

        form2.addRow("Fecha realizada:", self.f_fecha_realizada)
        form2.addRow("Operario CCTV:",   self.f_operario)
        form2.addRow("Material:",        self.f_material)
        form2.addRow("Estado:",          self.f_estado)
        layout.addWidget(grp2)

        # ── Observaciones ──
        grp3 = QGroupBox("Observaciones")
        v3 = QVBoxLayout(grp3)
        self.f_observaciones = QTextEdit()
        self.f_observaciones.setFixedHeight(80)
        self.f_observaciones.setPlaceholderText(
            "Descripción completa de lo observado durante la inspección...")
        v3.addWidget(self.f_observaciones)
        layout.addWidget(grp3)

        # ── Carpeta de la OS ──
        grp4 = QGroupBox("Carpeta de la OS  (correo + imágenes + informe)")
        h4 = QHBoxLayout(grp4)
        self.lbl_carpeta = QLabel("Sin seleccionar")
        self.lbl_carpeta.setWordWrap(True)
        btn_carpeta = QPushButton("Seleccionar carpeta…")
        btn_carpeta.clicked.connect(self._seleccionar_carpeta)
        h4.addWidget(self.lbl_carpeta, 1)
        h4.addWidget(btn_carpeta)
        layout.addWidget(grp4)

        # ── Botones ──
        hbox = QHBoxLayout()
        btn_ok     = QPushButton("✓  Cargar OS")
        btn_cancel = QPushButton("Cancelar")
        btn_ok.setDefault(True)
        btn_ok.setMinimumHeight(34)
        btn_ok.setStyleSheet(
            "QPushButton{background:#0a3d62;color:white;font-weight:bold;border-radius:3px;padding:0 14px;}"
            "QPushButton:hover{background:#1a5276;}"
        )
        btn_ok.clicked.connect(self._aceptar)
        btn_cancel.clicked.connect(self.reject)
        hbox.addStretch()
        hbox.addWidget(btn_cancel)
        hbox.addWidget(btn_ok)
        layout.addLayout(hbox)

    def _seleccionar_carpeta(self):
        ruta = QFileDialog.getExistingDirectory(
            self, "Carpeta con imágenes de la OS",
            RAIZ_IMAGENES
        )
        if ruta:
            self.carpeta_imagenes_src = ruta
            self.lbl_carpeta.setText(ruta)

    def _validar(self):
        errores = []
        if not self.f_numero_problema.text().strip():
            errores.append("• Nº Problema es obligatorio (vincula con la capa de problemas).")
        if not self.f_orden_servicio.text().strip():
            errores.append("• Orden de Servicio es obligatoria.")
        if errores:
            QMessageBox.warning(self, "Campos incompletos", "\n".join(errores))
            return False
        return True

    def _aceptar(self):
        if not self._validar():
            return

        datos = {
            "nro_trabajo":      self.f_nro_trabajo.text().strip(),
            "orden_servicio":   self.f_orden_servicio.text().strip(),
            "numero_problema":  self.f_numero_problema.text().strip(),
            "solicitante":      self.f_solicitante.text().strip(),
            "fecha_ingreso":    self.f_fecha_ingreso.text().strip(),
            "fecha_realizada":  self.f_fecha_realizada.text().strip(),
            "operario_cctv":    self.f_operario.text().strip(),
            "material":         self.f_material.text().strip(),
            "descripcion":      self.f_descripcion.text().strip(),
            "ubicacion":        self.f_ubicacion.text().strip(),
            "contacto":         self.f_contacto.text().strip(),
            "observaciones":    self.f_observaciones.toPlainText().strip(),
            "estado":           self.f_estado.currentText(),
        }

        # ── 1. Buscar el Problema en la capa de la IM ──────────────────────
        problema_feat, punto_xy = buscar_problema(datos["numero_problema"])
        if problema_feat is None:
            resp = QMessageBox.question(
                self, "Problema no encontrado",
                f"No se encontró el Problema Nº {datos['numero_problema']} en la capa\n"
                f"'{CAPA_PROBLEMAS}'.\n\n"
                "¿Querés cargar la OS igual sin geometría?",
                QMessageBox.Yes | QMessageBox.No
            )
            if resp == QMessageBox.No:
                return
            punto_xy = QgsPointXY(0, 0)   # geometría nula como fallback

        # ── 2. Organizar imágenes ─────────────────────────────────────────
        carpeta_os = self.carpeta_imagenes_src
        rutas_imagenes = []

        if carpeta_os:
            try:
                rutas_imagenes = renombrar_imagenes(carpeta_os)
                datos["ruta_imagenes"] = carpeta_os
            except Exception as e:
                QMessageBox.warning(self, "Error al renombrar imágenes", str(e))
        else:
            datos["ruta_imagenes"] = ""

        # ── 3. Capturar mapa ─────────────────────────────────────────────
        img_mapa = ""
        if carpeta_os and punto_xy != QgsPointXY(0, 0):
            try:
                ruta_mapa = os.path.join(carpeta_os, "mapa_os.png")
                capturar_mapa(punto_xy, ruta_mapa)
                img_mapa = ruta_mapa
            except Exception as e:
                QMessageBox.warning(self, "Error al capturar mapa", str(e))
        datos["img_mapa"] = img_mapa

        # ── 4. Generar HTML ───────────────────────────────────────────────
        nombre_html = f"informe_OS_{datos['orden_servicio']}.html"
        ruta_html   = os.path.join(carpeta_os, nombre_html) if carpeta_os else ""

        if not ruta_html:
            QMessageBox.warning(
                self, "Sin carpeta seleccionada",
                "No se seleccionó carpeta de OS.\nEl informe HTML no fue generado."
            )
            datos["ruta_html"] = ""
        elif os.path.exists(PLANTILLA_HTML):
            try:
                generar_html(datos, rutas_imagenes, ruta_html)
                datos["ruta_html"] = ruta_html
            except Exception as e:
                QMessageBox.warning(self, "Error al generar HTML", str(e))
                datos["ruta_html"] = ""
        else:
            QMessageBox.warning(
                self, "Plantilla no encontrada",
                f"No se encontró la plantilla HTML en:\n{PLANTILLA_HTML}\n\n"
                "El informe no fue generado, pero la OS se cargará igualmente."
            )
            datos["ruta_html"] = ""

        # ── 5. Agregar feature a inspecciones_OS ─────────────────────────
        try:
            agregar_feature_os(datos, punto_xy)
        except Exception as e:
            QMessageBox.critical(self, "Error al cargar en QGIS", str(e))
            return

        # ── 6. Zoom al punto ─────────────────────────────────────────────
        iface.mapCanvas().setCenter(punto_xy)
        iface.mapCanvas().zoomScale(2000)
        iface.mapCanvas().refresh()

        # ── Mensaje final ────────────────────────────────────────────────
        msg = (
            f"✓ OS {datos['orden_servicio']} cargada exitosamente.\n\n"
            f"• Problema vinculado: {datos['numero_problema']}\n"
            f"• Imágenes: {len(rutas_imagenes)} archivo(s) → {carpeta_os}\n"
        )
        if datos.get("ruta_html"):
            msg += f"• Informe HTML: {ruta_html}\n"
            msg += "\n¿Querés abrir el informe en el navegador?"
            resp = QMessageBox.question(
                self, "OS Cargada", msg,
                QMessageBox.Yes | QMessageBox.No
            )
            if resp == QMessageBox.Yes:
                import webbrowser
                webbrowser.open(f"file:///{ruta_html.replace(os.sep, '/')}")
        else:
            QMessageBox.information(self, "OS Cargada", msg)

        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA — ejecutar desde la consola Python de QGIS
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Abre el diálogo de carga de OS."""
    dlg = DialogoCargaOS()
    dlg.exec_()


# Ejecutar
main()
