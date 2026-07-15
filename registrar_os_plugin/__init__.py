"""
Registrar OS - Plugin QGIS
Grupo TAU - DICA
"""


def classFactory(iface):
    from .registrar_os import RegistrarOSPlugin
    return RegistrarOSPlugin(iface)
