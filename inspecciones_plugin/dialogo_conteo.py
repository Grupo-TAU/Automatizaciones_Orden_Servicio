from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QCheckBox, QPushButton, QPlainTextEdit,
    QFileDialog, QMessageBox, QApplication,
)

from . import sacar_numeros


class DialogoConteo(QDialog):
    """Muestra la matriz de OS por Etapa (filas) y Contrato (columnas).

    Dos fuentes, las mismas cuentas: la capa cargada en el proyecto o una
    planilla bajada del sistema. Sirven para contrastarlas a mano cuando los
    numeros no cierran.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Números de inspecciones")
        self.setMinimumWidth(620)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        self.f_capa = QLineEdit(sacar_numeros.CAPA_QGIS)
        self.f_expresion = QLineEdit()
        self.f_expresion.setPlaceholderText("filtro opcional de QGIS, ej: Restringir IS NULL")
        form.addRow("Capa:", self.f_capa)
        form.addRow("Filtro:", self.f_expresion)
        layout.addLayout(form)

        self.chk_detalle = QCheckBox("Mostrar los valores crudos (para ver qué cayó en «Otros»)")
        layout.addWidget(self.chk_detalle)

        h_fuentes = QHBoxLayout()
        btn_capa = QPushButton("Contar la capa")
        btn_capa.setDefault(True)
        btn_capa.setMinimumHeight(30)
        btn_capa.setStyleSheet(
            "QPushButton{background:#325423;color:white;font-weight:bold;"
            "border-radius:3px;padding:0 14px;}"
            "QPushButton:hover{background:#3e6a2c;}"
        )
        btn_capa.clicked.connect(self._contar_capa)
        btn_planilla = QPushButton("Contar una planilla…")
        btn_planilla.clicked.connect(self._contar_planilla)
        h_fuentes.addWidget(btn_capa)
        h_fuentes.addWidget(btn_planilla)
        h_fuentes.addStretch()
        layout.addLayout(h_fuentes)

        self.salida = QPlainTextEdit()
        self.salida.setReadOnly(True)
        # Fuente monoespaciada: la matriz se alinea con espacios.
        self.salida.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.salida.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.salida.setMinimumHeight(280)
        self.salida.setPlaceholderText("Elegí una fuente para contar.")
        layout.addWidget(self.salida, 1)

        h_cierre = QHBoxLayout()
        self.btn_copiar = QPushButton("Copiar al portapapeles")
        self.btn_copiar.setEnabled(False)
        self.btn_copiar.clicked.connect(self._copiar)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self.reject)
        h_cierre.addWidget(self.btn_copiar)
        h_cierre.addStretch()
        h_cierre.addWidget(btn_cerrar)
        layout.addLayout(h_cierre)

    def _contar_capa(self):
        capa = self.f_capa.text().strip() or sacar_numeros.CAPA_QGIS
        expresion = self.f_expresion.text().strip() or None
        titulo = f"Capa '{capa}'" + (f" filtrada por {expresion!r}" if expresion else "")
        self._contar(lambda: sacar_numeros.contar_capa_qgis(capa, expresion=expresion), titulo)

    def _contar_planilla(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir planilla", "", "Planillas (*.xlsx *.xlsm *.csv);;Todos los archivos (*)"
        )
        if not ruta:
            return
        nombre = ruta.replace("\\", "/").rsplit("/", 1)[-1]
        self._contar(lambda: sacar_numeros.contar_planilla(ruta), f"Planilla: {nombre}")

    def _contar(self, obtener_resultado, titulo):
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                resultado = obtener_resultado()
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as e:
            QMessageBox.critical(self, "No se pudo contar", str(e))
            return

        texto = sacar_numeros.formatear_matriz(resultado, titulo)
        if self.chk_detalle.isChecked():
            texto += "\n\n" + sacar_numeros.formatear_detalle(resultado)
        self.salida.setPlainText(texto)
        self.btn_copiar.setEnabled(True)

    def _copiar(self):
        QApplication.clipboard().setText(self.salida.toPlainText())
