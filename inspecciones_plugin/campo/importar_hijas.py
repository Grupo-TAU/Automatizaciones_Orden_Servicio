"""
Import de las tablas hijas (fotos, observaciones) desde el GeoPackage de campo.

Va SIEMPRE después de importar inspecciones (el diálogo lo hace cumplir): una
fila hija solo entra si su N°_OS ya existe en inspecciones.

  1. Staging <tabla>_staging_<iniciales>, con los tipos de la tabla real.
  2. analizar(): qué se insertaría, qué ya estaba (por clave_dedupe, nunca por
     fid) y las huérfanas agrupadas por N°_OS.
  3. aplicar(): un único INSERT ... SELECT ... INNER JOIN inspecciones, que deja
     afuera a las huérfanas sin abortar nada. Con conflicto = "actualizar",
     en la misma sentencia se actualizan las `editables` de las existentes.
  4. DROP del staging.

Las huérfanas no son un error: suelen ser fotos de una OS que todavía no se
cerró en campo y entran en el próximo ciclo. Se reportan para revisión manual
(detectar typos persistentes queda fuera de esta versión).
"""

from dataclasses import dataclass, field

from . import config, esquema
from .conexion import conectar, ejecutar, nombre_staging, qi, ql, tabla_calificada
from .staging import Staging, abrir_capa_gpkg, columnas_a_cargar

MAX_LISTADO = 30


@dataclass
class AnalisisHija:
    tabla: str
    total: int = 0
    a_insertar: int = 0
    existentes: int = 0
    con_cambios: int = 0             # solo con conflicto = "actualizar"
    sin_clave: int = 0               # clave_dedupe vacía: no se puede saber si ya está
    repetidas: int = 0               # misma clave_dedupe más de una vez en el gpkg
    huerfanas: list = field(default_factory=list)       # [(N°_OS, filas)]
    rutas_invalidas: list = field(default_factory=list)  # solo fotos: rutas que no siguen el patrón
    avisos: list = field(default_factory=list)

    @property
    def filas_huerfanas(self):
        return sum(n for _, n in self.huerfanas)

    def texto(self):
        lineas = [
            f"── {self.tabla} ──",
            f"Filas en el GeoPackage:        {self.total}",
            f"  Nuevas (se insertan):        {self.a_insertar}",
            f"  Ya estaban en la base:       {self.existentes}"
            + (f" ({self.con_cambios} con cambios, se actualizan)" if self.con_cambios else ""),
            f"  Huérfanas (quedan pendientes): {self.filas_huerfanas}",
        ]
        if self.sin_clave:
            lineas.append(f"  Sin clave, no se importan:   {self.sin_clave}")
        if self.repetidas:
            lineas.append(f"  Repetidas en el gpkg (entra una): {self.repetidas}")
        if self.huerfanas:
            lineas += ["", f"N°_OS huérfanos (no existen en {config.TABLA}):"]
            lineas += [f"  {os_ or '(vacío)'}: {n} fila(s)" for os_, n in self.huerfanas[:MAX_LISTADO]]
            if len(self.huerfanas) > MAX_LISTADO:
                lineas.append(f"  … y {len(self.huerfanas) - MAX_LISTADO} OS más")
            lineas.append("  Si alguna OS sigue huérfana varios ciclos, revisá si es un typo.")
        if self.rutas_invalidas:
            lineas += ["", "Rutas que no siguen DCIM/FOTOS_OS/<N°_OS>/<archivo> "
                           "(la fila se importa, el archivo no se copia):"]
            lineas += [f"  {r}" for r in self.rutas_invalidas[:MAX_LISTADO]]
        if self.avisos:
            lineas += [""] + [f"⚠ {a}" for a in self.avisos]
        return "\n".join(lineas)


@dataclass
class ResultadoHija:
    tabla: str
    insertadas: list = field(default_factory=list)   # [dict columna → texto] (pk + clave_dedupe)
    actualizadas: int = 0
    pk: list = field(default_factory=list)

    def texto(self):
        return f"✓ {self.tabla}: {len(self.insertadas)} insertada(s), {self.actualizadas} actualizada(s)."


class ImportacionHija:
    """Import de una tabla hija. Context manager: el staging se borra siempre.

        with ImportacionHija(ruta, "fotos", "fotos", "NA") as imp:
            analisis = imp.analizar()
            resultado = imp.aplicar()
    """

    def __init__(self, ruta_gpkg, nombre_capa, tabla, iniciales, conexion=None):
        self.tabla = tabla
        self.cfg = config.TABLAS_HIJAS[tabla]
        self.capa = abrir_capa_gpkg(ruta_gpkg, nombre_capa)
        self.conexion = conexion or conectar()
        self.avisos = []

        if not esquema.existe_tabla(self.conexion, tabla):
            raise RuntimeError(f"No existe la tabla {config.ESQUEMA}.{tabla} en la base.")
        self.esq = esquema.leer(self.conexion, tabla)
        self.fk, declarada = esquema.columna_fk(self.conexion, tabla)
        if not declarada:
            self.avisos.append(f"{tabla} no tiene FK declarada hacia {config.TABLA}; "
                               f"se usa la columna {qi(self.fk)} de config.py.")
        self.clave = list(self.cfg["clave_dedupe"])
        self.editables = list(self.cfg["editables"]) if self.cfg["conflicto"] == "actualizar" else []
        self._validar()

        self.columnas, ignoradas = columnas_a_cargar(self.esq, self.capa)
        if ignoradas:
            self.avisos.append("Columnas del GeoPackage que no están en la tabla (se ignoran): "
                               + ", ".join(ignoradas))
        self.pk = [c for c in self.esq.clave_primaria]
        self.stg = Staging(self.conexion, self.esq, tabla,
                           nombre_staging(iniciales, f"{tabla}_staging"), self.capa, self.columnas)

    def __enter__(self):
        self.stg.cargar()
        return self

    def __exit__(self, *exc):
        self.stg.borrar()
        return False

    def _validar(self):
        campos_gpkg = set(self.capa.fields().names())
        faltan_tabla = [c for c in [self.fk] + self.clave + self.editables if c not in self.esq.por_nombre]
        if faltan_tabla:
            mensaje = (f"Columnas que no existen en {config.ESQUEMA}.{self.tabla}: "
                       + ", ".join(faltan_tabla) + "\nColumnas reales: " + ", ".join(self.esq.nombres()))
            if config.COLUMNA_UUID in faltan_tabla:
                mensaje += ("\n\nFalta crear la columna uuid: correr una vez "
                            "campo/migraciones/observaciones_uuid.sql en la base.")
            raise RuntimeError(mensaje)
        faltan_gpkg = [c for c in [self.fk] + self.clave if c not in campos_gpkg]
        if faltan_gpkg:
            raise RuntimeError(f"La capa '{self.capa.name()}' del GeoPackage no tiene: "
                               + ", ".join(faltan_gpkg))

    # ── SQL comunes ─────────────────────────────────────────────────────────
    def _clave_no_nula(self, alias):
        return " AND ".join(f"{alias}.{qi(c)} IS NOT NULL" for c in self.clave)

    def _misma_clave(self, a, b):
        return " AND ".join(f"{a}.{qi(c)} = {b}.{qi(c)}" for c in self.clave)

    def _staging_sin_repetidos(self):
        """Una fila por clave_dedupe (DISTINCT ON), solo con clave completa."""
        cols = ", ".join(qi(c) for c in self.clave)
        return (f"(SELECT DISTINCT ON ({cols}) * FROM {self.stg.calificada} s "
                f"WHERE {self._clave_no_nula('s')} ORDER BY {cols})")

    # ── Análisis (modo prueba) ──────────────────────────────────────────────
    def analizar(self):
        stg = self.stg.calificada
        padre = tabla_calificada(config.TABLA)
        tabla = tabla_calificada(self.tabla)
        fk, clave_padre = qi(self.fk), qi(config.CLAVE)
        clave_cols = ", ".join(f"s.{qi(c)}" for c in self.clave)
        unicas = self._staging_sin_repetidos()

        total, sin_clave, distintas = ejecutar(self.conexion, f"""
            SELECT count(*),
                   count(*) FILTER (WHERE NOT ({self._clave_no_nula('s')})),
                   count(DISTINCT ({clave_cols})) FILTER (WHERE {self._clave_no_nula('s')})
            FROM {stg} s
        """)[0]

        cambia = " OR ".join(f"t.{qi(c)} IS DISTINCT FROM u.{qi(c)}" for c in self.editables) or "FALSE"
        a_insertar, existentes, con_cambios = ejecutar(self.conexion, f"""
            SELECT count(*) FILTER (WHERE t.ctid IS NULL AND p.ctid IS NOT NULL),
                   count(*) FILTER (WHERE t.ctid IS NOT NULL),
                   count(*) FILTER (WHERE t.ctid IS NOT NULL AND ({cambia}))
            FROM {unicas} u
            LEFT JOIN {padre} p ON p.{clave_padre} = u.{fk}
            LEFT JOIN {tabla} t ON {self._misma_clave('t', 'u')}
        """)[0]

        huerfanas = ejecutar(self.conexion, f"""
            SELECT s.{fk}::text, count(*)
            FROM {stg} s LEFT JOIN {padre} p ON p.{clave_padre} = s.{fk}
            WHERE p.ctid IS NULL
            GROUP BY 1 ORDER BY 1
        """)

        rutas_invalidas = []
        if self.tabla == config.TABLA_FOTOS and config.COLUMNA_RUTA_FOTO in self.columnas:
            ruta = qi(config.COLUMNA_RUTA_FOTO)
            rutas_invalidas = [f[0] for f in ejecutar(self.conexion, f"""
                SELECT {ruta} FROM {stg}
                WHERE {ruta} IS NOT NULL AND {ruta} !~ {ql(config.PATRON_RUTA_FOTO)}
                ORDER BY 1 LIMIT {MAX_LISTADO}
            """)]

        con_clave = int(total) - int(sin_clave)
        return AnalisisHija(
            tabla=self.tabla,
            total=int(total),
            a_insertar=int(a_insertar),
            existentes=int(existentes),
            con_cambios=int(con_cambios),
            sin_clave=int(sin_clave),
            repetidas=con_clave - int(distintas),
            huerfanas=[(f[0], int(f[1])) for f in huerfanas],
            rutas_invalidas=rutas_invalidas,
            avisos=list(self.avisos),
        )

    # ── Insert / update ─────────────────────────────────────────────────────
    def aplicar(self):
        """Una sola sentencia (atómica). Las huérfanas quedan afuera por el INNER JOIN."""
        tabla = tabla_calificada(self.tabla)
        padre = tabla_calificada(config.TABLA)
        fk, clave_padre = qi(self.fk), qi(config.CLAVE)
        cols = ", ".join(qi(c) for c in self.columnas)
        cols_u = ", ".join(f"u.{qi(c)}" for c in self.columnas)
        devolver = self.pk + [c for c in self.clave if c not in self.pk]
        ret = ", ".join(f"t.{qi(c)}::text" for c in devolver)
        unicas = self._staging_sin_repetidos()

        insertar = f"""
            INSERT INTO {tabla} AS t ({cols})
            SELECT {cols_u}
            FROM {unicas} u
            INNER JOIN {padre} p ON p.{clave_padre} = u.{fk}
            WHERE NOT EXISTS (SELECT 1 FROM {tabla} x WHERE {self._misma_clave('x', 'u')})
            RETURNING 'i'::text, {ret}
        """
        if self.editables:
            set_ = ", ".join(f"{qi(c)} = u.{qi(c)}" for c in self.editables)
            destino = ", ".join(f"t.{qi(c)}" for c in self.editables)
            origen = ", ".join(f"u.{qi(c)}" for c in self.editables)
            sql = f"""
                WITH actualizadas AS (
                    UPDATE {tabla} AS t SET {set_}
                    FROM {unicas} u
                    WHERE {self._misma_clave('t', 'u')} AND ({destino}) IS DISTINCT FROM ({origen})
                    RETURNING 'u'::text, {ret}
                ), insertadas AS ({insertar})
                SELECT * FROM actualizadas UNION ALL SELECT * FROM insertadas
            """
        else:
            sql = insertar

        filas = ejecutar(self.conexion, sql)
        resultado = ResultadoHija(self.tabla, pk=self.pk)
        for fila in filas:
            if fila[0] == "i":
                resultado.insertadas.append(dict(zip(devolver, fila[1:])))
            else:
                resultado.actualizadas += 1
        return resultado
