"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  SCRIPT: cargar_os_Futuro.py                                                 ║
║  Descripción: Registra la OS recibida por correo en la capa                  ║
║               inspecciones_nuevas_OS. El punto se ubica haciendo clic en el  ║
║               mapa de QGIS. Soporta carga automática desde el PDF de la IM.  ║
║  Uso: Consola Python de QGIS                                                 ║
║  Autor: Grupo TAU – DICA                                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

DEPENDENCIA EXTERNA:
  pdfplumber — necesaria para parsear el PDF de la IM.
  Instalar una sola vez desde la consola de QGIS:
      import subprocess, sys, os
      target = os.path.join(sys.prefix, 'Lib', 'site-packages')
      subprocess.call([os.path.join(sys.prefix, 'python.exe'),
                       '-m', 'pip', 'install', 'pdfplumber', '--target', target])

"""

import os
import re
from qgis.core import (
    QgsProject,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateTransform,
)
from qgis.gui import QgsMapToolEmitPoint
from qgis.utils import iface
from PyQt5.QtCore import QVariant, Qt, QDate
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QMessageBox, QGroupBox,
)
from PyQt5.QtGui import QFont

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

RAIZ_IMAGENES  = r"G:\Unidades compartidas\GRUPO TAU\INTENDENCIA DE MONTEVIDEO\SOMS\IMAGENES_OS"
CAPA_OS        = "inspecciones_nuevas_OS"
CAPA_PADRONES  = "padrones"
CAMPO_PADRON   = "padron"

CAMPOS_PASO1 = [
    ("N°_OS",         QVariant.String),
    ("Ubicación",     QVariant.String),
    ("Fecha_Ingreso", QVariant.Date),
    ("Descripción",   QVariant.String),
    ("N_Problema",    QVariant.String),
    ("Sector",        QVariant.String),
    ("Etapa",         QVariant.String),
    ("Restringir",    QVariant.String),
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
            "  import subprocess, sys, os\n"
            "  target = os.path.join(sys.prefix, 'Lib', 'site-packages')\n"
            "  subprocess.call([os.path.join(sys.prefix, 'python.exe'),\n"
            "                   '-m', 'pip', 'install', 'pdfplumber', '--target', target])"
        )

    datos = {}

    with pdfplumber.open(ruta_pdf) as pdf:
        texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

        # ── N°_OS ──────────────────────────────────────────────────────────
        m = re.search(r'Orden de Servicio\s+(\d+)', texto)
        if m:
            datos['orden_servicio'] = m.group(1)

        # ── Fecha_Ingreso — timestamp arriba a la derecha (antes del título,
        #   presente en ambos tipos de OS) ───────────────────────────────
        m = re.search(r'(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}.*?Orden de Servicio', texto, re.DOTALL)
        if m:
            datos['fecha_ingreso'] = m.group(1)

        # ── Descripción — entre "Observación:" y "Problema Nº:" ───────────
        m = re.search(r'Observaci[oó]n:\s*(.+?)\s*Problema\s*N[°º]:', texto, re.DOTALL)
        if m:
            datos['descripcion'] = re.sub(r'\s+', ' ', m.group(1)).strip()

        # ── Ubicación — entre "Ubicación:" y "Observación:" ───────────────
        m = re.search(r'Ubicaci[oó]n:\s*(.+?)\s*Observaci[oó]n:', texto, re.DOTALL)
        if m:
            ubic = re.sub(r'\s+', ' ', m.group(1)).strip()
            ubic = re.sub(r'N[°º]:\s*', 'Nº ', ubic)
            datos['ubicacion'] = ubic

            # ── Padrón — entre "[Padron: " y "]" dentro de la Ubicación ────
            m_pad = re.search(r'\[Padron:\s*(\d+)\]', ubic, re.IGNORECASE)
            if m_pad:
                datos['padron'] = m_pad.group(1)

        # ── N_Problema — entre "Problema N°:" y "Fecha Problema" ──────────
        m = re.search(r'Problema\s*N[°º]:\s*(.+?)\s*Fecha problema:', texto, re.DOTALL)
        if m:
            datos['n_problema'] = re.sub(r'\s+', ' ', m.group(1)).strip()

        # ── Sector — entre "Sector:" y "Generada" ──────────────────────────
        m = re.search(r'Sector:\s*(.+?)\s*Generada', texto, re.DOTALL)
        if m:
            datos['sector'] = re.sub(r'\s+', ' ', m.group(1)).strip()

    return datos


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES QGIS
# ─────────────────────────────────────────────────────────────────────────────

def obtener_capa(nombre):
    capas = QgsProject.instance().mapLayersByName(nombre)
    return capas[0] if capas else None


def buscar_punto_padron(numero_padron):
    """
    Busca en la capa CAPA_PADRONES el feature cuyo campo CAMPO_PADRON coincide
    con numero_padron y devuelve el centroide (QgsPointXY) reproyectado al CRS
    del proyecto. Si la capa/campo no existen, o hay 0 o más de 1 coincidencia,
    devuelve None (el usuario deberá hacer clic manualmente en el mapa).
    """
    capa = obtener_capa(CAPA_PADRONES)
    if capa is None:
        return None

    idx = capa.fields().indexOf(CAMPO_PADRON)
    if idx < 0:
        return None

    numero_padron = str(numero_padron).strip()
    coincidencias = [
        f for f in capa.getFeatures()
        if str(f[CAMPO_PADRON]).strip() == numero_padron
    ]
    if len(coincidencias) != 1:
        return None

    geom = coincidencias[0].geometry()
    if geom is None or geom.isEmpty():
        return None

    punto = geom.centroid().asPoint()

    crs_proyecto = QgsProject.instance().crs()
    if capa.crs() != crs_proyecto:
        transformador = QgsCoordinateTransform(capa.crs(), crs_proyecto, QgsProject.instance())
        punto = transformador.transform(punto)

    return punto


def agregar_feature_os(datos, punto_xy):
    capa = obtener_capa(CAPA_OS)
    if capa is None:
        raise ValueError(f"No se encontró la capa '{CAPA_OS}' en el proyecto.")

    if not capa.isEditable():
        capa.startEditing()

    feat = QgsFeature(capa.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(punto_xy))

    indices_seteados = set()
    for nombre_campo, tipo in CAMPOS_PASO1:
        idx = capa.fields().indexOf(nombre_campo)
        if idx >= 0 and nombre_campo in datos:
            valor = datos[nombre_campo]
            if tipo == QVariant.Date and isinstance(valor, str) and valor:
                valor = QDate.fromString(valor, "dd/MM/yyyy")
            feat.setAttribute(idx, valor)
            indices_seteados.add(idx)

    # Evaluar expresiones por defecto de la capa para campos no seteados
    # (ej: "N° Trabajo" con expresión maximum("N° Trabajo") + 1)
    for idx in range(capa.fields().count()):
        if idx not in indices_seteados:
            defn = capa.defaultValueDefinition(idx)
            if defn.isValid():
                feat.setAttribute(idx, capa.defaultValue(idx))

    capa.addFeature(feat)
    capa.commitChanges()
    capa.triggerRepaint()


# ─────────────────────────────────────────────────────────────────────────────
# DIÁLOGO
# ─────────────────────────────────────────────────────────────────────────────

class DialogoRegistroOS(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar OS")
        self.setMinimumWidth(540)
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

        # ── Datos ────────────────────────────────────────────────────────
        grp = QGroupBox("Datos de la OS")
        form = QFormLayout(grp)
        form.setSpacing(6)

        self.f_orden_servicio = self._campo("ej: 5337775")
        self.f_fecha_ingreso  = self._campo("dd/mm/aaaa")
        self.f_ubicacion      = self._campo("ej: 25 DE MAYO Nº 259")
        self.f_descripcion    = self._campo("ej: Inspección cámara televisada")
        self.f_n_problema     = self._campo("ej: 123456")
        self.f_sector         = self._campo("ej: Baderery-Giberol")

        form.addRow("Orden de Servicio:", self.f_orden_servicio)
        form.addRow("Fecha ingreso:",     self.f_fecha_ingreso)
        form.addRow("Ubicación:",         self.f_ubicacion)
        form.addRow("Descripción:",       self.f_descripcion)
        form.addRow("N° Problema:",       self.f_n_problema)
        form.addRow("Sector:",            self.f_sector)
        layout.addWidget(grp)

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
        self.lbl_punto.setText("Hacé clic en el mapa…")
        self.lbl_punto.setStyleSheet("color:#e67e00; font-weight:bold;")

    def _punto_capturado(self, punto, boton):
        if boton != Qt.LeftButton:
            return
        self.punto_xy = punto
        iface.mapCanvas().setMapTool(self._herramienta_previa)
        self._capturador = None
        self.lbl_punto.setText(f"X: {punto.x():.2f}  |  Y: {punto.y():.2f}")
        self.lbl_punto.setStyleSheet("color:green; font-weight:bold;")
        self.raise_()
        self.activateWindow()

    # ── Carga desde PDF ──────────────────────────────────────────────────────

    def _cargar_pdf(self):
        ruta_pdf, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar PDF de la OS", RAIZ_IMAGENES, "PDF (*.pdf *.PDF)"
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
            'n_problema':     self.f_n_problema,
            'sector':         self.f_sector,
        }
        for clave, widget in setters.items():
            if clave in datos:
                widget.setText(datos[clave])

        self.lbl_pdf.setText(f"✓  {os.path.basename(ruta_pdf)}")
        self.lbl_pdf.setStyleSheet("color:green; font-weight:bold;")

        # ── Ubicar el punto automáticamente a partir del padrón ────────────
        if 'padron' in datos:
            punto = buscar_punto_padron(datos['padron'])
            if punto is not None:
                self.punto_xy = punto
                self.lbl_punto.setText(
                    f"X: {punto.x():.2f}  |  Y: {punto.y():.2f}  "
                    f"(Padrón {datos['padron']} — automático)"
                )
                self.lbl_punto.setStyleSheet("color:green; font-weight:bold;")
            else:
                QMessageBox.warning(
                    self, "Padrón no ubicado",
                    f"No se encontró (o hay más de una coincidencia para) el "
                    f"padrón {datos['padron']} en la capa '{CAPA_PADRONES}'.\n\n"
                    "Hacé clic manualmente en el mapa para ubicar la OS."
                )

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
            "N°_OS":         self.f_orden_servicio.text().strip(),
            "Ubicación":     self.f_ubicacion.text().strip(),
            "Fecha_Ingreso": self.f_fecha_ingreso.text().strip(),
            "Descripción":   self.f_descripcion.text().strip(),
            "N_Problema":    self.f_n_problema.text().strip(),
            "Sector":        self.f_sector.text().strip(),
            "Etapa":         "Pendiente",
            "Restringir":    "Si",
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
            f"✓ OS {datos['N°_OS']} registrada correctamente.\n\n"
            f"  Ubicación : {datos['Ubicación']}\n"
            f"  Etapa     : Pendiente\n"
            f"  Restringir: Si"
        )
        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

# Variable global para evitar que el garbage collector destruya el diálogo
_dlg_registro = None

def main():
    global _dlg_registro
    _dlg_registro = DialogoRegistroOS()
    _dlg_registro.show()  # no-modal: permite clic en el mapa con el diálogo abierto

main()
