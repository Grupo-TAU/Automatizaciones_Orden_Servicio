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

# ─── QgsSettings ─────────────────────────────────────────────────────────────
# Nunca se guarda la contraseña acá: va cifrada en QgsAuthManager (authcfg) o
# queda en la conexión existente de QGIS que el usuario eligió.
SETTINGS_PREFIJO = "inspecciones/campo/"
MODO_EXISTENTE = "existente"    # usa una conexión PostGIS del Navegador de QGIS
MODO_PROPIA = "propia"          # host/puerto/base en settings + credenciales en authcfg

NOMBRE_AUTHCFG = "Inspecciones - PostGIS"
