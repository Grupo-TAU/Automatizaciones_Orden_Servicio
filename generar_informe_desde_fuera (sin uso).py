"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  SCRIPT: generar_informe_desde_fuera.py  —  PASO 3 (standalone)             ║
║  Descripción: Lee los datos desde el .gpkg, genera el informe HTML con       ║
║               imágenes embebidas en base64 y exporta PDF con pdfkit.         ║
║  Uso: python generar_informe_desde_fuera.py  (sin QGIS)                      ║
║  Autor: Grupo TAU – DICA                                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

Dependencias externas (instalar una sola vez):
    pip install pdfkit PyQt5

wkhtmltopdf: descargarlo de https://wkhtmltopdf.org/downloads.html
"""

import os
import sys
import glob
import base64
import sqlite3
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QScrollArea, QWidget,
    QTextEdit, QMessageBox, QComboBox, QGroupBox,
)
from PyQt5.QtGui import QFont

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

GPKG_PATH = r"G:\Unidades compartidas\GRUPO TAU\02 - EQUIPO TAU\NA\Inspecciones - OS\inspecciones_OS.gpkg"
TABLA_OS  = "inspecciones_OS"

PLANTILLA_HTML = r"C:\Users\grupo\OneDrive\Desktop\Repos\Automatizaciones_Orden_Servicio\informe_os.html"

RAIZ_IMAGENES  = r"G:\Unidades compartidas\GRUPO TAU\02 - EQUIPO TAU\NA\Inspecciones - OS"

# Busca wkhtmltopdf en las ubicaciones más comunes
def _encontrar_wkhtmltopdf():
    candidatos = [
        r"C:\Users\grupo\OneDrive\Desktop\net10.0\Windows\wkhtmltopdf.exe",
        r"C:\Users\grupo\OneDrive\Desktop\net10.0\Windows\bin\wkhtmltopdf.exe",
        r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe",
        r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe",
    ]
    for p in candidatos:
        if os.path.exists(p):
            return p
    return None

WKHTMLTOPDF = _encontrar_wkhtmltopdf()

# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES — GPKG (sqlite3)
# ─────────────────────────────────────────────────────────────────────────────

def buscar_os_en_gpkg(orden_servicio):
    """Devuelve dict con todos los campos de la OS, o None si no existe."""
    conn = sqlite3.connect(GPKG_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT * FROM "{TABLA_OS}" WHERE "N___OS" = ?',
                    (str(orden_servicio).strip(),))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _cargar_spatialite(conn):
    """Intenta cargar mod_spatialite para satisfacer triggers del GeoPackage."""
    candidatos = [
        r"C:\Program Files\QGIS 3.44.10\apps\qgis-ltr\mod_spatialite.dll",
        r"C:\Program Files\QGIS 3.44.10\apps\qgis-ltr\.\mod_spatialite",
        r"C:\PROGRA~1\QGIS34~1.10\apps\qgis-ltr\mod_spatialite",
        r"C:\Program Files\QGIS 3.34\apps\qgis\mod_spatialite.dll",
    ]
    try:
        conn.enable_load_extension(True)
        for path in candidatos:
            try:
                conn.load_extension(path)
                return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def actualizar_os_en_gpkg(orden_servicio, datos):
    """Actualiza los campos del dict en el registro con ese N___OS."""
    conn = sqlite3.connect(GPKG_PATH)
    try:
        _cargar_spatialite(conn)
        sets = ", ".join(f'"{k}" = ?' for k in datos)
        vals = list(datos.values()) + [str(orden_servicio).strip()]
        conn.execute(f'UPDATE "{TABLA_OS}" SET {sets} WHERE "N___OS" = ?', vals)
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES — IMÁGENES Y HTML
# ─────────────────────────────────────────────────────────────────────────────

def listar_imagenes(carpeta):
    """Devuelve hasta 10 rutas de imágenes (excluye archivos 'mapa*')."""
    carpeta = os.path.realpath(carpeta)
    extensiones = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    archivos = []
    for ext in extensiones:
        archivos.extend(glob.glob(os.path.join(carpeta, ext)))
    archivos = [p for p in archivos
                if not os.path.basename(p).lower().startswith("mapa")]
    archivos.sort(key=lambda p: os.path.basename(p).lower())
    return archivos[:10]


def generar_html(datos, rutas_imagenes, ruta_salida):
    """Genera el HTML con imágenes embebidas en base64."""
    with open(PLANTILLA_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    def a_base64(ruta):
        ext = os.path.splitext(ruta)[1].lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
        with open(ruta, "rb") as f:
            return f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"

    # Mapa (archivo mapa.* en la carpeta)
    img_mapa = datos.get("img_mapa", "")
    if img_mapa and os.path.exists(img_mapa):
        try:
            html = html.replace("{{IMG_MAPA}}", a_base64(img_mapa))
        except Exception:
            html = html.replace("{{IMG_MAPA}}", "")
    else:
        html = html.replace("{{IMG_MAPA}}", "")

    # Fotos embebidas
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

    reemplazos = {
        "{{NRO_TRABAJO}}":       str(datos.get("N___trabajo", "")),
        "{{ORDEN_SERVICIO}}":    str(datos.get("N___OS", "")),
        "{{SOLICITANTE}}":       "",
        "{{UBICACION}}":         datos.get("Name", ""),
        "{{FECHA_INGRESO}}":     datos.get("Fecha_Ingreso", ""),
        "{{DESCRIPCION}}":       datos.get("Tipo_de_Inspecci__n", ""),
        "{{OBSERVACIONES}}":     (datos.get("Observaciones_prev_") or "").replace("\n", "<br>"),
        "{{FECHA_REALIZADA}}":   datos.get("Fecha_inspeccionado", ""),
        "{{OPERARIO_CCTV}}":     datos.get("Operario", ""),
        "{{ESTADO_INSPECCION}}": datos.get("Estado_Inspecci__n", ""),
        "{{LIMPIEZA}}":          datos.get("LIMPIEZA", ""),
        "{{METRAJE}}":           datos.get("METRAJE", ""),
        "{{FECHA_ENTREGA}}":     datos.get("Fecha_entrega", ""),
        "{{OBS_ADIC}}":          (datos.get("Observaciones_adic_") or "").replace("\n", "<br>"),
        "{{CONTACTO}}":          "",
        "{{NUMERO_PROBLEMA}}":   "",
        "{{MATERIAL}}":          "",
        "{{FECHA_GENERACION}}":  datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    for marcador, valor in reemplazos.items():
        html = html.replace(marcador, valor or "")

    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(html)

    return html


def generar_pdf(ruta_html, ruta_pdf):
    """Convierte el HTML a PDF usando pdfkit + wkhtmltopdf."""
    try:
        import pdfkit
    except ImportError:
        raise ImportError("Instalá pdfkit:  pip install pdfkit")

    if not WKHTMLTOPDF:
        raise FileNotFoundError(
            "No se encontró wkhtmltopdf.exe.\n"
            "Verificá la ruta en la sección CONFIGURACIÓN del script."
        )

    config  = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF)
    options = {
        "page-size":              "A4",
        "margin-top":             "0mm",
        "margin-right":           "0mm",
        "margin-bottom":          "0mm",
        "margin-left":            "0mm",
        "encoding":               "UTF-8",
        "enable-local-file-access": None,
        "no-outline":             None,
        "quiet":                  None,
    }
    pdfkit.from_file(ruta_html, ruta_pdf, configuration=config, options=options)


# ─────────────────────────────────────────────────────────────────────────────
# DIÁLOGO
# ─────────────────────────────────────────────────────────────────────────────

class DialogoGenerarInforme(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generar Informe — Paso 3")
        self.setMinimumWidth(600)
        self.setMinimumHeight(700)
        self.datos_os   = None
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Scroll para el contenido
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        contenedor = QWidget()
        layout = QVBoxLayout(contenedor)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)
        scroll.setWidget(contenedor)
        outer.addWidget(scroll, 1)

        titulo = QLabel("Generar Informe de OS")
        titulo.setFont(QFont("Arial", 13, QFont.Bold))
        layout.addWidget(titulo)

        # ── Búsqueda ──
        grp_buscar = QGroupBox("Buscar OS en el GeoPackage")
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

        # ── Datos del correo (solo lectura) ──
        grp_info = QGroupBox("Datos del correo  (solo lectura)")
        form_info = QFormLayout(grp_info)
        form_info.setSpacing(5)
        self.f_nro_trabajo    = self._campo(readonly=True)
        self.f_orden_servicio = self._campo(readonly=True)
        self.f_name           = self._campo(readonly=True)
        self.f_fecha_ingreso  = self._campo(readonly=True)
        self.f_tipo_insp      = self._campo(readonly=True)
        self.f_obs_prev       = QTextEdit()
        self.f_obs_prev.setReadOnly(True)
        self.f_obs_prev.setFixedHeight(55)
        self.f_obs_prev.setStyleSheet("background:#f0f0f0; color:#555;")
        form_info.addRow("Nº Trabajo:",    self.f_nro_trabajo)
        form_info.addRow("N° OS:",         self.f_orden_servicio)
        form_info.addRow("Ubicación:",     self.f_name)
        form_info.addRow("Fecha ingreso:", self.f_fecha_ingreso)
        form_info.addRow("Tipo insp.:",    self.f_tipo_insp)
        form_info.addRow("Obs. previas:",  self.f_obs_prev)
        layout.addWidget(grp_info)

        # ── Datos de la inspección (editables) ──
        grp_insp = QGroupBox("Datos de la inspección")
        form_insp = QFormLayout(grp_insp)
        form_insp.setSpacing(6)
        self.f_fecha_inspeccionado = self._campo("dd/mm/aaaa")
        self.f_operario            = self._campo("ej: JS")
        self.f_estado_insp         = self._campo("ej: Realizada")
        self.f_limpieza            = self._campo("ej: Sí / No")
        self.f_metraje             = self._campo("ej: 5.3 m")
        self.f_fecha_entrega       = self._campo("dd/mm/aaaa")
        self.f_estado              = QComboBox()
        self.f_estado.addItems(["Pendiente", "Realizada", "Parcial", "No realizada"])
        form_insp.addRow("Fecha inspeccionado:", self.f_fecha_inspeccionado)
        form_insp.addRow("Operario:",            self.f_operario)
        form_insp.addRow("Estado inspección:",   self.f_estado_insp)
        form_insp.addRow("Limpieza:",            self.f_limpieza)
        form_insp.addRow("Metraje:",             self.f_metraje)
        form_insp.addRow("Fecha entrega:",       self.f_fecha_entrega)
        form_insp.addRow("Estado (workflow):",   self.f_estado)
        layout.addWidget(grp_insp)

        # ── Observaciones adicionales ──
        grp_obs = QGroupBox("Observaciones adicionales")
        v_obs = QVBoxLayout(grp_obs)
        self.f_obs_adic = QTextEdit()
        self.f_obs_adic.setFixedHeight(80)
        self.f_obs_adic.setPlaceholderText("Observaciones de la inspección realizada...")
        v_obs.addWidget(self.f_obs_adic)
        layout.addWidget(grp_obs)

        # ── Carpeta de la OS ──
        grp_carpeta = QGroupBox("Carpeta de la OS  (correo + fotos + mapa.png)")
        h_carp = QHBoxLayout(grp_carpeta)
        self.lbl_carpeta = QLabel("Sin seleccionar")
        self.lbl_carpeta.setWordWrap(True)
        btn_carpeta = QPushButton("Seleccionar…")
        btn_carpeta.clicked.connect(self._seleccionar_carpeta)
        h_carp.addWidget(self.lbl_carpeta, 1)
        h_carp.addWidget(btn_carpeta)
        layout.addWidget(grp_carpeta)

        layout.addStretch()

        # ── Botones (fuera del scroll) ──
        hbox = QHBoxLayout()
        hbox.setContentsMargins(12, 6, 12, 12)
        self.btn_generar = QPushButton("✓  Generar HTML + PDF")
        btn_cancel       = QPushButton("Cancelar")
        self.btn_generar.setEnabled(False)
        self.btn_generar.setMinimumHeight(36)
        self.btn_generar.setStyleSheet(
            "QPushButton{background:#325423;color:white;font-weight:bold;"
            "border-radius:3px;padding:0 16px;}"
            "QPushButton:hover{background:#3e6a2c;}"
            "QPushButton:disabled{background:#aaa;}"
        )
        self.btn_generar.clicked.connect(self._aceptar)
        btn_cancel.clicked.connect(self.reject)
        hbox.addStretch()
        hbox.addWidget(btn_cancel)
        hbox.addWidget(self.btn_generar)
        outer.addLayout(hbox)

    # ── Búsqueda ─────────────────────────────────────────────────────────────

    def _buscar(self):
        os_num = self.f_buscar.text().strip()
        if not os_num:
            return

        try:
            row = buscar_os_en_gpkg(os_num)
        except Exception as e:
            QMessageBox.critical(self, "Error al leer GeoPackage", str(e))
            return

        if row is None:
            self.lbl_estado_busqueda.setText("✗ No encontrada")
            self.lbl_estado_busqueda.setStyleSheet("color:red;")
            self.btn_generar.setEnabled(False)
            return

        self.datos_os = row

        ruta_guardada = str(row.get("RUTA") or "").strip()
        if ruta_guardada and os.path.isdir(ruta_guardada):
            self.carpeta_os = ruta_guardada
            self.lbl_carpeta.setText(ruta_guardada)

        self._poblar_formulario(row)
        self.lbl_estado_busqueda.setText("✓ Encontrada")
        self.lbl_estado_busqueda.setStyleSheet("color:green; font-weight:bold;")
        self.btn_generar.setEnabled(True)

    def _poblar_formulario(self, row):
        def val(campo):
            v = row.get(campo)
            return "" if v is None or str(v) in ("NULL", "None") else str(v)

        self.f_nro_trabajo.setText(val("N___trabajo"))
        self.f_orden_servicio.setText(val("N___OS"))
        self.f_name.setText(val("Name"))
        self.f_fecha_ingreso.setText(val("Fecha_Ingreso"))
        self.f_tipo_insp.setText(val("Tipo_de_Inspecci__n"))
        self.f_obs_prev.setPlainText(val("Observaciones_prev_"))
        self.f_fecha_inspeccionado.setText(val("Fecha_inspeccionado"))
        self.f_operario.setText(val("Operario"))
        self.f_estado_insp.setText(val("Estado_Inspecci__n"))
        self.f_limpieza.setText(val("LIMPIEZA"))
        self.f_metraje.setText(val("METRAJE"))
        self.f_fecha_entrega.setText(val("Fecha_entrega"))
        self.f_obs_adic.setPlainText(val("Observaciones_adic_"))
        idx = self.f_estado.findText(val("Estado"))
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
            errores.append("• Seleccioná la carpeta de la OS.")
        if not os.path.exists(PLANTILLA_HTML):
            errores.append(f"• Plantilla HTML no encontrada:\n  {PLANTILLA_HTML}")
        if errores:
            QMessageBox.warning(self, "No se puede generar", "\n".join(errores))
            return False
        return True

    def _aceptar(self):
        if not self._validar():
            return

        carpeta    = self.carpeta_os
        os_num     = self.f_orden_servicio.text().strip()

        datos = {
            "N___trabajo":          self.f_nro_trabajo.text().strip(),
            "N___OS":               os_num,
            "Name":                 self.f_name.text().strip(),
            "Fecha_Ingreso":        self.f_fecha_ingreso.text().strip(),
            "Tipo_de_Inspecci__n":  self.f_tipo_insp.text().strip(),
            "Observaciones_prev_":  self.f_obs_prev.toPlainText().strip(),
            "Operario":             self.f_operario.text().strip(),
            "Estado_Inspecci__n":   self.f_estado_insp.text().strip(),
            "LIMPIEZA":             self.f_limpieza.text().strip(),
            "Fecha_inspeccionado":  self.f_fecha_inspeccionado.text().strip(),
            "Fecha_entrega":        self.f_fecha_entrega.text().strip(),
            "METRAJE":              self.f_metraje.text().strip(),
            "Observaciones_adic_":  self.f_obs_adic.toPlainText().strip(),
            "Estado":               self.f_estado.currentText(),
            "RUTA":                 carpeta,
        }

        # 1. Imágenes
        rutas_imagenes = listar_imagenes(carpeta)

        # 2. Mapa
        mapa_candidatos = glob.glob(os.path.join(os.path.realpath(carpeta), "mapa.*"))
        datos["img_mapa"] = mapa_candidatos[0] if mapa_candidatos else ""

        # 3. Generar HTML
        nombre_html = f"informe_OS_{os_num}.html"
        ruta_html   = os.path.join(carpeta, nombre_html)
        try:
            generar_html(datos, rutas_imagenes, ruta_html)
        except Exception as e:
            QMessageBox.critical(self, "Error al generar HTML", str(e))
            return

        # 4. Generar PDF
        ruta_pdf = ruta_html.replace(".html", ".pdf")
        pdf_ok   = False
        try:
            generar_pdf(ruta_html, ruta_pdf)
            pdf_ok = True
        except Exception as e:
            QMessageBox.warning(self, "PDF no generado", str(e))

        # 5. Actualizar GeoPackage
        try:
            actualizar_os_en_gpkg(os_num, {
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
            QMessageBox.warning(self, "Error al actualizar GeoPackage", str(e))

        # 6. Mensaje final
        msg = (
            f"✓ OS {os_num} procesada.\n\n"
            f"  Imágenes incluidas : {len(rutas_imagenes)}\n"
            f"  Mapa               : {'Sí' if datos['img_mapa'] else 'No'}\n"
            f"  HTML               : {nombre_html}\n"
            f"  PDF                : {'✓  ' + os.path.basename(ruta_pdf) if pdf_ok else '✗  no generado'}\n\n"
            "¿Abrís el PDF?"
        )
        if pdf_ok:
            resp = QMessageBox.question(self, "Informe generado", msg,
                                        QMessageBox.Yes | QMessageBox.No)
            if resp == QMessageBox.Yes:
                os.startfile(ruta_pdf)
        else:
            QMessageBox.information(self, "Informe generado", msg)

        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA — correr con:  python generar_informe_desde_fuera.py
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = DialogoGenerarInforme()
    dlg.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
