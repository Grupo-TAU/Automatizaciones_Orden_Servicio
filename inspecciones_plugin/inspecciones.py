import os

from PyQt5.QtWidgets import QAction
from PyQt5.QtGui import QIcon


class InspeccionesPlugin:
    """Punto de entrada del plugin: alta/baja de los botones en la GUI de QGIS."""

    MENU = "&Grupo TAU"

    def __init__(self, iface):
        self.iface = iface
        self.acciones = []
        # Referencias persistentes: sin esto el GC destruye los diálogos no-modales.
        self.dlg = None
        self.dlg_copiar_imagenes = None
        self.dlg_conteo = None
        self.dlg_exportar_campo = None
        self.dlg_importar_campo = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))

        # Solo "Registrar OS" va a la barra de herramientas: es la acción de uso
        # diario, las otras dos se usan de a ratos y viven solo en el menú.
        self._agregar_accion(icon, "Registrar OS", self.run, en_barra=True)
        self._agregar_accion(icon, "Copiar imágenes de OS", self.run_copiar_imagenes)
        self._agregar_accion(icon, "Números de inspecciones", self.run_conteo, en_barra=True)
        # Ida y vuelta con QField: solo menú.
        self._agregar_accion(icon, "Exportar paquete de campo…", self.run_exportar_campo)
        self._agregar_accion(icon, "Importar cambios de campo…", self.run_importar_campo)
        self._agregar_accion(icon, "Configurar conexión PostGIS…", self.run_configurar_conexion)

    def _agregar_accion(self, icon, titulo, callback, en_barra=False):
        accion = QAction(icon, titulo, self.iface.mainWindow())
        accion.triggered.connect(callback)
        if en_barra:
            self.iface.addToolBarIcon(accion)
        self.iface.addPluginToMenu(self.MENU, accion)
        self.acciones.append((accion, en_barra))
        return accion

    def unload(self):
        for accion, en_barra in self.acciones:
            self.iface.removePluginMenu(self.MENU, accion)
            if en_barra:
                self.iface.removeToolBarIcon(accion)
        self.acciones = []

    def run(self):
        from .dialogo_registro_os import DialogoRegistroOS
        self.dlg = DialogoRegistroOS()
        self.dlg.show()  # no-modal: permite clic en el mapa con el diálogo abierto

    def run_copiar_imagenes(self):
        from .dialogo_copiar_imagenes import DialogoCopiarImagenes
        self.dlg_copiar_imagenes = DialogoCopiarImagenes()
        self.dlg_copiar_imagenes.show()

    def run_conteo(self):
        from .dialogo_conteo import DialogoConteo
        self.dlg_conteo = DialogoConteo()
        self.dlg_conteo.show()

    def run_exportar_campo(self):
        from .campo.dialogo_conexion import asegurar_conexion
        from .campo.dialogo_exportar import DialogoExportar
        if not asegurar_conexion(self.iface.mainWindow()):
            return
        self.dlg_exportar_campo = DialogoExportar()
        self.dlg_exportar_campo.show()

    def run_importar_campo(self):
        from .campo.dialogo_conexion import asegurar_conexion
        from .campo.dialogo_importar import DialogoImportar
        if not asegurar_conexion(self.iface.mainWindow()):
            return
        self.dlg_importar_campo = DialogoImportar()
        self.dlg_importar_campo.show()

    def run_configurar_conexion(self):
        from .campo.dialogo_conexion import DialogoConexion
        DialogoConexion(self.iface.mainWindow()).exec_()
