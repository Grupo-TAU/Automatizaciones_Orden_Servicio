import os

from qgis.gui import QgsMapToolEmitPoint
from qgis.utils import iface

from PyQt5.QtCore import Qt, QDate
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QMessageBox, QGroupBox, QApplication,
)
from PyQt5.QtGui import QFont, QCursor

from .capa_utils import RAIZ_IMAGENES, buscar_punto_padron, agregar_feature_os, CAPA_PADRONES
from .pdf_parser import parsear_pdf_os, pdfplumber_disponible, instalar_pdfplumber


class _CapturadorPunto(QgsMapToolEmitPoint):
    """Herramienta temporal: captura un clic izquierdo en el canvas."""

    def __init__(self, canvas, callback):
        super().__init__(canvas)
        self.canvasClicked.connect(callback)


class DialogoRegistroOS(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar OS")
        self.setMinimumWidth(540)
        self.punto_xy = None
        self._capturador = None
        self._herramienta_previa = None
        self._build_ui()

    def _campo(self, placeholder=""):
        w = QLineEdit()
        w.setPlaceholderText(placeholder)
        return w

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        titulo = QLabel("Registro de OS — Datos del correo")
        titulo.setFont(QFont("Arial", 13, QFont.Bold))
        layout.addWidget(titulo)

        # ── Ubicación en el mapa ─────────────────────────────────────────
        grp_mapa = QGroupBox("Ubicación en el mapa *")
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

        self.btn_instalar_dep = QPushButton("Instalar dependencia (pdfplumber)…")
        self.btn_instalar_dep.setVisible(not pdfplumber_disponible())
        self.btn_instalar_dep.clicked.connect(self._instalar_dependencia)
        h_pdf.addWidget(self.btn_instalar_dep)

        layout.addWidget(grp_pdf)

        # ── Datos ────────────────────────────────────────────────────────
        grp = QGroupBox("Datos de la OS")
        form = QFormLayout(grp)
        form.setSpacing(6)

        self.f_orden_servicio = self._campo("ej: 5337775")
        self.f_fecha_ingreso = self._campo("dd/mm/aaaa")
        self.f_fecha_ingreso.setText(QDate.currentDate().toString("dd/MM/yyyy"))
        self.f_ubicacion = self._campo("ej: 25 DE MAYO Nº 259")
        self.f_descripcion = self._campo("ej: Inspección cámara televisada")
        self.f_n_problema = self._campo("ej: 123456")
        self.f_contrato = self._campo("ej: Baderery-Giberol")
        self.f_n_trabajo = self._campo("ej: 12345")
        self.f_tipo = self._campo("ej: Reclamo")

        form.addRow("Orden de Servicio:", self.f_orden_servicio)
        form.addRow("Fecha ingreso:", self.f_fecha_ingreso)
        form.addRow("Ubicación:", self.f_ubicacion)
        form.addRow("Descripción:", self.f_descripcion)
        form.addRow("N° Problema:", self.f_n_problema)
        form.addRow("Contrato:", self.f_contrato)
        form.addRow("N° Trabajo:", self.f_n_trabajo)
        form.addRow("Tipo:", self.f_tipo)
        layout.addWidget(grp)

        # ── Botones ──────────────────────────────────────────────────────
        hbox = QHBoxLayout()
        btn_ok = QPushButton("✓ Registrar OS")
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
        self.lbl_punto.setText(f"X: {punto.x():.2f} | Y: {punto.y():.2f}")
        self.lbl_punto.setStyleSheet("color:green; font-weight:bold;")
        self.raise_()
        self.activateWindow()

    # ── Instalación de pdfplumber ─────────────────────────────────────────────
    def _instalar_dependencia(self):
        respuesta = QMessageBox.question(
            self, "Instalar pdfplumber",
            "Esto va a instalar la librería pdfplumber en el intérprete de QGIS "
            "usando pip (requiere conexión a internet). Puede tardar unos segundos.\n\n"
            "¿Confirmás la instalación?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if respuesta != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            ok, salida = instalar_pdfplumber()
        finally:
            QApplication.restoreOverrideCursor()

        if ok and pdfplumber_disponible():
            self.btn_instalar_dep.setVisible(False)
            QMessageBox.information(self, "Instalación completa", "pdfplumber se instaló correctamente.")
        else:
            QMessageBox.critical(
                self, "Error al instalar",
                "No se pudo instalar pdfplumber.\n\nSalida de pip:\n" + salida[-2000:],
            )

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
            'fecha_ingreso': self.f_fecha_ingreso,
            'descripcion': self.f_descripcion,
            'ubicacion': self.f_ubicacion,
            'n_problema': self.f_n_problema,
            'sector': self.f_contrato,
            'tipo': self.f_tipo,
        }
        for clave, widget in setters.items():
            if clave in datos:
                widget.setText(datos[clave])

        self.lbl_pdf.setText(f"✓ {os.path.basename(ruta_pdf)}")
        self.lbl_pdf.setStyleSheet("color:green; font-weight:bold;")

        # ── Ubicar el punto automáticamente a partir del padrón ────────────
        if 'padron' in datos:
            punto = buscar_punto_padron(datos['padron'])
            if punto is not None:
                self.punto_xy = punto
                self.lbl_punto.setText(
                    f"X: {punto.x():.2f} | Y: {punto.y():.2f} "
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
            "N°_OS": self.f_orden_servicio.text().strip(),
            "Ubicación": self.f_ubicacion.text().strip(),
            "Fecha_Ingreso": self.f_fecha_ingreso.text().strip(),
            "Descripción": self.f_descripcion.text().strip(),
            "N_Problema": self.f_n_problema.text().strip(),
            "Contrato": self.f_contrato.text().strip(),
            "Tipo": self.f_tipo.text().strip(),
            "Etapa": "Pendiente",
            "Restringir": "Si",
        }

        # "N° Trabajo" se ingresa a mano; si se deja vacío, se respeta la
        # expresión por defecto de la capa (ej: maximum("N° Trabajo") + 1).
        n_trabajo = self.f_n_trabajo.text().strip()
        if n_trabajo:
            datos["N° Trabajo"] = n_trabajo

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
