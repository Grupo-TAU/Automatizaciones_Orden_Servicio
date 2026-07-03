"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  SCRIPT: cargar_os_Futuro.py  —  PASO 1 de 3                                ║
║  Descripción: Registra la OS recibida por correo en la capa inspecciones_OS. ║
║               El punto se ubica haciendo clic en el mapa de QGIS.            ║
║               Soporta carga automática de datos desde el PDF de la IM.       ║
║  Uso: Consola Python de QGIS                                                 ║
║  Autor: Grupo TAU – DICA                                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

DEPENDENCIA EXTERNA:
  pdfplumber — necesaria para parsear el PDF de la IM.
  Instalar una sola vez desde la consola de QGIS:
      import subprocess, sys
      subprocess.call([sys.executable, '-m', 'pip', 'install', 'pdfplumber'])

FLUJO COMPLETO:
  Paso 1 — cargar_os_Futuro.py  ← este script
  Paso 2 — edición nativa QGIS / trabajo de campo
  Paso 3 — generar_informe.py
"""

import os
import re
from datetime import datetime
from qgis.core import (
    QgsProject,
    QgsFeature,
    QgsGeometry,
    QgsField,
)
from qgis.gui import QgsMapToolEmitPoint
from PyQt5.QtCore import QVariant, Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QTextEdit, QMessageBox, QGroupBox,
)
from PyQt5.QtGui import QFont

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

RAIZ_IMAGENES = r"G:\Unidades compartidas\GRUPO TAU\INTENDENCIA DE MONTEVIDEO\SOMS\IMAGENES_OS"
CAPA_OS       = "inspecciones_OS"

CAMPOS_PASO1 = [
    ("N__trabajo",          QVariant.String),
    ("N__OS",               QVariant.String),
    ("Name",                QVariant.String),
    ("Fecha_Ingreso",       QVariant.String),
    ("Tipo_de_Inspecci__n", QVariant.String),
    ("Observaciones_prev_", QVariant.String),
    ("Estado",              QVariant.String),
    ("RUTA",                QVariant.String),
]

# ─────────────────────────────────────────────────────────────────────────────
# HERRAMIENTA DE CAPTURA DE PUNTO EN EL MAPA
# ─────────────────────────────────────────────────────────────────────────────

class _CapturadorPunto(QgsMapToolEmitPoint):
    """Herramienta temporal: captura un clic izquierdo en el canvas."""
    def __init__(self, canvas, callback):
        super().__init__(canvas)
        self.canvasClicked.connect(callback)


# ─────────────────────────────────────────────────────────────────────────────
# PARSER PDF
# ─────────────────────────────────────────────────────────────────────────────

def parsear_pdf_os(ruta_pdf):
    """
    Extrae los datos de la OS desde el PDF del Sistema Único de Respuesta (IM).
    Devuelve dict con los campos del formulario.
    Requiere pdfplumber (pip install pdfplumber).
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "Falta la librería pdfplumber.\n\n"
            "Instalala ejecutando en la consola de QGIS:\n"
            "  import subprocess, sys\n"
            "  subprocess.call([sys.executable, '-m', 'pip', 'install', 'pdfplumber'])"
        )

    datos = {}

    with pdfplumber.open(ruta_pdf) as pdf:
        p1 = pdf.pages[0].extract_text() or ""
        p2 = (pdf.pages[1].extract_text() or "") if len(pdf.pages) > 1 else ""

        # ── Orden de Servicio ──────────────────────────────────────────────
        m = re.search(r'Orden de Servicio\s+(\d+)', p1)
        if m:
            datos['orden_servicio'] = m.group(1)

        # ── Fecha ingreso ──────────────────────────────────────────────────
        m = re.search(r'(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}', p1)
        if m:
            datos['fecha_ingreso'] = m.group(1)

        # ── Descripción ────────────────────────────────────────────────────
        lineas = [l.strip() for l in p1.splitlines() if l.strip()]
        for i, linea in enumerate(lineas):
            if re.match(r'Orden de Servicio\s+\d+', linea):
                for j in range(i + 1, min(i + 4, len(lineas))):
                    if not re.match(r'\d{2}/\d{2}/\d{4}', lineas[j]):
                        datos['descripcion'] = lineas[j]
                        break
                break

        # ── Ubicación ──────────────────────────────────────────────────────
        m = re.search(r'Ubicaci[oó]n:\s*(.+?)(?:\n|$)', p1)
        if m:
            ubic = m.group(1).strip()
            ubic = re.sub(r'\s*\[Padron[^\]]*\]', '', ubic)
            ubic = re.sub(r'\s+entre\s+.+$', '', ubic, flags=re.IGNORECASE)
            ubic = re.sub(r'N[°º]:\s*', 'Nº ', ubic)
            datos['ubicacion'] = ubic.strip()

        # ── Solicitante + Contacto ─────────────────────────────────────────
        m = re.search(
            r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,40})\s+\d{5,8}\s+(\d{6,9})\s+(\d{6,9})',
            p2, re.MULTILINE
        )
        if m:
            datos['solicitante'] = m.group(1).strip()
            tel = m.group(2).strip()
            cel = m.group(3).strip()
            partes = []
            if tel:
                partes.append(f"Tel: {tel}")
            if cel:
                partes.append(f"Cel: {cel}")
            datos['contacto'] = " / ".join(partes)

        # ── Observaciones del solicitante ──────────────────────────────────
        m = re.search(
            r'\d{6,9}\s+\d{6,9}\s*\n(.+?)\nObservaciones:',
            p2, re.DOTALL
        )
        if m:
            obs = m.group(1).strip()
            if obs:
                datos['obs_cliente'] = obs

    return datos


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES QGIS
# ─────────────────────────────────────────────────────────────────────────────

def obtener_capa(nombre):
    capas = QgsProject.instance().mapLayersByName(nombre)
    return capas[0] if capas else None


def agregar_feature_os(datos, punto_xy):
    capa = obtener_capa(CAPA_OS)
    if capa is None:
        raise ValueError(f"No se encontró la capa '{CAPA_OS}' en el proyecto.")

    if not capa.isEditable():
        capa.startEditing()

    feat = QgsFeature(capa.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(punto_xy))

    for nombre_campo, _ in CAMPOS_PASO1:
        if nombre_campo in datos and capa.fields().indexOf(nombre_campo) >= 0:
            feat.setAttribute(nombre_campo, datos[nombre_campo])

    feat.setAttribute("fecha_carga", datetime.now().strftime("%Y-%m-%d %H:%M"))

    capa.addFeature(feat)
    capa.commitChanges()
    capa.triggerRepaint()


# ─────────────────────────────────────────────────────────────────────────────
# DIÁLOGO
# ─────────────────────────────────────────────────────────────────────────────

class DialogoRegistroOS(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar OS — Paso 1")
        self.setMinimumWidth(540)
        self.carpeta_os          = ""
        self.punto_xy            = None
        self._capturador         = None
        self._herramienta_previa = None
        self._build_ui()

    def _campo(self, placeholder=""):
        w = QLineEdit()
        w.setPlaceholderText(placeholder)
        return w

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        titulo = QLabel("Registro de OS  —  Datos del correo")
        titulo.setFont(QFont("Arial", 13, QFont.Bold))
        layout.addWidget(titulo)

        # ── Ubicación en el mapa ─────────────────────────────────────────
        grp_mapa = QGroupBox("Ubicación en el mapa  *")
        h_mapa = QHBoxLayout(grp_mapa)
        btn_punto = QPushButton("Hacer clic en el mapa…")
        btn_punto.setMinimumHeight(30)
        btn_punto.setStyleSheet(
            "QPushButton{background:#0a3d62;color:white;font-weight:bold;"
            "border-radius:3px;padding:0 14px;}"
            "QPushButton:hover{background:#1a5276;}"
        )
        btn_punto.clicked.connect(self._activar_captura)
        self.lbl_punto = QLabel("Sin punto seleccionado")
        self.lbl_punto.setStyleSheet("color:#999; font-style:italic;")
        h_mapa.addWidget(btn_punto)
        h_mapa.addWidget(self.lbl_punto, 1)
        layout.addWidget(grp_mapa)

        # ── Carga desde PDF ──────────────────────────────────────────────
        grp_pdf = QGroupBox("Carga automática desde PDF")
        h_pdf = QHBoxLayout(grp_pdf)
        btn_pdf = QPushButton("Cargar desde PDF…")
        btn_pdf.setMinimumHeight(30)
        btn_pdf.setStyleSheet(
            "QPushButton{background:#325423;color:white;font-weight:bold;"
            "border-radius:3px;padding:0 14px;}"
            "QPushButton:hover{background:#3e6a2c;}"
        )
        btn_pdf.clicked.connect(self._cargar_pdf)
        self.lbl_pdf = QLabel("Sin PDF seleccionado")
        self.lbl_pdf.setStyleSheet("color:#666; font-style:italic;")
        h_pdf.addWidget(btn_pdf)
        h_pdf.addWidget(self.lbl_pdf, 1)
        layout.addWidget(grp_pdf)

        # ── Datos del correo ─────────────────────────────────────────────
        grp = QGroupBox("Datos del correo")
        form = QFormLayout(grp)
        form.setSpacing(6)

        self.f_nro_trabajo    = self._campo("ej: 1  (completar manualmente)")
        self.f_orden_servicio = self._campo("ej: 5337775")
        self.f_solicitante    = self._campo("ej: BEATRIZ TOLMEO")
        self.f_fecha_ingreso  = self._campo("dd/mm/aaaa")
        self.f_ubicacion      = self._campo("ej: 25 DE MAYO Nº 259")
        self.f_descripcion    = self._campo("ej: Inspeccion camara televisada")

        form.addRow("Nº Trabajo:",        self.f_nro_trabajo)
        form.addRow("Orden de Servicio:", self.f_orden_servicio)
        form.addRow("Solicitante:",       self.f_solicitante)
        form.addRow("Fecha ingreso:",     self.f_fecha_ingreso)
        form.addRow("Ubicación:",         self.f_ubicacion)
        form.addRow("Descripción:",       self.f_descripcion)
        layout.addWidget(grp)

        # ── Observaciones del solicitante ────────────────────────────────
        grp_obs = QGroupBox("Observaciones del solicitante")
        v_obs = QVBoxLayout(grp_obs)
        self.f_observaciones = QTextEdit()
        self.f_observaciones.setFixedHeight(65)
        self.f_observaciones.setPlaceholderText(
            "Observaciones/notas del solicitante (se completa desde el PDF)...")
        v_obs.addWidget(self.f_observaciones)
        layout.addWidget(grp_obs)

        # ── Carpeta de la OS ─────────────────────────────────────────────
        grp_carpeta = QGroupBox("Carpeta de la OS  (donde guardás el archivo del correo)")
        h = QHBoxLayout(grp_carpeta)
        self.lbl_carpeta = QLabel("Sin seleccionar")
        self.lbl_carpeta.setWordWrap(True)
        btn_carpeta = QPushButton("Seleccionar…")
        btn_carpeta.clicked.connect(self._seleccionar_carpeta)
        h.addWidget(self.lbl_carpeta, 1)
        h.addWidget(btn_carpeta)
        layout.addWidget(grp_carpeta)

        # ── Botones ──────────────────────────────────────────────────────
        hbox = QHBoxLayout()
        btn_ok     = QPushButton("✓  Registrar OS")
        btn_cancel = QPushButton("Cancelar")
        btn_ok.setDefault(True)
        btn_ok.setMinimumHeight(34)
        btn_ok.setStyleSheet(
            "QPushButton{background:#325423;color:white;font-weight:bold;"
            "border-radius:3px;padding:0 14px;}"
            "QPushButton:hover{background:#3e6a2c;}"
        )
        btn_ok.clicked.connect(self._aceptar)
        btn_cancel.clicked.connect(self.reject)
        hbox.addStretch()
        hbox.addWidget(btn_cancel)
        hbox.addWidget(btn_ok)
        layout.addLayout(hbox)

    # ── Captura de punto en el mapa ──────────────────────────────────────────

    def _activar_captura(self):
        canvas = iface.mapCanvas()
        self._herramienta_previa = canvas.mapTool()
        self._capturador = _CapturadorPunto(canvas, self._punto_capturado)
        canvas.setMapTool(self._capturador)
        self.hide()

    def _punto_capturado(self, punto, boton):
        if boton != Qt.LeftButton:
            return
        self.punto_xy = punto
        canvas = iface.mapCanvas()
        canvas.setMapTool(self._herramienta_previa)
        self._capturador = None
        self.show()
        self.raise_()
        self.activateWindow()
        self.lbl_punto.setText(f"X: {punto.x():.2f}  |  Y: {punto.y():.2f}")
        self.lbl_punto.setStyleSheet("color:green; font-weight:bold;")

    # ── Carga desde PDF ──────────────────────────────────────────────────────

    def _cargar_pdf(self):
        inicio = self.carpeta_os or RAIZ_IMAGENES
        ruta_pdf, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar PDF de la OS", inicio, "PDF (*.pdf *.PDF)"
        )
        if not ruta_pdf:
            return

        try:
            datos = parsear_pdf_os(ruta_pdf)
        except ImportError as e:
            QMessageBox.warning(self, "Librería faltante", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "Error al leer el PDF", str(e))
            return

        setters = {
            'orden_servicio': self.f_orden_servicio,
            'fecha_ingreso':  self.f_fecha_ingreso,
            'descripcion':    self.f_descripcion,
            'ubicacion':      self.f_ubicacion,
            'solicitante':    self.f_solicitante,
        }
        for clave, widget in setters.items():
            if clave in datos:
                widget.setText(datos[clave])

        if 'obs_cliente' in datos:
            self.f_observaciones.setPlainText(datos['obs_cliente'])

        nombre = os.path.basename(ruta_pdf)
        self.lbl_pdf.setText(f"✓  {nombre}")
        self.lbl_pdf.setStyleSheet("color:green; font-weight:bold;")

        if not self.carpeta_os:
            carpeta = os.path.dirname(ruta_pdf)
            self.carpeta_os = carpeta
            self.lbl_carpeta.setText(carpeta)

    # ── Carpeta ──────────────────────────────────────────────────────────────

    def _seleccionar_carpeta(self):
        ruta = QFileDialog.getExistingDirectory(
            self, "Carpeta de la OS", self.carpeta_os or RAIZ_IMAGENES
        )
        if ruta:
            self.carpeta_os = ruta
            self.lbl_carpeta.setText(ruta)

    # ── Validación ───────────────────────────────────────────────────────────

    def _validar(self):
        errores = []
        if self.punto_xy is None:
            errores.append("• Hacé clic en el mapa para ubicar la OS.")
        if not self.f_orden_servicio.text().strip():
            errores.append("• Orden de Servicio es obligatoria.")
        if errores:
            QMessageBox.warning(self, "Campos incompletos", "\n".join(errores))
            return False
        return True

    # ── Aceptar ──────────────────────────────────────────────────────────────

    def _aceptar(self):
        if not self._validar():
            return

        datos = {
            "N__trabajo":          self.f_nro_trabajo.text().strip(),
            "N__OS":               self.f_orden_servicio.text().strip(),
            "Name":                self.f_ubicacion.text().strip(),
            "Fecha_Ingreso":       self.f_fecha_ingreso.text().strip(),
            "Tipo_de_Inspecci__n": self.f_descripcion.text().strip(),
            "Observaciones_prev_": self.f_observaciones.toPlainText().strip(),
            "Estado":              "Pendiente",
            "RUTA":                self.carpeta_os,
        }

        try:
            agregar_feature_os(datos, self.punto_xy)
        except Exception as e:
            QMessageBox.critical(self, "Error al registrar en QGIS", str(e))
            return

        iface.mapCanvas().setCenter(self.punto_xy)
        iface.mapCanvas().zoomScale(2000)
        iface.mapCanvas().refresh()

        QMessageBox.information(
            self, "OS Registrada",
            f"✓ OS {datos['N__OS']} registrada en QGIS.\n\n"
            f"  Ubicación  : {datos['Name']}\n"
            f"  Estado     : Pendiente\n"
            f"  Carpeta    : {self.carpeta_os or '—'}\n\n"
            "Cuando la inspección esté completa usá 'Generar Informe' (paso 3)."
        )
        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

def main():
    dlg = DialogoRegistroOS()
    dlg.exec_()

main()
