"""
Carga de una capa de GeoPackage a una tabla de staging en PostGIS.

El staging se crea con los MISMOS tipos que la tabla real
(CREATE TABLE AS ... WITH NO DATA): un valor que no entra en el tipo de su
columna falla acá, antes de tocar la tabla real. Lo usan inspecciones y las
tablas hijas (fotos, observaciones).
"""

from PyQt5.QtCore import QDate, QDateTime, QTime, QVariant, Qt
from qgis.core import QgsProviderRegistry, QgsVectorLayer

from . import config
from .conexion import ejecutar, ql, qi, tabla_calificada

FILAS_POR_INSERT = 200
TIPOS_TEXTO = {"text", "character varying", "character"}


def capas_gpkg(ruta):
    """Nombres de las capas dentro del GeoPackage.

    Si el gpkg es el data.gpkg que arma QFieldSync con "edición sin conexión",
    se omiten sus tablas internas de registro (log_*).
    """
    subcapas = QgsProviderRegistry.instance().querySublayers(ruta)
    return [s.name() for s in subcapas
            if s.providerKey() == "ogr" and not s.name().startswith("log_")]


def capa_sugerida(capas, nombre):
    """`nombre` si está; si no, la que QFieldSync renombró a <nombre>_<id>; si no, ""."""
    if nombre in capas:
        return nombre
    return next((c for c in capas if c.startswith(nombre + "_")), "")


def abrir_capa_gpkg(ruta, nombre_capa):
    capa = QgsVectorLayer(f"{ruta}|layername={nombre_capa}", nombre_capa, "ogr")
    if not capa.isValid():
        raise RuntimeError(f"No se pudo abrir la capa '{nombre_capa}' de {ruta}.")
    return capa


def columnas_a_cargar(esq, capa):
    """Columnas del gpkg que existen en la tabla, en el orden de la tabla.

    Se descartan las que genera la base (fid serial, identity, generadas): en
    filas nuevas las completa PostgreSQL y en las existentes no se tocan.
    Devuelve (columnas, campos del gpkg que no están en la tabla).
    """
    campos_gpkg = set(capa.fields().names())
    columnas = []
    for c in esq.columnas:
        if c.nombre == esq.geometria or c.nombre not in campos_gpkg:
            continue
        if c.generada or (c.tiene_default and c.nombre in esq.clave_primaria):
            continue
        columnas.append(c.nombre)
    if esq.geometria and capa.isSpatial():
        columnas.append(esq.geometria)
    ignoradas = sorted(campos_gpkg - set(esq.nombres()))
    return columnas, ignoradas


class Staging:
    def __init__(self, conexion, esq, tabla, nombre, capa, columnas):
        self.conexion = conexion
        self.esq = esq
        self.tabla = tabla              # tabla real (define los tipos)
        self.nombre = nombre            # tabla de staging
        self.capa = capa
        self.columnas = columnas

    @property
    def calificada(self):
        return tabla_calificada(self.nombre)

    def cargar(self):
        cols = ", ".join(qi(c) for c in self.columnas)
        ejecutar(self.conexion, f"DROP TABLE IF EXISTS {self.calificada}")
        ejecutar(self.conexion, f"""
            CREATE TABLE {self.calificada} AS
            SELECT {cols} FROM {tabla_calificada(self.tabla)} WITH NO DATA
        """)
        lote = []
        for feature in self.capa.getFeatures():
            lote.append("(" + ", ".join(self._valor_sql(feature, c) for c in self.columnas) + ")")
            if len(lote) >= FILAS_POR_INSERT:
                self._insertar_lote(cols, lote)
                lote = []
        if lote:
            self._insertar_lote(cols, lote)

    def _insertar_lote(self, cols, lote):
        ejecutar(self.conexion, f"INSERT INTO {self.calificada} ({cols}) VALUES\n" + ",\n".join(lote))

    def _valor_sql(self, feature, columna):
        if columna == self.esq.geometria:
            geom = feature.geometry()
            if geom is None or geom.isNull():
                return "NULL"
            sql = f"ST_SetSRID(ST_GeomFromWKB(decode({ql(geom.asWkb().toHex().data().decode())}, 'hex')), {config.SRID})"
            return f"ST_Force2D({sql})" if self.esq.dimension_geom == 2 else sql

        valor = feature[columna]
        if valor is None or (isinstance(valor, QVariant) and valor.isNull()):
            return "NULL"
        if isinstance(valor, bool):
            return "TRUE" if valor else "FALSE"
        if isinstance(valor, (QDate, QDateTime, QTime)):
            return ql(valor.toString(Qt.ISODate)) if valor.isValid() else "NULL"
        texto = str(valor)
        # Un "" en una columna no-texto (fecha, número, uuid) es un campo vacío del formulario.
        if texto == "" and self.esq.por_nombre[columna].tipo not in TIPOS_TEXTO:
            return "NULL"
        # Literal sin tipo: PostgreSQL lo convierte al tipo de la columna de staging.
        return ql(texto)

    def borrar(self):
        try:
            ejecutar(self.conexion, f"DROP TABLE IF EXISTS {self.calificada}")
        except Exception:
            pass    # no tapar el error original; queda para el próximo DROP IF EXISTS
