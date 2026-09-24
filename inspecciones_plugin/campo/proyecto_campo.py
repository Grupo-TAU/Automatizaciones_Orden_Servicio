"""
Genera el proyecto de campo (.qgz) para empaquetar con QFieldSync.

Parte de la última versión GUARDADA del proyecto abierto (el de oficina),
cambia la fuente de la capa de inspecciones de PostGIS al GeoPackage exportado
(conserva nombre, estilo y formulario, igual que "Cambiar fuente de datos…") y
la marca con la acción "Copy" de QFieldSync. El proyecto de oficina no se toca:
se lee en una instancia aparte y se escribe con otro nombre.
"""

import os

from PyQt5.QtXml import QDomDocument
from qgis.core import (
    Qgis,
    QgsDataProvider,
    QgsDataSourceUri,
    QgsFieldConstraints,
    QgsProject,
    QgsVectorLayer,
)

from . import config

# Propiedad de capa donde QFieldSync guarda la "Acción de empaquetado".
PROPIEDAD_ACCION_QFIELD = "QFieldSync/action"
ACCION_COPIAR = "copy"


def ruta_proyecto_campo(ruta_gpkg):
    """inspecciones.gpkg → inspecciones_campo.qgz, en la misma carpeta."""
    return os.path.splitext(ruta_gpkg)[0] + "_campo.qgz"


def _es_tabla_inspecciones(capa):
    if not isinstance(capa, QgsVectorLayer) or capa.providerType() != "postgres":
        return False
    uri = QgsDataSourceUri(capa.source())
    return uri.schema() == config.ESQUEMA and uri.table() == config.TABLA


def _estilo(capa):
    """Estilo completo de la capa (simbología, formulario, alias…) como documento <qgis>.

    Si la base no respondió al leer el proyecto la capa queda inválida y QGIS
    no le cargó el estilo; en ese caso se toma del XML original del proyecto.
    """
    doc = QDomDocument()
    if capa.isValid():
        capa.exportNamedStyle(doc)
        return doc
    xml = capa.originalXmlProperties()
    if not xml or not doc.setContent(xml)[0]:
        return None
    raiz = doc.documentElement()      # <maplayer> → <qgis>, que es lo que espera importNamedStyle
    raiz.setTagName("qgis")
    raiz.setAttribute("version", Qgis.version())
    return doc


def generar(ruta_gpkg, ruta_destino=None):
    """Escribe el proyecto de campo. Devuelve (ruta, nombres de capas que siguen en PostGIS)."""
    origen = QgsProject.instance().fileName()
    if not origen:
        raise ValueError("Guardá el proyecto abierto: el proyecto de campo se arma a partir de él.")
    ruta_destino = ruta_destino or ruta_proyecto_campo(ruta_gpkg)

    proyecto = QgsProject()
    if not proyecto.read(origen):
        raise RuntimeError(f"No se pudo leer el proyecto {origen}: {proyecto.error()}")

    capas = [c for c in proyecto.mapLayers().values() if _es_tabla_inspecciones(c)]
    if not capas:
        raise RuntimeError(
            f"El proyecto abierto no tiene una capa de PostGIS con la tabla "
            f"{config.ESQUEMA}.{config.TABLA}: no hay qué apuntar al GeoPackage."
        )

    fuente = f"{ruta_gpkg}|layername={config.CAPA_GPKG}"
    opciones = QgsDataProvider.ProviderOptions()
    opciones.transformContext = proyecto.transformContext()
    for capa in capas:
        estilo = _estilo(capa)
        capa.setDataSource(fuente, capa.name(), "ogr", opciones)
        if not capa.isValid():
            raise RuntimeError(f"No se pudo apuntar la capa '{capa.name()}' a {ruta_gpkg}.")
        if estilo is not None:
            capa.importNamedStyle(estilo)
        capa.setCustomProperty(PROPIEDAD_ACCION_QFIELD, ACCION_COPIAR)
        # Una OS creada en campo sin número no se puede importar: que QField no deje guardarla.
        indice = capa.fields().indexOf(config.CLAVE)
        if indice >= 0:
            capa.setFieldConstraint(indice, QgsFieldConstraints.ConstraintNotNull,
                                    QgsFieldConstraints.ConstraintStrengthHard)

    restantes = sorted(c.name() for c in proyecto.mapLayers().values()
                       if c.providerType() == "postgres")

    if not proyecto.write(ruta_destino):
        raise RuntimeError(f"No se pudo guardar {ruta_destino}: {proyecto.error()}")
    return ruta_destino, restantes
