"""
Import del GeoPackage editado en campo a PostGIS, con UPSERT seguro.

Flujo (ver Importacion):
  1. cargar_staging(): crea inspecciones_staging_<iniciales> con los MISMOS tipos
     que la tabla real (CREATE TABLE AS ... WITH NO DATA) y copia las filas del
     gpkg. Un valor que no entra en el tipo de la columna falla acá, antes de
     tocar la tabla real.
  2. analizar(): chequeos (clave nula / duplicada) y conteos del modo prueba.
  3. aplicar(): un único INSERT ... ON CONFLICT ("n°_os") DO UPDATE, atómico.
     El SET incluye SOLO config.COLUMNAS_EDITABLES; la geometría y el resto de
     las columnas se escriben únicamente en filas nuevas.
  4. borrar_staging(): siempre, también si algo falló.

Fuera de alcance por ahora (se enchufan en analizar()/aplicar()):
  - resolución de conflictos cuando la misma OS se editó en el server y en campo;
  - fotos/adjuntos (tabla fotos_os, todavía no existe).
"""

from dataclasses import dataclass, field

from PyQt5.QtCore import QDate, QDateTime, QTime, QVariant, Qt
from qgis.core import QgsProviderRegistry, QgsVectorLayer

from . import config, esquema
from .conexion import conectar, ejecutar, nombre_staging, qi, ql, tabla_calificada

FILAS_POR_INSERT = 200
TIPOS_TEXTO = {"text", "character varying", "character"}
MAX_LISTADO = 30


def capas_gpkg(ruta):
    """Nombres de las capas vectoriales dentro del GeoPackage."""
    subcapas = QgsProviderRegistry.instance().querySublayers(ruta)
    return [s.name() for s in subcapas if s.providerKey() == "ogr"]


def abrir_capa_gpkg(ruta, nombre_capa):
    capa = QgsVectorLayer(f"{ruta}|layername={nombre_capa}", nombre_capa, "ogr")
    if not capa.isValid():
        raise RuntimeError(f"No se pudo abrir la capa '{nombre_capa}' de {ruta}.")
    return capa


@dataclass
class Analisis:
    total: int = 0
    existentes: int = 0
    nuevas: int = 0
    con_cambios: int = 0
    cambios_por_columna: dict = field(default_factory=dict)   # columna -> filas que cambian
    numeros_nuevos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    def texto(self):
        lineas = [
            f"Filas en el GeoPackage:           {self.total}",
            f"  Coinciden con OS existentes:    {self.existentes}",
            f"    con algún cambio editable:    {self.con_cambios}",
            f"    sin cambios:                  {self.existentes - self.con_cambios}",
            f"  OS nuevas (se insertan):        {self.nuevas}",
        ]
        cambios = {c: n for c, n in self.cambios_por_columna.items() if n}
        if cambios:
            lineas += ["", "Filas que cambian, por columna:"]
            ancho = max(len(c) for c in cambios)
            lineas += [f"  {c:<{ancho}}  {n}" for c, n in cambios.items()]
        if self.numeros_nuevos:
            lineas += ["", "OS nuevas:"]
            lineas += [f"  {n}" for n in self.numeros_nuevos[:MAX_LISTADO]]
            if self.nuevas > MAX_LISTADO:
                lineas.append(f"  … y {self.nuevas - MAX_LISTADO} más")
        if self.avisos:
            lineas += ["", "Avisos:"] + [f"  ⚠ {a}" for a in self.avisos]
        return "\n".join(lineas)


class Importacion:
    """Una importación de un gpkg. Usar como context manager para garantizar el DROP:

        with Importacion(ruta, capa, "NA") as imp:
            analisis = imp.analizar()
            insertadas, actualizadas = imp.aplicar()
    """

    def __init__(self, ruta_gpkg, nombre_capa, iniciales):
        self.staging = nombre_staging(iniciales)
        self.capa = abrir_capa_gpkg(ruta_gpkg, nombre_capa)
        self.conexion = conectar()
        self.esq = esquema.leer(self.conexion)
        self.avisos = []
        self._validar_esquema()
        self.columnas = self._columnas_a_cargar()
        self.editables = [c for c in self.esq.nombres()
                          if c in config.COLUMNAS_EDITABLES and c in self.columnas]
        if config.ACTUALIZAR_GEOMETRIA and self.esq.geometria in self.columnas:
            self.editables.append(self.esq.geometria)

    def __enter__(self):
        self.cargar_staging()
        return self

    def __exit__(self, *exc):
        self.borrar_staging()
        return False

    # ── Validaciones ────────────────────────────────────────────────────────
    def _validar_esquema(self):
        faltantes = self.esq.editables_faltantes()
        if faltantes:
            raise RuntimeError(
                "Estas columnas de COLUMNAS_EDITABLES (campo/config.py) no existen en "
                f"{config.ESQUEMA}.{config.TABLA}:\n  " + "\n  ".join(faltantes)
                + "\n\nColumnas reales:\n  " + "\n  ".join(self.esq.nombres())
            )
        if config.CLAVE not in self.esq.por_nombre:
            raise RuntimeError(f"La tabla no tiene la columna clave {qi(config.CLAVE)}.")
        if self.capa.fields().indexOf(config.CLAVE) < 0:
            raise RuntimeError(f"El GeoPackage no tiene la columna clave {qi(config.CLAVE)}.")

        crs = self.capa.crs()
        if self.esq.geometria and crs.isValid() and crs.postgisSrid() != config.SRID:
            raise RuntimeError(
                f"El GeoPackage está en {crs.authid()}, se esperaba EPSG:{config.SRID}. "
                "No se transforma: revisá el archivo."
            )

    def _columnas_a_cargar(self):
        """Columnas del gpkg que existen en la tabla, en el orden de la tabla.

        Se descartan las que genera la base (fid serial, identity, generadas):
        en filas nuevas las completa PostgreSQL, en existentes no se tocan.
        """
        campos_gpkg = set(self.capa.fields().names())
        columnas = []
        for c in self.esq.columnas:
            if c.nombre == self.esq.geometria:
                continue
            if c.nombre not in campos_gpkg:
                continue
            if c.generada or (c.tiene_default and c.nombre in self.esq.clave_primaria):
                continue
            columnas.append(c.nombre)

        ignoradas = sorted(campos_gpkg - set(self.esq.nombres()))
        if ignoradas:
            self.avisos.append("Columnas del GeoPackage que no están en la tabla (se ignoran): "
                               + ", ".join(ignoradas))
        sin_dato = [c for c in config.COLUMNAS_EDITABLES if c not in campos_gpkg]
        if sin_dato:
            self.avisos.append("Columnas editables que no vienen en el GeoPackage (no se tocan): "
                               + ", ".join(sin_dato))

        if self.esq.geometria and self.capa.isSpatial():
            columnas.append(self.esq.geometria)
        return columnas

    # ── Staging ─────────────────────────────────────────────────────────────
    def cargar_staging(self):
        stg = tabla_calificada(self.staging)
        cols = ", ".join(qi(c) for c in self.columnas)
        ejecutar(self.conexion, f"DROP TABLE IF EXISTS {stg}")
        ejecutar(self.conexion, f"""
            CREATE TABLE {stg} AS
            SELECT {cols} FROM {tabla_calificada(config.TABLA)} WITH NO DATA
        """)

        lote = []
        for feature in self.capa.getFeatures():
            lote.append("(" + ", ".join(self._valor_sql(feature, c) for c in self.columnas) + ")")
            if len(lote) >= FILAS_POR_INSERT:
                self._insertar_lote(stg, cols, lote)
                lote = []
        if lote:
            self._insertar_lote(stg, cols, lote)

    def _insertar_lote(self, stg, cols, lote):
        ejecutar(self.conexion, f"INSERT INTO {stg} ({cols}) VALUES\n" + ",\n".join(lote))

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
        # Un "" en una columna no-texto (fecha, número) es un campo vacío del formulario.
        if texto == "" and self.esq.por_nombre[columna].tipo not in TIPOS_TEXTO:
            return "NULL"
        # Literal sin tipo: PostgreSQL lo convierte al tipo de la columna de staging.
        return ql(texto)

    def borrar_staging(self):
        try:
            ejecutar(self.conexion, f"DROP TABLE IF EXISTS {tabla_calificada(self.staging)}")
        except Exception:
            pass    # no tapar el error original; queda para el próximo DROP IF EXISTS

    # ── Análisis (modo prueba) ──────────────────────────────────────────────
    def analizar(self):
        stg = tabla_calificada(self.staging)
        tabla = tabla_calificada(config.TABLA)
        clave = qi(config.CLAVE)

        nulas = ejecutar(self.conexion, f"SELECT count(*) FROM {stg} WHERE {clave} IS NULL")[0][0]
        if nulas:
            raise RuntimeError(f"Hay {nulas} fila(s) en el GeoPackage sin {config.CLAVE}. "
                               "Completalas antes de importar.")
        duplicadas = ejecutar(self.conexion, f"""
            SELECT {clave}, count(*) FROM {stg} GROUP BY 1 HAVING count(*) > 1 ORDER BY 1 LIMIT {MAX_LISTADO}
        """)
        if duplicadas:
            raise RuntimeError(
                f"Hay {config.CLAVE} repetidos en el GeoPackage:\n  "
                + "\n  ".join(f"{f[0]} ({f[1]} veces)" for f in duplicadas)
            )

        cambia = [f"t.{qi(c)} IS DISTINCT FROM s.{qi(c)}" for c in self.editables]
        alguno = " OR ".join(cambia) or "FALSE"
        por_columna = "".join(
            f",\n count(*) FILTER (WHERE t.{clave} IS NOT NULL AND {cond})" for cond in cambia
        )
        fila = ejecutar(self.conexion, f"""
            SELECT count(*),
                   count(*) FILTER (WHERE t.{clave} IS NOT NULL),
                   count(*) FILTER (WHERE t.{clave} IS NOT NULL AND ({alguno})){por_columna}
            FROM {stg} s LEFT JOIN {tabla} t ON t.{clave} = s.{clave}
        """)[0]

        nuevos = ejecutar(self.conexion, f"""
            SELECT s.{clave}::text FROM {stg} s
            WHERE NOT EXISTS (SELECT 1 FROM {tabla} t WHERE t.{clave} = s.{clave})
            ORDER BY 1 LIMIT {MAX_LISTADO}
        """)

        total, existentes, con_cambios = (int(v) for v in fila[:3])
        return Analisis(
            total=total,
            existentes=existentes,
            nuevas=total - existentes,
            con_cambios=con_cambios,
            cambios_por_columna={c: int(n) for c, n in zip(self.editables, fila[3:])},
            numeros_nuevos=[f[0] for f in nuevos],
            avisos=list(self.avisos),
        )

    # ── UPSERT ──────────────────────────────────────────────────────────────
    def aplicar(self):
        """Ejecuta el UPSERT. Devuelve (insertadas, actualizadas).

        Las filas existentes sin cambios en columnas editables no se reescriben
        (WHERE ... IS DISTINCT FROM), así que no cuentan como actualizadas.
        xmax = 0 en la fila devuelta distingue un INSERT de un UPDATE.
        """
        cols = ", ".join(qi(c) for c in self.columnas)
        if self.editables:
            set_ = ", ".join(f"{qi(c)} = EXCLUDED.{qi(c)}" for c in self.editables)
            destino = ", ".join(f"t.{qi(c)}" for c in self.editables)
            origen = ", ".join(f"EXCLUDED.{qi(c)}" for c in self.editables)
            conflicto = (f"DO UPDATE SET {set_}\n"
                         f"      WHERE ({destino}) IS DISTINCT FROM ({origen})")
        else:
            conflicto = "DO NOTHING"

        fila = ejecutar(self.conexion, f"""
            WITH upsert AS (
                INSERT INTO {tabla_calificada(config.TABLA)} AS t ({cols})
                SELECT {cols} FROM {tabla_calificada(self.staging)}
                ON CONFLICT ({qi(config.CLAVE)}) {conflicto}
                RETURNING (t.xmax = 0) AS insertada
            )
            SELECT count(*) FILTER (WHERE insertada), count(*) FILTER (WHERE NOT insertada)
            FROM upsert
        """)[0]
        return int(fila[0]), int(fila[1])
