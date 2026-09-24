from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QRadioButton,
    QComboBox, QLineEdit, QPushButton, QPlainTextEdit, QLabel,
    QMessageBox, QApplication,
)

from . import conexion, config, esquema

ESTILO_PRINCIPAL = (
    "QPushButton{background:#325423;color:white;font-weight:bold;"
    "border-radius:3px;padding:0 14px;}"
    "QPushButton:hover{background:#3e6a2c;}"
)


class DialogoConexion(QDialog):
    """Configura la conexión a PostGIS: una del Navegador de QGIS o una propia.

    En el modo propio la contraseña se guarda cifrada en el gestor de
    autenticación de QGIS (pide la contraseña maestra), nunca en settings.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar conexión PostGIS")
        self.setMinimumWidth(560)
        self._build_ui()
        self._cargar()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.rb_existente = QRadioButton("Usar una conexión PostgreSQL del Navegador de QGIS")
        self.cb_conexiones = QComboBox()
        self.rb_propia = QRadioButton("Configurar una conexión propia del plugin")
        self.rb_existente.toggled.connect(self._actualizar_habilitados)

        layout.addWidget(self.rb_existente)
        h_exist = QHBoxLayout()
        h_exist.addSpacing(20)
        h_exist.addWidget(self.cb_conexiones, 1)
        layout.addLayout(h_exist)
        nota = QLabel("Se usa tal cual está guardada en QGIS (con su usuario y contraseña).")
        nota.setStyleSheet("color:#777; margin-left:20px;")
        layout.addWidget(nota)

        layout.addWidget(self.rb_propia)
        self.grupo_propia = QGroupBox()
        form = QFormLayout(self.grupo_propia)
        self.f_host = QLineEdit()
        self.f_puerto = QLineEdit("5432")
        self.f_base = QLineEdit()
        self.cb_ssl = QComboBox()
        self.cb_ssl.addItems(["prefer", "disable", "allow", "require", "verify-ca", "verify-full"])
        self.f_usuario = QLineEdit()
        self.f_password = QLineEdit()
        self.f_password.setEchoMode(QLineEdit.Password)
        form.addRow("Host:", self.f_host)
        form.addRow("Puerto:", self.f_puerto)
        form.addRow("Base de datos:", self.f_base)
        form.addRow("SSL:", self.cb_ssl)
        form.addRow("Usuario:", self.f_usuario)
        form.addRow("Contraseña:", self.f_password)
        layout.addWidget(self.grupo_propia)

        self.salida = QPlainTextEdit()
        self.salida.setReadOnly(True)
        self.salida.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.salida.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.salida.setMinimumHeight(160)
        self.salida.setPlaceholderText("Guardá y probá la conexión.")
        layout.addWidget(self.salida, 1)

        h_botones = QHBoxLayout()
        btn_guardar = QPushButton("Guardar y probar")
        btn_guardar.setDefault(True)
        btn_guardar.setMinimumHeight(30)
        btn_guardar.setStyleSheet(ESTILO_PRINCIPAL)
        btn_guardar.clicked.connect(self._guardar)
        btn_columnas = QPushButton("Ver columnas de la tabla")
        btn_columnas.clicked.connect(self._ver_columnas)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self._cerrar)
        h_botones.addWidget(btn_guardar)
        h_botones.addWidget(btn_columnas)
        h_botones.addStretch()
        h_botones.addWidget(btn_cerrar)
        layout.addLayout(h_botones)

    def _cargar(self):
        try:
            nombres = conexion.conexiones_existentes()
        except Exception:
            nombres = []
        self.cb_conexiones.addItems(nombres)

        cfg = conexion.leer_config()
        if cfg["conexion"] in nombres:
            self.cb_conexiones.setCurrentText(cfg["conexion"])
        self.f_host.setText(cfg["host"])
        self.f_puerto.setText(cfg["puerto"])
        self.f_base.setText(cfg["base"])
        self.cb_ssl.setCurrentText(cfg["sslmode"])
        if cfg["authcfg"]:
            self.f_password.setPlaceholderText("(guardada — dejar vacío para no cambiarla)")

        usar_existente = cfg["modo"] == config.MODO_EXISTENTE or (not cfg["modo"] and nombres)
        self.rb_existente.setChecked(bool(usar_existente))
        self.rb_propia.setChecked(not usar_existente)
        self.rb_existente.setEnabled(bool(nombres))
        self._actualizar_habilitados()

    def _actualizar_habilitados(self):
        self.cb_conexiones.setEnabled(self.rb_existente.isChecked())
        self.grupo_propia.setEnabled(self.rb_propia.isChecked())
        # Pedir el usuario al gestor dispara la contraseña maestra: solo si hace falta.
        if self.rb_propia.isChecked() and not self.f_usuario.text() and conexion.leer_config()["authcfg"]:
            self.f_usuario.setText(conexion.usuario_guardado())

    def _guardar(self):
        try:
            if self.rb_existente.isChecked():
                nombre = self.cb_conexiones.currentText()
                if not nombre:
                    raise ValueError("Elegí una conexión.")
                conexion.guardar_existente(nombre)
            else:
                host, base = self.f_host.text().strip(), self.f_base.text().strip()
                usuario = self.f_usuario.text().strip()
                if not (host and base and usuario):
                    raise ValueError("Completá host, base de datos y usuario.")
                conexion.guardar_propia(
                    host, self.f_puerto.text().strip() or "5432", base,
                    self.cb_ssl.currentText(), usuario, self.f_password.text(),
                )
                self.f_password.clear()
                self.f_password.setPlaceholderText("(guardada — dejar vacío para no cambiarla)")
        except Exception as e:
            QMessageBox.warning(self, "No se pudo guardar", str(e))
            return
        self._ejecutar(conexion.probar)

    def _ver_columnas(self):
        self._ejecutar(lambda: esquema.describir(esquema.leer(conexion.conectar())))

    def _ejecutar(self, funcion):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            texto = funcion()
        except Exception as e:
            texto = f"✗ {e}"
        finally:
            QApplication.restoreOverrideCursor()
        self.salida.setPlainText(texto)

    def _cerrar(self):
        if conexion.esta_configurada():
            self.accept()
        else:
            self.reject()


def asegurar_conexion(parent=None):
    """Abre el diálogo si la conexión todavía no está configurada. True si quedó configurada."""
    if conexion.esta_configurada():
        return True
    DialogoConexion(parent).exec_()
    return conexion.esta_configurada()
