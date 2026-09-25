"""
Lectura de la estructura real de la tabla (equivalente a \\d en psql).

Los nombres de columna se usan tal cual los devuelve la base: no hay que
confiar en que la lista de config.py tenga las tildes o el ° bien escritos.
"""

from dataclasses import dataclass, field

from . import config
from .conexion import ejecutar, ql, qi, tabla_calificada


@dataclass
class Columna:
    nombre: str
    tipo: str               # data_type de information_schema (ej: "text", "date", "USER-DEFINED")
    tiene_default: bool     # serial / identity / DEFAULT: la base genera el valor
    generada: bool          # GENERATED ALWAYS AS (...): no se puede escribir


@dataclass
class Esquema:
    columnas: list                      # [Columna] en orden de la tabla
    clave_primaria: list                # nombres
    geometria: str = ""                 # nombre de la columna geometry ("" si no hay)
    dimension_geom: int = 2
    por_nombre: dict = field(default_factory=dict)

    def __post_init__(self):
        self.por_nombre = {c.nombre: c for c in self.columnas}

    def nombres(self):
        return [c.nombre for c in self.columnas]

    def editables_faltantes(self):
        return [c for c in config.COLUMNAS_EDITABLES if c not in self.por_nombre]


def leer(conexion, tabla=config.TABLA, esquema=config.ESQUEMA):
    filas = ejecutar(conexion, f"""
        SELECT column_name, data_type, column_default IS NOT NULL OR is_identity = 'YES',
               is_generated = 'ALWAYS'
        FROM information_schema.columns
        WHERE table_schema = {ql(esquema)} AND table_name = {ql(tabla)}
        ORDER BY ordinal_position
    """)
    if not filas:
        raise RuntimeError(
            f"No se encontró la tabla {esquema}.{tabla} (o el usuario no tiene permiso para verla)."
        )
    columnas = [Columna(f[0], f[1], bool(f[2]), bool(f[3])) for f in filas]

    pk = [f[0] for f in ejecutar(conexion, f"""
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = {ql(tabla_calificada(tabla, esquema))}::regclass AND i.indisprimary
    """)]

    geom = ejecutar(conexion, f"""
        SELECT f_geometry_column, coord_dimension
        FROM geometry_columns
        WHERE f_table_schema = {ql(esquema)} AND f_table_name = {ql(tabla)}
        LIMIT 1
    """)
    nombre_geom, dimension = (geom[0][0], int(geom[0][1] or 2)) if geom else ("", 2)

    return Esquema(columnas, pk, nombre_geom, dimension)


def describir(esq):
    """Texto tipo \\d marcando qué columnas se actualizan desde campo."""
    ancho = max(len(c.nombre) for c in esq.columnas)
    lineas = [f"Tabla {config.ESQUEMA}.{config.TABLA}", ""]
    for c in esq.columnas:
        if c.nombre == config.CLAVE:
            rol = "clave del UPSERT"
        elif c.nombre in esq.clave_primaria:
            rol = "clave primaria" + (" (la genera la base)" if c.tiene_default else "")
        elif c.nombre == esq.geometria:
            rol = "geometría (solo en filas nuevas)" if not config.ACTUALIZAR_GEOMETRIA else "geometría (editable)"
        elif c.nombre in config.COLUMNAS_EDITABLES:
            rol = "EDITABLE en campo"
        else:
            rol = "solo lectura"
        lineas.append(f"  {qi(c.nombre):<{ancho + 2}}  {c.tipo:<22}  {rol}")

    faltantes = esq.editables_faltantes()
    if faltantes:
        lineas += ["", "⚠ Columnas de COLUMNAS_EDITABLES (config.py) que NO existen en la tabla:"]
        lineas += [f"  {n}" for n in faltantes]
    if config.CLAVE not in esq.por_nombre:
        lineas += ["", f"⚠ No existe la columna clave {qi(config.CLAVE)}."]
    return "\n".join(lineas)


def columna_fk(conexion, tabla_hija):
    """Columna de tabla_hija que referencia inspecciones."n°_os", leída del constraint.

    Devuelve (nombre, declarada). Si no hay FK declarada, usa config.COLUMNA_FK_HIJAS
    y declarada=False para que quien llama lo avise.
    """
    filas = ejecutar(conexion, f"""
        SELECT a.attname
        FROM pg_constraint c
        JOIN pg_attribute a  ON a.attrelid  = c.conrelid  AND a.attnum  = ANY(c.conkey)
        JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = ANY(c.confkey)
        WHERE c.contype = 'f'
          AND c.conrelid  = {ql(tabla_calificada(tabla_hija))}::regclass
          AND c.confrelid = {ql(tabla_calificada(config.TABLA))}::regclass
          AND af.attname = {ql(config.CLAVE)}
        LIMIT 1
    """)
    if filas:
        return filas[0][0], True
    return config.COLUMNA_FK_HIJAS, False


def existe_tabla(conexion, tabla):
    return bool(ejecutar(conexion, f"SELECT to_regclass({ql(tabla_calificada(tabla))}) IS NOT NULL")[0][0])


def describir_hija(conexion, tabla):
    """Texto tipo \\d de una tabla hija: FK, clave para no duplicar y editables."""
    cfg = config.TABLAS_HIJAS[tabla]
    if not existe_tabla(conexion, tabla):
        return f"Tabla {config.ESQUEMA}.{tabla}\n\n⚠ No existe en la base."
    esq = leer(conexion, tabla)
    fk, declarada = columna_fk(conexion, tabla)
    ancho = max(len(c.nombre) for c in esq.columnas)
    lineas = [f"Tabla {config.ESQUEMA}.{tabla}", ""]
    for c in esq.columnas:
        roles = []
        if c.nombre in esq.clave_primaria:
            roles.append("clave primaria" + (" (la genera la base)" if c.tiene_default else ""))
        if c.nombre == fk:
            roles.append(f"FK → {config.TABLA}.{config.CLAVE}")
        if c.nombre in cfg["clave_dedupe"]:
            roles.append("identifica filas ya importadas")
        if cfg["conflicto"] == "actualizar" and c.nombre in cfg["editables"]:
            roles.append("EDITABLE en campo")
        lineas.append(f"  {qi(c.nombre):<{ancho + 2}}  {c.tipo:<22}  {', '.join(roles) or 'solo inserción'}")

    if not declarada:
        lineas += ["", f"⚠ No hay FK declarada hacia {config.TABLA}; se usa {qi(fk)} (config.py)."]
    if fk not in esq.por_nombre:
        lineas += ["", f"⚠ No existe la columna {qi(fk)}."]
    faltan = [c for c in cfg["clave_dedupe"] + cfg["editables"] if c not in esq.por_nombre]
    if faltan:
        lineas += ["", "⚠ Columnas de config.py que NO existen en la tabla: " + ", ".join(faltan)]
        if config.COLUMNA_UUID in faltan:
            lineas.append("  Para crear uuid: campo/migraciones/observaciones_uuid.sql")
    return "\n".join(lineas)


def describir_todo(conexion):
    partes = [describir(leer(conexion))]
    partes += [describir_hija(conexion, t) for t in config.TABLAS_HIJAS]
    return ("\n\n" + "─" * 60 + "\n\n").join(partes)
