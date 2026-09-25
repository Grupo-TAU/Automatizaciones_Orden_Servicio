import os
from contextlib import ExitStack

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QLineEdit, QPlainTextEdit, QPushButton, QLabel,
    QFileDialog, QMessageBox, QApplication,
)

from . import config, conexion, copiar_fotos, importar, importar_hijas
from .conexion import conectar
from .dialogo_conexion import ESTILO_PRINCIPAL
from .staging import capa_sugerida, capas_gpkg

NO_IMPORTAR = "(no importar)"
ESTILO_OK = "color:#325423;font-weight:bold;"
ESTILO_BLOQUEADO = "color:#999;font-style:italic;"


class DialogoImportar(QDialog):
    """Trae el GeoPackage editado en campo, en tres pasos que se habilitan en orden.

    1. Inspecciones (UPSERT). 2. Fotos y observaciones: se habilita recién
    cuando el paso 1 terminó, porque sus filas necesitan que la OS ya exista.
    3. Copia de los archivos de las fotos recién insertadas en el paso 2.

    El estado vive en el diálogo: cambiar de archivo o de capa lo reinicia.
    Repetir el paso 1 con el mismo gpkg no cambia nada en la base, así que
    cerrar y volver a empezar es seguro.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar cambios de campo")
        self.setMinimumWidth(680)
        self.ruta = ""
        self._build_ui()
        self._reiniciar()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        form = QFormLayout()
        self.f_iniciales = QLineEdit(conexion.leer_iniciales())
        self.f_iniciales.setPlaceholderText("ej: NA")
        self.f_iniciales.setMaxLength(10)
        self.f_iniciales.setToolTip(
            "Se usan para nombrar las tablas temporales (inspecciones_staging_na, "
            "fotos_staging_na…), así dos personas importando a la vez no se pisan."
        )
        form.addRow("Iniciales del operario:", self.f_iniciales)

        h_archivo = QHBoxLayout()
        btn_archivo = QPushButton("Elegir GeoPackage…")
        btn_archivo.clicked.connect(self._elegir_archivo)
        self.lbl_archivo = QLabel("Sin archivo seleccionado")
        self.lbl_archivo.setStyleSheet("color:#999; font-style:italic;")
        h_archivo.addWidget(btn_archivo)
        h_archivo.addWidget(self.lbl_archivo, 1)
        form.addRow(h_archivo)

        self.cb_capa = QComboBox()
        self.cb_capa.currentIndexChanged.connect(self._reiniciar)
        form.addRow("Capa de inspecciones:", self.cb_capa)
        self.cb_hijas = {}
        for tabla in config.TABLAS_HIJAS:
            combo = QComboBox()
            combo.currentIndexChanged.connect(self._reiniciar)
            form.addRow(f"Capa de {tabla}:", combo)
            self.cb_hijas[tabla] = combo
        layout.addLayout(form)

        # Paso 1
        self.grupo1 = QGroupBox("1. Inspecciones")
        h1 = QHBoxLayout(self.grupo1)
        btn_probar1 = QPushButton("Probar")
        btn_probar1.clicked.connect(self._probar_inspecciones)
        btn_importar1 = QPushButton("Importar inspecciones…")
        btn_importar1.setStyleSheet(ESTILO_PRINCIPAL)
        btn_importar1.setMinimumHeight(28)
        btn_importar1.clicked.connect(self._importar_inspecciones)
        self.lbl_paso1 = QLabel()
        h1.addWidget(btn_probar1)
        h1.addWidget(btn_importar1)
        h1.addWidget(self.lbl_paso1, 1)
        layout.addWidget(self.grupo1)

        # Paso 2
        self.grupo2 = QGroupBox("2. " + " y ".join(t.capitalize() for t in config.TABLAS_HIJAS))
        h2 = QHBoxLayout(self.grupo2)
        self.btn_probar2 = QPushButton("Probar")
        self.btn_probar2.clicked.connect(self._probar_hijas)
        self.btn_importar2 = QPushButton("Importar…")
        self.btn_importar2.setStyleSheet(ESTILO_PRINCIPAL)
        self.btn_importar2.setMinimumHeight(28)
        self.btn_importar2.clicked.connect(self._importar_hijas)
        self.lbl_paso2 = QLabel()
        h2.addWidget(self.btn_probar2)
        h2.addWidget(self.btn_importar2)
        h2.addWidget(self.lbl_paso2, 1)
        layout.addWidget(self.grupo2)

        # Paso 3
        self.grupo3 = QGroupBox("3. Copiar archivos de fotos al servidor")
        h3 = QHBoxLayout(self.grupo3)
        btn_destino = QPushButton("Destino…")
        btn_destino.clicked.connect(self._configurar_destino)
        self.btn_copiar = QPushButton("Copiar fotos")
        self.btn_copiar.setStyleSheet(ESTILO_PRINCIPAL)
        self.btn_copiar.setMinimumHeight(28)
        self.btn_copiar.clicked.connect(self._copiar_fotos)
        self.lbl_paso3 = QLabel()
        h3.addWidget(btn_destino)
        h3.addWidget(self.btn_copiar)
        h3.addWidget(self.lbl_paso3, 1)
        layout.addWidget(self.grupo3)

        self.salida = QPlainTextEdit()
        self.salida.setReadOnly(True)
        self.salida.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.salida.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.salida.setMinimumHeight(260)
        self.salida.setPlaceholderText(
            "Probá primero cada paso: muestra qué se haría, sin modificar la base."
        )
        layout.addWidget(self.salida, 1)

        h_cierre = QHBoxLayout()
        h_cierre.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self.reject)
        h_cierre.addWidget(btn_cerrar)
        layout.addLayout(h_cierre)

    # ── Estado del ciclo ────────────────────────────────────────────────────
    def _reiniciar(self):
        self.paso1_ok = False
        self.paso2_ok = False
        self.fotos_nuevas = []          # [(fid, ruta_relativa)] insertadas en el paso 2
        self._actualizar_pasos()

    def _actualizar_pasos(self):
        hay_hijas = any(c.currentText() not in ("", NO_IMPORTAR) for c in self.cb_hijas.values())
        self.grupo2.setEnabled(self.paso1_ok and hay_hijas)
        self.grupo3.setEnabled(self.paso2_ok and bool(self.fotos_nuevas))

        self.lbl_paso1.setText("✓ Importadas" if self.paso1_ok else "")
        self.lbl_paso1.setStyleSheet(ESTILO_OK)
        if not self.paso1_ok:
            self._estado(self.lbl_paso2, "Se habilita al terminar el paso 1", bloqueado=True)
        elif not hay_hijas:
            self._estado(self.lbl_paso2, "No hay capas elegidas", bloqueado=True)
        elif self.paso2_ok:
            self._estado(self.lbl_paso2, "✓ Importadas")
        else:
            self._estado(self.lbl_paso2, "")

        if not self.paso2_ok:
            self._estado(self.lbl_paso3, "Se habilita al terminar el paso 2", bloqueado=True)
        elif not self.fotos_nuevas:
            self._estado(self.lbl_paso3, "No hubo fotos nuevas", bloqueado=True)
        else:
            self._estado(self.lbl_paso3, f"{len(self.fotos_nuevas)} foto(s) → {copiar_fotos.describir_destino()}")

    @staticmethod
    def _estado(etiqueta, texto, bloqueado=False):
        etiqueta.setText(texto)
        etiqueta.setStyleSheet(ESTILO_BLOQUEADO if bloqueado else ESTILO_OK)

    # ── Archivo ─────────────────────────────────────────────────────────────
    def _elegir_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir GeoPackage de campo", "", "GeoPackage (*.gpkg)"
        )
        if not ruta:
            return
        capas = capas_gpkg(ruta)
        if not capas:
            QMessageBox.warning(self, "GeoPackage sin capas", f"No se encontraron capas en:\n{ruta}")
            return
        self.ruta = ruta
        self.lbl_archivo.setText(ruta)
        self.lbl_archivo.setStyleSheet("color:green; font-weight:bold;")

        self.cb_capa.blockSignals(True)
        self.cb_capa.clear()
        self.cb_capa.addItems(capas)
        self.cb_capa.setCurrentText(capa_sugerida(capas, config.CAPA_GPKG) or capas[0])
        self.cb_capa.blockSignals(False)
        for tabla, combo in self.cb_hijas.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([NO_IMPORTAR] + capas)
            combo.setCurrentText(capa_sugerida(capas, config.TABLAS_HIJAS[tabla]["capa_gpkg"]) or NO_IMPORTAR)
            combo.blockSignals(False)
        self.salida.clear()
        self._reiniciar()

    def _iniciales_ok(self):
        iniciales = self.f_iniciales.text().strip()
        try:
            conexion.nombre_staging(iniciales)
        except ValueError as e:
            QMessageBox.warning(self, "Faltan las iniciales", str(e))
            self.f_iniciales.setFocus()
            return None
        if not self.ruta:
            QMessageBox.warning(self, "Falta el archivo", "Elegí el GeoPackage que volvió de campo.")
            return None
        conexion.guardar_iniciales(iniciales)
        return iniciales

    def _hijas_elegidas(self):
        return [(t, c.currentText()) for t, c in self.cb_hijas.items()
                if c.currentText() not in ("", NO_IMPORTAR)]

    # ── Paso 1: inspecciones ────────────────────────────────────────────────
    def _importacion_inspecciones(self, iniciales):
        return importar.Importacion(self.ruta, self.cb_capa.currentText(), iniciales)

    def _probar_inspecciones(self):
        iniciales = self._iniciales_ok()
        if not iniciales:
            return
        try:
            with _Espera():
                with self._importacion_inspecciones(iniciales) as imp:
                    analisis = imp.analizar()
        except Exception as e:
            self.salida.setPlainText(f"✗ {e}")
            return
        self.salida.setPlainText("MODO PRUEBA — la base no se modificó.\n\n" + analisis.texto())

    def _importar_inspecciones(self):
        iniciales = self._iniciales_ok()
        if not iniciales:
            return
        try:
            with ExitStack() as pila:
                pila.enter_context(_Espera())
                imp = pila.enter_context(self._importacion_inspecciones(iniciales))
                analisis = imp.analizar()
                self.salida.setPlainText(analisis.texto())
                QApplication.restoreOverrideCursor()

                if analisis.con_cambios == 0 and analisis.nuevas == 0:
                    resumen = "✓ Inspecciones: sin cambios respecto de la base."
                else:
                    respuesta = QMessageBox.question(
                        self, "Confirmar importación de inspecciones",
                        f"Se van a actualizar {analisis.con_cambios} OS existentes "
                        f"(solo columnas editables) e insertar {analisis.nuevas} OS nuevas "
                        f"en {config.ESQUEMA}.{config.TABLA}.\n\n¿Continuar?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                    )
                    if respuesta != QMessageBox.Yes:
                        return
                    QApplication.setOverrideCursor(Qt.WaitCursor)
                    insertadas, actualizadas = imp.aplicar()
                    resumen = f"✓ Inspecciones: {insertadas} OS nuevas insertadas, {actualizadas} actualizadas."
        except Exception as e:
            # El UPSERT es una sola sentencia: si falló, no quedó nada a medias.
            self.salida.appendPlainText(f"\n✗ {e}\n\nNo se aplicó ningún cambio a la tabla.")
            QMessageBox.critical(self, "No se pudo importar", str(e))
            return

        self.salida.appendPlainText("\n" + resumen)
        self.paso1_ok = True
        self._actualizar_pasos()
        siguiente = "\n\nSeguí con el paso 2." if self._hijas_elegidas() else ""
        QMessageBox.information(self, "Paso 1 terminado", resumen + siguiente)

    # ── Paso 2: fotos y observaciones ───────────────────────────────────────
    def _abrir_hijas(self, pila, iniciales):
        conexion_bd = conectar()
        return [pila.enter_context(importar_hijas.ImportacionHija(
                    self.ruta, capa, tabla, iniciales, conexion_bd))
                for tabla, capa in self._hijas_elegidas()]

    def _probar_hijas(self):
        iniciales = self._iniciales_ok()
        if not iniciales or not self.paso1_ok:
            return
        try:
            with ExitStack() as pila:
                pila.enter_context(_Espera())
                analisis = [imp.analizar() for imp in self._abrir_hijas(pila, iniciales)]
        except Exception as e:
            self.salida.setPlainText(f"✗ {e}")
            return
        self.salida.setPlainText("MODO PRUEBA — la base no se modificó.\n\n"
                                 + "\n\n".join(a.texto() for a in analisis))

    def _importar_hijas(self):
        iniciales = self._iniciales_ok()
        if not iniciales or not self.paso1_ok:
            return
        resultados, errores = [], []
        try:
            with ExitStack() as pila:
                pila.enter_context(_Espera())
                importaciones = self._abrir_hijas(pila, iniciales)
                analisis = [imp.analizar() for imp in importaciones]
                self.salida.setPlainText("\n\n".join(a.texto() for a in analisis))
                QApplication.restoreOverrideCursor()

                detalle = "\n".join(
                    f"  {a.tabla}: {a.a_insertar} nuevas"
                    + (f", {a.con_cambios} a actualizar" if a.con_cambios else "")
                    + (f", {a.filas_huerfanas} huérfanas quedan pendientes" if a.huerfanas else "")
                    for a in analisis
                )
                respuesta = QMessageBox.question(
                    self, "Confirmar importación",
                    f"Se va a importar:\n{detalle}\n\n¿Continuar?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                QApplication.setOverrideCursor(Qt.WaitCursor)
                if respuesta != QMessageBox.Yes:
                    return
                # Cada tabla es una sentencia atómica; si una falla, las demás siguen.
                for imp in importaciones:
                    try:
                        resultados.append(imp.aplicar())
                    except Exception as e:
                        errores.append(f"✗ {imp.tabla}: {e} (no se aplicó ningún cambio a esa tabla)")
        except Exception as e:
            self.salida.appendPlainText(f"\n✗ {e}")
            QMessageBox.critical(self, "No se pudo importar", str(e))
            return

        for r in resultados:
            if r.tabla == config.TABLA_FOTOS:
                pk = r.pk[0] if r.pk else ""
                self.fotos_nuevas = [(f.get(pk, "?"), f.get(config.COLUMNA_RUTA_FOTO, ""))
                                     for f in r.insertadas]
        resumen = "\n".join([r.texto() for r in resultados] + errores)
        self.salida.appendPlainText("\n" + resumen)
        self.paso2_ok = True
        self._actualizar_pasos()
        if self.fotos_nuevas:
            resumen += "\n\nSeguí con el paso 3 para copiar los archivos de las fotos."
        mostrar = QMessageBox.warning if errores else QMessageBox.information
        mostrar(self, "Paso 2 terminado", resumen)

    # ── Paso 3: archivos ────────────────────────────────────────────────────
    def _configurar_destino(self):
        from .dialogo_destino_fotos import DialogoDestinoFotos
        DialogoDestinoFotos(self).exec_()
        self._actualizar_pasos()

    def _copiar_fotos(self):
        if not copiar_fotos.destino_configurado():
            self._configurar_destino()
            if not copiar_fotos.destino_configurado():
                return
        try:
            with _Espera():
                resultado = copiar_fotos.copiar(self.fotos_nuevas, os.path.dirname(self.ruta))
        except Exception as e:
            QMessageBox.critical(self, "No se pudieron copiar las fotos", str(e))
            return
        self.salida.setPlainText(resultado.texto())
        problemas = len(resultado.fallidas) + len(resultado.rutas_invalidas)
        mostrar = QMessageBox.warning if problemas else QMessageBox.information
        mostrar(self, "Paso 3 terminado",
                f"{len(resultado.copiadas)} copiada(s), {len(resultado.ya_existian)} ya estaban, "
                f"{problemas} con problemas (detalle en la ventana)."
                + ("\n\nPodés corregir y volver a copiar: las que ya están no se duplican." if problemas else ""))


class _Espera:
    """Cursor de espera que se restaura siempre, aunque se lo haya restaurado a mano en el medio."""

    def __enter__(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        return self

    def __exit__(self, *exc):
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        return False
