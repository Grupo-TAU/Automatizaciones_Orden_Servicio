"""
Genera el proyecto de campo (.qgz) para empaquetar con QFieldSync.

Parte de la última versión GUARDADA del proyecto abierto (el de oficina),
cambia la fuente de las capas de PostGIS de inspecciones, fotos y observaciones
a sus capas del GeoPackage exportado (conserva nombre, estilo, formulario y las
relaciones entre ellas, igual que "Cambiar fuente de datos…") y las marca con
la acción "Copy" de QFieldSync. El proyecto de oficina no se toca:
se lee en una instancia aparte y se escribe con otro nombre.
"""

import os

from PyQt5.QtXml import QDomDocument
from qgis.core import (
    Qgis,
    QgsDataProvider,
    QgsDataSourceUri,
    QgsDefaultValue,
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


def _tabla_postgis(capa):
    """Nombre de la tabla del esquema de inspecciones a la que apunta la capa, o ""."""
    if not isinstance(capa, QgsVectorLayer) or capa.providerType() != "postgres":
        return ""
    uri = QgsDataSourceUri(capa.source())
    return uri.table() if uri.schema() == config.ESQUEMA else ""


def _capas_gpkg_por_tabla():
    """tabla de la base → capa del GeoPackage."""
    capas = {config.TABLA: config.CAPA_GPKG}
    capas.update({t: cfg["capa_gpkg"] for t, cfg in config.TABLAS_HIJAS.items()})
    return capas


def _obligatorio(capa, campo):
    indice = capa.fields().indexOf(campo)
    if indice >= 0:
        capa.setFieldConstraint(indice, QgsFieldConstraints.ConstraintNotNull,
                                QgsFieldConstraints.ConstraintStrengthHard)


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
    """Escribe el proyecto de campo.

    Devuelve (ruta, capas que siguen en PostGIS, tablas hijas sin capa en el proyecto).
    """
    origen = QgsProject.instance().fileName()
    if not origen:
        raise ValueError("Guardá el proyecto abierto: el proyecto de campo se arma a partir de él.")
    ruta_destino = ruta_destino or ruta_proyecto_campo(ruta_gpkg)

    proyecto = QgsProject()
    if not proyecto.read(origen):
        raise RuntimeError(f"No se pudo leer el proyecto {origen}: {proyecto.error()}")

    capas_gpkg = _capas_gpkg_por_tabla()
    a_cambiar = [(c, _tabla_postgis(c)) for c in proyecto.mapLayers().values()]
    a_cambiar = [(c, t) for c, t in a_cambiar if t in capas_gpkg]
    if not any(t == config.TABLA for _, t in a_cambiar):
        raise RuntimeError(
            f"El proyecto abierto no tiene una capa de PostGIS con la tabla "
            f"{config.ESQUEMA}.{config.TABLA}: no hay qué apuntar al GeoPackage."
        )

    opciones = QgsDataProvider.ProviderOptions()
    opciones.transformContext = proyecto.transformContext()
    for capa, tabla in a_cambiar:
        estilo = _estilo(capa)
        capa.setDataSource(f"{ruta_gpkg}|layername={capas_gpkg[tabla]}", capa.name(), "ogr", opciones)
        if not capa.isValid():
            raise RuntimeError(f"No se pudo apuntar la capa '{capa.name()}' a {ruta_gpkg}.")
        if estilo is not None:
            capa.importNamedStyle(estilo)
        capa.setCustomProperty(PROPIEDAD_ACCION_QFIELD, ACCION_COPIAR)

        if tabla == config.TABLA:
            # Una OS creada en campo sin número no se puede importar: que QField no deje guardarla.
            _obligatorio(capa, config.CLAVE)
        else:
            # Fila hija sin N°_OS = huérfana para siempre. El formulario de la relación lo completa solo.
            _obligatorio(capa, config.COLUMNA_FK_HIJAS)
            indice = capa.fields().indexOf(config.COLUMNA_UUID)
            if indice >= 0 and config.COLUMNA_UUID in config.TABLAS_HIJAS[tabla]["clave_dedupe"]:
                # Clave estable de la fila: se genera en el celular al crearla.
                capa.setDefaultValueDefinition(indice, QgsDefaultValue("uuid('WithoutBraces')"))
                _obligatorio(capa, config.COLUMNA_UUID)

    restantes = sorted(c.name() for c in proyecto.mapLayers().values()
                       if c.providerType() == "postgres")
    con_capa = {t for _, t in a_cambiar}
    sin_capa = [t for t in config.TABLAS_HIJAS if t not in con_capa]

    if not proyecto.write(ruta_destino):
        raise RuntimeError(f"No se pudo guardar {ruta_destino}: {proyecto.error()}")
    return ruta_destino, restantes, sin_capa
