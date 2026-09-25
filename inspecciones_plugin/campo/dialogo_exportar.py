import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QCheckBox, QComboBox, QPlainTextEdit, QPushButton, QLabel,
    QFileDialog, QMessageBox, QApplication,
)
from qgis.core import QgsProject

from . import config, exportar, proyecto_campo
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

        # Tablas hijas: siempre van como capas (para cargar filas nuevas en campo);
        # las "opcional" pueden llevar además las filas existentes de esas OS.
        self.chk_hijas = {}
        for tabla, cfg in config.TABLAS_HIJAS.items():
            if cfg["exportar"] == "opcional":
                chk = QCheckBox(f"Incluir las {tabla} existentes de esas OS")
                layout.addWidget(chk)
                self.chk_hijas[tabla] = chk
        vacias = [t for t, cfg in config.TABLAS_HIJAS.items() if cfg["exportar"] == "vacia"]
        if vacias:
            nota_hijas = QLabel(f"{', '.join(vacias).capitalize()}: van vacías, en campo solo se cargan nuevas.")
            nota_hijas.setStyleSheet("color:#777;")
            layout.addWidget(nota_hijas)

        self.chk_proyecto = QCheckBox(
            "Generar también el proyecto de campo para QFieldSync (copia del proyecto abierto)"
        )
        self.chk_proyecto.setChecked(True)
        self.chk_proyecto.setToolTip(
            "Crea <nombre>_campo.qgz junto al GeoPackage, con la capa de inspecciones "
            "apuntando al GeoPackage y marcada como 'Copy' en QFieldSync."
        )
        layout.addWidget(self.chk_proyecto)

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
        incluir = [t for t, chk in self.chk_hijas.items() if chk.isChecked()]
        try:
            exportadas = exportar.exportar(ruta, numeros, etapa, incluir)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "No se pudo exportar", str(e))
            return
        QApplication.restoreOverrideCursor()

        mensaje = f"✓ GeoPackage:\n{ruta}\n"
        for capa, filas in exportadas.items():
            if filas is None:
                mensaje += f"\n  ⚠ {capa}: la tabla no existe en la base, no se exportó"
            else:
                mensaje += f"\n  {capa}: {filas} fila(s)"
        if self.chk_proyecto.isChecked():
            mensaje += "\n\n" + self._generar_proyecto(ruta)
        else:
            mensaje += "\n\nSiguiente paso: empaquetarlo con QFieldSync y copiarlo al dispositivo."
        QMessageBox.information(self, "Paquete de campo", mensaje)

    def _generar_proyecto(self, ruta_gpkg):
        """Arma el proyecto de campo y devuelve el texto para el resumen."""
        destino = proyecto_campo.ruta_proyecto_campo(ruta_gpkg)
        if os.path.exists(destino):
            respuesta = QMessageBox.question(
                self, "Proyecto de campo",
                f"Ya existe:\n{destino}\n\n¿Reemplazarlo con una copia nueva del proyecto abierto?\n\n"
                "Si elegís No, se mantiene el existente: ya apunta a este mismo GeoPackage, "
                "así que toma los datos recién exportados.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                return f"Proyecto de campo (sin cambios):\n{destino}\n\nAbrilo y empaquetalo con QFieldSync."

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            destino, restantes, sin_capa = proyecto_campo.generar(ruta_gpkg, destino)
        except Exception as e:
            return f"✗ No se pudo generar el proyecto de campo: {e}"
        finally:
            QApplication.restoreOverrideCursor()

        texto = (f"✓ Proyecto de campo:\n{destino}\n\n"
                 "Abrilo y empaquetalo con QFieldSync: las capas ya apuntan "
                 "al GeoPackage y están en 'Copy'.")
        if sin_capa:
            texto += ("\n\n⚠ El proyecto abierto no tiene capa de: " + ", ".join(sin_capa)
                      + ". Agregala desde PostGIS al proyecto de oficina, con su formulario y la "
                      "relación con inspecciones, guardá y volvé a exportar.")
        if QgsProject.instance().isDirty():
            texto += "\n\nSe usó la última versión GUARDADA del proyecto abierto."
        if restantes:
            texto += ("\n\nEstas capas siguen siendo de PostGIS (en el celular no hay base): "
                      + ", ".join(restantes)
                      + ".\nEn QFieldSync elegí 'Offline editing' si las necesitás en campo, "
                      "o 'Remove from project' si no.")
        return texto
