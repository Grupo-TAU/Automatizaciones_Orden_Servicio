"""
Constantes del módulo de campo. Sin dependencias de QGIS.

Los NOMBRES de columna se validan contra la base en cada importación
(ver esquema.py): si alguno de COLUMNAS_EDITABLES no existe en la tabla real,
la importación se corta antes de tocar nada.
"""

ESQUEMA = "inspecciones_os"
TABLA = "inspecciones"
CLAVE = "n°_os"                 # UNIQUE en la tabla: es la clave del ON CONFLICT
COLUMNA_ETAPA = "etapa"

# Base del nombre de la tabla de staging. Se le agregan las iniciales del
# operario que importa (ej: _na) para que dos importaciones a la vez no se pisen.
STAGING_BASE = "inspecciones_staging"

SRID = 32721

# Nombre de la capa dentro del GeoPackage exportado.
CAPA_GPKG = "inspecciones"

# Lista blanca de columnas que el formulario de campo puede modificar. Son las
# ÚNICAS que van en el DO UPDATE SET: cualquier otra columna de la tabla
# (n_trabajo, contrato, descripción, fecha_ingreso, la clave, etc.) queda como
# solo lectura, incluidas las que se agreguen a la tabla en el futuro.
COLUMNAS_EDITABLES = [
    "etapa",
    "fecha_realizada",
    "operario",
    "material",
    "profundidad",
    "diametro_conexion",
    "sifón",
    "ubicación_colector",
    "limite_padron",
    "dimension_camara",
    "long_vereda",
    "estado_estructural",
    "estado_matenimiento",
    "limpieza",
    "long_inspeccionada",
    "introduccion",
    "conclusiones",
]

# La geometría NO se actualiza en filas existentes (el punto no se reubica en
# campo). En filas nuevas creadas en campo sí se inserta.
ACTUALIZAR_GEOMETRIA = False

# ─── Tablas hijas (FK hacia inspecciones."n°_os") ────────────────────────────
# Se importan SIEMPRE después de inspecciones. La columna FK se descubre del
# constraint en la base; COLUMNA_FK_HIJAS es solo el respaldo si no hay FK declarada.
COLUMNA_FK_HIJAS = "N°_OS"

# Por tabla:
#   capa_gpkg:    nombre de la capa dentro del GeoPackage de campo.
#   clave_dedupe: columnas que identifican una fila ya importada. El fid NO
#                 sirve: el del gpkg no es el de la base y cambia en cada ciclo.
#   conflicto:    "nada"       → solo se insertan las filas que no existen.
#                 "actualizar" → además se actualizan `editables` de las existentes.
#   editables:    columnas del UPDATE cuando conflicto = "actualizar".
#   exportar:     "vacia"      → el gpkg lleva la capa sin filas (solo se cargan nuevas en campo).
#                 "opcional"   → el diálogo ofrece incluir las filas de las OS exportadas.
TABLAS_HIJAS = {
    "fotos": {
        "capa_gpkg": "fotos",
        "clave_dedupe": ["ruta_relativa"],
        "conflicto": "nada",
        "editables": [],
        "exportar": "vacia",
    },
    "observaciones": {
        "capa_gpkg": "observaciones",
        # Requiere la columna uuid (ver migraciones/observaciones_uuid.sql); en
        # el proyecto de campo se completa sola con uuid() al crear la fila.
        "clave_dedupe": ["uuid"],
        "conflicto": "nada",
        "editables": [],
        "exportar": "opcional",
    },
}
COLUMNA_UUID = "uuid"

# ─── Archivos de fotos ───────────────────────────────────────────────────────
# ruta_relativa la escribe QField: DCIM/FOTOS_OS/<N°_OS>/<N°_OS>-<timestamp>.<ext>
TABLA_FOTOS = "fotos"
COLUMNA_RUTA_FOTO = "ruta_relativa"
PATRON_RUTA_FOTO = r"^DCIM/FOTOS_OS/[^/]+/[^/]+$"
DESTINO_CARPETA = "carpeta"     # carpeta compartida / unidad de red (\\servidor\... o Z:\...)
DESTINO_SSH = "ssh"             # ssh del sistema (OpenSSH de Windows) con clave, sin contraseña
RUTA_REMOTA_FOTOS = "/srv/backups/fotos/inspecciones_os"

# ─── QgsSettings ─────────────────────────────────────────────────────────────
# Nunca se guarda la contraseña acá: va cifrada en QgsAuthManager (authcfg) o
# queda en la conexión existente de QGIS que el usuario eligió.
SETTINGS_PREFIJO = "inspecciones/campo/"
MODO_EXISTENTE = "existente"    # usa una conexión PostGIS del Navegador de QGIS
MODO_PROPIA = "propia"          # host/puerto/base en settings + credenciales en authcfg

NOMBRE_AUTHCFG = "Inspecciones - PostGIS"
