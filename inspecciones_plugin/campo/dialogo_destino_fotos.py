from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QRadioButton,
    QLineEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QApplication,
)

from . import config, conexion, copiar_fotos
from .dialogo_conexion import ESTILO_PRINCIPAL


class DialogoDestinoFotos(QDialog):
    """Cómo llegar a /srv/backups/fotos/inspecciones_os en el servidor.

    La conexión a PostgreSQL no sirve para esto: solo lee y escribe en la base,
    no crea archivos en el disco del servidor.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Destino de las fotos")
        self.setMinimumWidth(560)
        self._build_ui()
        self._cargar()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "Las fotos se copian al servidor respetando ruta_relativa "
            "(DCIM/FOTOS_OS/<N°_OS>/…). Elegí cómo accede esta PC a la carpeta del servidor."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.rb_carpeta = QRadioButton("Carpeta compartida o unidad de red")
        self.rb_carpeta.toggled.connect(self._actualizar_habilitados)
        layout.addWidget(self.rb_carpeta)
        self.grupo_carpeta = QGroupBox()
        h_carpeta = QHBoxLayout(self.grupo_carpeta)
        self.f_carpeta = QLineEdit()
        self.f_carpeta.setPlaceholderText(r"ej: \\servidor\backups\fotos\inspecciones_os  o  Z:\fotos\inspecciones_os")
        btn_carpeta = QPushButton("…")
        btn_carpeta.setMaximumWidth(30)
        btn_carpeta.clicked.connect(self._elegir_carpeta)
        h_carpeta.addWidget(self.f_carpeta, 1)
        h_carpeta.addWidget(btn_carpeta)
        layout.addWidget(self.grupo_carpeta)

        self.rb_ssh = QRadioButton("SSH (con clave, sin contraseña)")
        layout.addWidget(self.rb_ssh)
        self.grupo_ssh = QGroupBox()
        form = QFormLayout(self.grupo_ssh)
        self.f_host = QLineEdit()
        self.f_usuario = QLineEdit()
        self.f_puerto = QLineEdit("22")
        self.f_ruta = QLineEdit(config.RUTA_REMOTA_FOTOS)
        h_clave = QHBoxLayout()
        self.f_clave = QLineEdit()
        self.f_clave.setPlaceholderText("opcional: por defecto usa la de ~/.ssh")
        btn_clave = QPushButton("…")
        btn_clave.setMaximumWidth(30)
        btn_clave.clicked.connect(self._elegir_clave)
        h_clave.addWidget(self.f_clave, 1)
        h_clave.addWidget(btn_clave)
        form.addRow("Servidor:", self.f_host)
        form.addRow("Usuario:", self.f_usuario)
        form.addRow("Puerto:", self.f_puerto)
        form.addRow("Carpeta remota:", self.f_ruta)
        form.addRow("Clave privada:", h_clave)
        layout.addWidget(self.grupo_ssh)

        self.lbl_resultado = QLabel("")
        self.lbl_resultado.setWordWrap(True)
        self.lbl_resultado.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lbl_resultado)

        h_botones = QHBoxLayout()
        btn_guardar = QPushButton("Guardar y probar")
        btn_guardar.setDefault(True)
        btn_guardar.setMinimumHeight(30)
        btn_guardar.setStyleSheet(ESTILO_PRINCIPAL)
        btn_guardar.clicked.connect(self._guardar)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self._cerrar)
        h_botones.addWidget(btn_guardar)
        h_botones.addStretch()
        h_botones.addWidget(btn_cerrar)
        layout.addLayout(h_botones)

    def _cargar(self):
        d = copiar_fotos.leer_destino()
        self.f_carpeta.setText(d["carpeta"])
        # Por defecto, el mismo servidor que la base.
        self.f_host.setText(d["host"] or conexion.leer_config()["host"])
        self.f_usuario.setText(d["usuario"])
        self.f_puerto.setText(d["puerto"])
        self.f_ruta.setText(d["ruta_remota"])
        self.f_clave.setText(d["clave_privada"])
        self.rb_ssh.setChecked(d["modo"] == config.DESTINO_SSH)
        self.rb_carpeta.setChecked(d["modo"] != config.DESTINO_SSH)
        self._actualizar_habilitados()

    def _actualizar_habilitados(self):
        self.grupo_carpeta.setEnabled(self.rb_carpeta.isChecked())
        self.grupo_ssh.setEnabled(self.rb_ssh.isChecked())

    def _elegir_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de fotos en el servidor", self.f_carpeta.text())
        if carpeta:
            self.f_carpeta.setText(carpeta)

    def _elegir_clave(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Clave privada SSH", self.f_clave.text())
        if ruta:
            self.f_clave.setText(ruta)

    def _guardar(self):
        if self.rb_carpeta.isChecked():
            if not self.f_carpeta.text().strip():
                QMessageBox.warning(self, "Falta la carpeta", "Indicá la carpeta destino.")
                return
            copiar_fotos.guardar_destino(modo=config.DESTINO_CARPETA, carpeta=self.f_carpeta.text().strip())
        else:
            if not (self.f_host.text().strip() and self.f_usuario.text().strip() and self.f_ruta.text().strip()):
                QMessageBox.warning(self, "Faltan datos", "Completá servidor, usuario y carpeta remota.")
                return
            copiar_fotos.guardar_destino(
                modo=config.DESTINO_SSH, host=self.f_host.text().strip(),
                usuario=self.f_usuario.text().strip(), puerto=self.f_puerto.text().strip() or "22",
                ruta_remota=self.f_ruta.text().strip(), clave_privada=self.f_clave.text().strip(),
            )
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            texto, error = copiar_fotos.probar_destino(), False
        except Exception as e:
            texto, error = f"✗ {e}", True
        finally:
            QApplication.restoreOverrideCursor()
        self.lbl_resultado.setText(texto)
        self.lbl_resultado.setStyleSheet("color:#b00020;" if error else "color:#325423;font-weight:bold;")

    def _cerrar(self):
        if copiar_fotos.destino_configurado():
            self.accept()
        else:
            self.reject()
