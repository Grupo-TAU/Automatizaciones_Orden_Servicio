"""
Inspecciones - Plugin QGIS
Grupo TAU - DICA
"""


def classFactory(iface):
    from .inspecciones import InspeccionesPlugin
    return InspeccionesPlugin(iface)
