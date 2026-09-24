"""
Export de inspecciones filtradas de PostGIS a un GeoPackage nuevo.

Reemplaza al paso manual:
    ogr2ogr -f GPKG salida.gpkg PG:"..." -sql "SELECT * FROM inspecciones_os.inspecciones WHERE ..."

Las geometrías salen tal como están en la base (EPSG:32721), sin transformar.
Después de esto el gpkg se empaqueta aparte con QFieldSync.
"""

import re

from qgis.core import QgsProject, QgsVectorFileWriter, QgsVectorLayer

from . import config, esquema
from .conexion import conectar, ejecutar, qi, ql, tabla_calificada, uri_base


def parsear_numeros(texto):
    """Números de OS pegados separados por coma, punto y coma, tab o salto de línea."""
    vistos = []
    for parte in re.split(r"[,;\t\r\n]+", texto or ""):
        parte = parte.strip()
        if parte and parte not in vistos:
            vistos.append(parte)
    return vistos


def construir_filtro(numeros, etapa):
    """WHERE (sin la palabra WHERE) en SQL de PostgreSQL. Combina con AND."""
    condiciones = []
    if numeros:
        condiciones.append(f"{qi(config.CLAVE)}::text IN ({', '.join(ql(n) for n in numeros)})")
    if etapa:
        condiciones.append(f"{qi(config.COLUMNA_ETAPA)} = {ql(etapa)}")
    if not condiciones:
        raise ValueError("Elegí al menos un filtro: números de OS, etapa o ambos.")
    return " AND ".join(condiciones)


def etapas(conexion=None):
    conexion = conexion or conectar()
    filas = ejecutar(conexion, f"""
        SELECT DISTINCT {qi(config.COLUMNA_ETAPA)}
        FROM {tabla_calificada(config.TABLA)}
        WHERE {qi(config.COLUMNA_ETAPA)} IS NOT NULL
        ORDER BY 1
    """)
    return [str(f[0]) for f in filas]


def previsualizar(numeros, etapa, conexion=None):
    """(filas que se exportarían, números pedidos que no existen en la tabla)."""
    conexion = conexion or conectar()
    filtro = construir_filtro(numeros, etapa)
    tabla = tabla_calificada(config.TABLA)
    total = ejecutar(conexion, f"SELECT count(*) FROM {tabla} WHERE {filtro}")[0][0]

    no_encontrados = []
    if numeros:
        encontrados = {str(f[0]) for f in ejecutar(conexion, f"""
            SELECT {qi(config.CLAVE)}::text FROM {tabla}
            WHERE {qi(config.CLAVE)}::text IN ({', '.join(ql(n) for n in numeros)})
        """)}
        no_encontrados = [n for n in numeros if n not in encontrados]
    return int(total), no_encontrados


def exportar(ruta_gpkg, numeros, etapa):
    """Escribe el GeoPackage (lo pisa si existe). Devuelve la cantidad de filas exportadas."""
    conexion = conectar()
    esq = esquema.leer(conexion)
    filtro = construir_filtro(numeros, etapa)

    uri = uri_base()
    clave_capa = esq.clave_primaria[0] if len(esq.clave_primaria) == 1 else config.CLAVE
    uri.setDataSource(config.ESQUEMA, config.TABLA, esq.geometria or None, filtro, clave_capa)
    capa = QgsVectorLayer(uri.uri(False), config.CAPA_GPKG, "postgres")
    if not capa.isValid():
        raise RuntimeError(
            "QGIS no pudo abrir la tabla con ese filtro. Revisá la conexión y los permisos.\n"
            + capa.dataProvider().error().summary()
        )
    if capa.crs().isValid() and capa.crs().postgisSrid() != config.SRID:
        raise RuntimeError(
            f"La tabla está en {capa.crs().authid()}, se esperaba EPSG:{config.SRID}. "
            "No se transforma: revisá la base antes de exportar."
        )

    cantidad = capa.featureCount()
    if cantidad == 0:
        raise ValueError("El filtro no devuelve ninguna inspección: no se generó el archivo.")

    opciones = QgsVectorFileWriter.SaveVectorOptions()
    opciones.driverName = "GPKG"
    opciones.layerName = config.CAPA_GPKG
    opciones.fileEncoding = "UTF-8"
    opciones.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
    resultado = QgsVectorFileWriter.writeAsVectorFormatV3(
        capa, ruta_gpkg, QgsProject.instance().transformContext(), opciones
    )
    if resultado[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"No se pudo escribir el GeoPackage: {resultado[1]}")
    return cantidad
