from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QLineEdit, QPlainTextEdit, QPushButton, QLabel,
    QFileDialog, QMessageBox, QApplication,
)

from . import config, conexion, importar
from .dialogo_conexion import ESTILO_PRINCIPAL


class DialogoImportar(QDialog):
    """Trae el GeoPackage editado en campo y hace el UPSERT en PostGIS.

    "Probar" carga el staging, muestra qué pasaría y lo borra sin tocar la tabla.
    "Importar" hace lo mismo, pide confirmación con esos números y recién ahí
    ejecuta el UPSERT.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar cambios de campo")
        self.setMinimumWidth(620)
        self.ruta = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form_operario = QFormLayout()
        self.f_iniciales = QLineEdit(conexion.leer_iniciales())
        self.f_iniciales.setPlaceholderText("ej: NA")
        self.f_iniciales.setMaxLength(10)
        self.f_iniciales.setToolTip(
            "Se usan para nombrar la tabla temporal (inspecciones_staging_na), "
            "así dos personas importando a la vez no se pisan."
        )
        form_operario.addRow("Iniciales del operario:", self.f_iniciales)
        layout.addLayout(form_operario)

        h_archivo = QHBoxLayout()
        btn_archivo = QPushButton("Elegir GeoPackage…")
        btn_archivo.clicked.connect(self._elegir_archivo)
        self.lbl_archivo = QLabel("Sin archivo seleccionado")
        self.lbl_archivo.setStyleSheet("color:#999; font-style:italic;")
        h_archivo.addWidget(btn_archivo)
        h_archivo.addWidget(self.lbl_archivo, 1)
        layout.addLayout(h_archivo)

        form = QFormLayout()
        self.cb_capa = QComboBox()
        form.addRow("Capa:", self.cb_capa)
        layout.addLayout(form)

        self.salida = QPlainTextEdit()
        self.salida.setReadOnly(True)
        self.salida.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.salida.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.salida.setMinimumHeight(280)
        self.salida.setPlaceholderText(
            "Probá primero: muestra cuántas OS se actualizarían y cuántas son nuevas, "
            "sin modificar la base."
        )
        layout.addWidget(self.salida, 1)

        hbox = QHBoxLayout()
        btn_probar = QPushButton("Probar (no modifica la base)")
        btn_probar.setDefault(True)
        btn_probar.clicked.connect(self._probar)
        btn_importar = QPushButton("Importar…")
        btn_importar.setMinimumHeight(30)
        btn_importar.setStyleSheet(ESTILO_PRINCIPAL)
        btn_importar.clicked.connect(self._importar)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self.reject)
        hbox.addWidget(btn_probar)
        hbox.addStretch()
        hbox.addWidget(btn_cerrar)
        hbox.addWidget(btn_importar)
        layout.addLayout(hbox)

    def _elegir_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir GeoPackage de campo", "", "GeoPackage (*.gpkg)"
        )
        if not ruta:
            return
        capas = importar.capas_gpkg(ruta)
        if not capas:
            QMessageBox.warning(self, "GeoPackage sin capas", f"No se encontraron capas en:\n{ruta}")
            return
        self.ruta = ruta
        self.lbl_archivo.setText(ruta)
        self.lbl_archivo.setStyleSheet("color:green; font-weight:bold;")
        self.cb_capa.clear()
        self.cb_capa.addItems(capas)
        self.cb_capa.setCurrentText(importar.capa_sugerida(capas))
        self.salida.clear()

    def _listo(self):
        iniciales = self.f_iniciales.text().strip()
        try:
            conexion.nombre_staging(iniciales)
        except ValueError as e:
            QMessageBox.warning(self, "Faltan las iniciales", str(e))
            self.f_iniciales.setFocus()
            return False
        if not self.ruta or not self.cb_capa.currentText():
            QMessageBox.warning(self, "Falta el archivo", "Elegí el GeoPackage que volvió de campo.")
            return False
        conexion.guardar_iniciales(iniciales)
        return True

    def _importacion(self):
        return importar.Importacion(self.ruta, self.cb_capa.currentText(), self.f_iniciales.text().strip())

    def _probar(self):
        if not self._listo():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            with self._importacion() as imp:
                analisis = imp.analizar()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.salida.setPlainText(f"✗ {e}")
            return
        QApplication.restoreOverrideCursor()
        self.salida.setPlainText("MODO PRUEBA — la base no se modificó.\n\n" + analisis.texto())

    def _importar(self):
        if not self._listo():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            with self._importacion() as imp:
                analisis = imp.analizar()
                self.salida.setPlainText(analisis.texto())
                QApplication.restoreOverrideCursor()

                if analisis.con_cambios == 0 and analisis.nuevas == 0:
                    QMessageBox.information(self, "Sin cambios",
                                            "El GeoPackage no trae cambios respecto de la base.")
                    return
                respuesta = QMessageBox.question(
                    self, "Confirmar importación",
                    f"Se van a actualizar {analisis.con_cambios} OS existentes "
                    f"(solo columnas editables) e insertar {analisis.nuevas} OS nuevas "
                    f"en {config.ESQUEMA}.{config.TABLA}.\n\n¿Continuar?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if respuesta != QMessageBox.Yes:
                    return

                QApplication.setOverrideCursor(Qt.WaitCursor)
                insertadas, actualizadas = imp.aplicar()
        except Exception as e:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            # El UPSERT es una sola sentencia: si falló, no quedó nada a medias.
            self.salida.appendPlainText(f"\n✗ {e}\n\nNo se aplicó ningún cambio a la tabla.")
            QMessageBox.critical(self, "No se pudo importar", str(e))
            return
        finally:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        resumen = f"✓ {insertadas} OS nuevas insertadas, {actualizadas} OS actualizadas."
        self.salida.appendPlainText("\n" + resumen)
        QMessageBox.information(self, "Importación terminada", resumen)
