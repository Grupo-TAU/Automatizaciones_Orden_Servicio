from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QPlainTextEdit, QPushButton, QLabel,
    QFileDialog, QMessageBox, QApplication,
)

from . import exportar
from .dialogo_conexion import ESTILO_PRINCIPAL

SIN_ETAPA = "(cualquier etapa)"


class DialogoExportar(QDialog):
    """Arma el GeoPackage para campo filtrando por N° de OS, por etapa o ambos (AND)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exportar paquete de campo")
        self.setMinimumWidth(520)
        self._build_ui()
        self._cargar_etapas()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        self.f_numeros = QPlainTextEdit()
        self.f_numeros.setPlaceholderText(
            "Opcional. Pegá los N° de OS separados por coma o uno por línea."
        )
        self.f_numeros.setMaximumHeight(110)
        self.cb_etapa = QComboBox()
        form.addRow("N° de OS:", self.f_numeros)
        form.addRow("Etapa:", self.cb_etapa)
        layout.addLayout(form)

        nota = QLabel("Si se completan los dos filtros se exportan las OS que cumplen ambos.")
        nota.setStyleSheet("color:#777;")
        layout.addWidget(nota)

        self.lbl_resultado = QLabel("")
        self.lbl_resultado.setWordWrap(True)
        self.lbl_resultado.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lbl_resultado)

        hbox = QHBoxLayout()
        btn_previa = QPushButton("Contar")
        btn_previa.clicked.connect(self._previsualizar)
        btn_exportar = QPushButton("Exportar a GeoPackage…")
        btn_exportar.setDefault(True)
        btn_exportar.setMinimumHeight(30)
        btn_exportar.setStyleSheet(ESTILO_PRINCIPAL)
        btn_exportar.clicked.connect(self._exportar)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self.reject)
        hbox.addWidget(btn_previa)
        hbox.addStretch()
        hbox.addWidget(btn_cerrar)
        hbox.addWidget(btn_exportar)
        layout.addLayout(hbox)

    def _cargar_etapas(self):
        self.cb_etapa.addItem(SIN_ETAPA)
        try:
            self.cb_etapa.addItems(exportar.etapas())
        except Exception as e:
            self._mostrar(f"✗ No se pudieron leer las etapas de la base: {e}", error=True)
        indice = self.cb_etapa.findText("Pendiente")
        if indice >= 0:
            self.cb_etapa.setCurrentIndex(indice)

    def _filtros(self):
        numeros = exportar.parsear_numeros(self.f_numeros.toPlainText())
        etapa = self.cb_etapa.currentText()
        return numeros, ("" if etapa == SIN_ETAPA else etapa)

    def _mostrar(self, texto, error=False):
        self.lbl_resultado.setText(texto)
        self.lbl_resultado.setStyleSheet("color:#b00020;" if error else "color:#325423;font-weight:bold;")

    def _previsualizar(self):
        numeros, etapa = self._filtros()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            total, no_encontrados = exportar.previsualizar(numeros, etapa)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self._mostrar(f"✗ {e}", error=True)
            return None
        QApplication.restoreOverrideCursor()

        texto = f"{total} inspección(es) cumplen el filtro."
        if no_encontrados:
            texto += f"\n⚠ N° de OS que no existen en la base: {', '.join(no_encontrados)}"
        self._mostrar(texto, error=total == 0)
        return total

    def _exportar(self):
        total = self._previsualizar()
        if not total:
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar GeoPackage para campo", "", "GeoPackage (*.gpkg)"
        )
        if not ruta:
            return
        if not ruta.lower().endswith(".gpkg"):
            ruta += ".gpkg"

        numeros, etapa = self._filtros()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            cantidad = exportar.exportar(ruta, numeros, etapa)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "No se pudo exportar", str(e))
            return
        QApplication.restoreOverrideCursor()

        QMessageBox.information(
            self, "Paquete de campo",
            f"✓ {cantidad} inspección(es) exportada(s) a:\n{ruta}\n\n"
            "Siguiente paso: empaquetarlo con QFieldSync y copiarlo al dispositivo.",
        )
