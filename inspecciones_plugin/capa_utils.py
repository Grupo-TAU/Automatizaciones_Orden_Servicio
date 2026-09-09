"""
Acceso a capas del proyecto y escritura del feature de OS.
Sin dependencias de UI: reutilizable desde la consola o desde tests.
"""

from qgis.core import (
    QgsProject,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsCsException,
    QgsSpatialIndex,
)
from PyQt5.QtCore import QVariant, QDate

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────
# TODO: si esto varía entre las 6 PCs, migrar a QgsSettings en vez de constante.
RAIZ_IMAGENES = r"G:\Unidades compartidas\GRUPO TAU\INTENDENCIA DE MONTEVIDEO\SOMS\IMAGENES_OS"

CAPA_OS = "inspecciones_OS"
CAPA_PADRONES = "padrones"
CAMPO_PADRON = "padron"

# Clasificación automática por zona: el punto de la OS se marca según caiga
# dentro o fuera de CAPA_ZONA. CAMPO_DENTRO_ZONA guarda "Si" cuando cae DENTRO.
CAPA_ZONA = "zona8_delimitada"
CAMPO_DENTRO_ZONA = "Dentro_Zona"

CAPA_FOTOS_OS = "fotos_OS"
CAMPO_FOTOS_OS_N_OS = "N°_OS"
CAMPO_FOTOS_OS_RUTA = "ruta_relativa"
# CAMPO_FOTOS_OS_RUTA es relativa a esta carpeta.
CARPETA_ORIGEN_FOTOS = r"C:\Proyectos-QGisCloud\QField\cloud\inspecciones_os"

CAMPOS_PASO1 = [
    ("N°_OS", QVariant.String),
    ("Ubicación", QVariant.String),
    ("Fecha_Ingreso", QVariant.Date),
    ("Descripción", QVariant.String),
    ("N_Problema", QVariant.String),
    ("Contrato", QVariant.String),
    ("N° Trabajo", QVariant.String),
    ("Tipo", QVariant.String),
    ("Etapa", QVariant.String),
    ("Restringir", QVariant.String),
]


def obtener_capa(nombre):
    """Busca la capa por nombre, o None si no está en el proyecto.

    mapLayersByName() distingue mayúsculas y los nombres de capa del proyecto no
    siempre respetan el mismo casing, así que si el match exacto falla se
    recorren todas comparando en minúsculas.
    """
    capas = QgsProject.instance().mapLayersByName(nombre)
    if capas:
        return capas[0]

    objetivo = nombre.casefold()
    for capa in QgsProject.instance().mapLayers().values():
        if capa.name().casefold() == objetivo:
            return capa
    return None


def buscar_punto_padron(numero_padron):
    """
    Busca en CAPA_PADRONES el feature cuyo CAMPO_PADRON coincide con
    numero_padron y devuelve el centroide (QgsPointXY) reproyectado al CRS
    del proyecto. Devuelve None si no hay 0 o más de 1 coincidencia, o si
    capa/campo no existen (el usuario deberá hacer clic manualmente).
    """
    capa = obtener_capa(CAPA_PADRONES)
    if capa is None:
        return None

    idx = capa.fields().indexOf(CAMPO_PADRON)
    if idx < 0:
        return None

    numero_padron = str(numero_padron).strip()
    coincidencias = [
        f for f in capa.getFeatures()
        if str(f[CAMPO_PADRON]).strip() == numero_padron
    ]
    if len(coincidencias) != 1:
        return None

    geom = coincidencias[0].geometry()
    if geom is None or geom.isEmpty():
        return None

    punto = geom.centroid().asPoint()
    crs_proyecto = QgsProject.instance().crs()
    if capa.crs() != crs_proyecto:
        transformador = QgsCoordinateTransform(capa.crs(), crs_proyecto, QgsProject.instance())
        punto = transformador.transform(punto)

    return punto


def buscar_rutas_fotos_os(numero_os):
    """
    Devuelve la lista de rutas (campo CAMPO_FOTOS_OS_RUTA, relativa a
    CARPETA_ORIGEN_FOTOS) de las fotos asociadas a numero_os en la capa
    CAPA_FOTOS_OS.
    """
    capa = obtener_capa(CAPA_FOTOS_OS)
    if capa is None:
        raise ValueError(f"No se encontró la capa '{CAPA_FOTOS_OS}' en el proyecto.")

    idx = capa.fields().indexOf(CAMPO_FOTOS_OS_N_OS)
    if idx < 0:
        raise ValueError(f"La capa '{CAPA_FOTOS_OS}' no tiene el campo '{CAMPO_FOTOS_OS_N_OS}'.")

    numero_os = str(numero_os).strip()
    return [
        f[CAMPO_FOTOS_OS_RUTA]
        for f in capa.getFeatures()
        if str(f[CAMPO_FOTOS_OS_N_OS]).strip() == numero_os and f[CAMPO_FOTOS_OS_RUTA]
    ]


# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICACIÓN POR ZONA
# ─────────────────────────────────────────────────────────────────────────────
def construir_clasificador(capa_zonas, crs_puntos):
    """Devuelve una closure `fuera_zona(geom_punto) -> bool | None`.

    OJO CON LA POLARIDAD — la closure contesta "¿está FUERA?":
        True  -> el punto no toca ninguna zona (está FUERA)
        False -> el punto cae DENTRO de alguna zona
        None  -> indeterminado (sin geometría, o falló la reproyección)

    El campo CAMPO_DENTRO_ZONA guarda lo contrario ("Si" = dentro), así que en
    el punto de escritura hay que invertir. Es el error más fácil de cometer acá.

    Las geometrías de la zona y el índice espacial se arman UNA sola vez, al
    construir: si se llama a esto por cada punto se relee la capa entera cada vez.
    """
    geoms = {f.id(): f.geometry() for f in capa_zonas.getFeatures()}
    indice = QgsSpatialIndex(capa_zonas.getFeatures())
    transformador = QgsCoordinateTransform(
        crs_puntos, capa_zonas.crs(), QgsProject.instance()
    )

    def fuera_zona(geom_punto):
        if geom_punto is None or geom_punto.isEmpty():
            return None

        # Copia: transform() muta la geometría in place y la del feature no se toca.
        g = QgsGeometry(geom_punto)
        try:
            g.transform(transformador)
        except QgsCsException:
            return None

        # El índice filtra por bounding box (barato); la intersección real se
        # chequea solo contra los candidatos que sobreviven ese filtro.
        for fid in indice.intersects(g.boundingBox()):
            geom_zona = geoms.get(fid)
            if geom_zona is not None and geom_zona.intersects(g):
                return False
        return True

    return fuera_zona


def construir_clasificador_zona():
    """Clasificador listo para CAPA_ZONA, o None si esa capa no está cargada.

    Es el que hay que usar en cargas de varias OS seguidas: se construye una vez
    y se pasa por parámetro a cada alta.
    """
    capa = obtener_capa(CAPA_ZONA)
    if capa is None:
        return None
    return construir_clasificador(capa, QgsProject.instance().crs())


def clasificar_fuera_zona(geom_punto):
    """Atajo para clasificar UN punto suelto. Devuelve True fuera / False dentro
    / None sin clasificar (incluido el caso de que CAPA_ZONA no esté cargada).

    Construye el clasificador al vuelo, así que para varios puntos usar
    construir_clasificador_zona() una vez y reusarlo.
    """
    clasificador = construir_clasificador_zona()
    if clasificador is None:
        return None
    return clasificador(geom_punto)


def _valor_dentro_zona(capa, idx_campo, dentro):
    """Adapta el booleano al tipo real del campo.

    `dentro` ya viene invertido: True = el punto cae DENTRO de la zona.
    El campo puede estar tipado como bool, numérico o texto según el origen de
    datos, así que no se asume texto.
    """
    tipo = capa.fields().at(idx_campo).type()
    if tipo == QVariant.Bool:
        return dentro
    if tipo in (QVariant.Int, QVariant.LongLong, QVariant.Double):
        return int(dentro)
    return "Si" if dentro else "No"


# leer_dentro_zona vive en sacar_numeros, que no depende de qgis y ya es el
# módulo que interpreta valores de campo. Se re-exporta acá porque este es el
# módulo de la zona: así el conteo y la escritura usan el mismo criterio, sin
# dos normalizaciones que se puedan desincronizar.
from .sacar_numeros import leer_dentro_zona  # noqa: E402,F401


# ─────────────────────────────────────────────────────────────────────────────
# ALTA DEL FEATURE
# ─────────────────────────────────────────────────────────────────────────────
def agregar_feature_os(datos, punto_xy, fuera_zona=None):
    """Da de alta la OS en CAPA_OS y clasifica el punto contra CAPA_ZONA.

    fuera_zona: clasificador ya construido (ver construir_clasificador_zona).
    Conviene pasarlo cuando se cargan varias OS seguidas; si es None, la
    clasificación se resuelve al vuelo para este punto solo.

    Devuelve el resultado de la clasificación con la polaridad del clasificador
    (True fuera / False dentro / None sin clasificar), para que la UI lo muestre.
    """
    capa = obtener_capa(CAPA_OS)
    if capa is None:
        raise ValueError(f"No se encontró la capa '{CAPA_OS}' en el proyecto.")

    if not capa.isEditable():
        capa.startEditing()

    feat = QgsFeature(capa.fields())
    geom = QgsGeometry.fromPointXY(punto_xy)
    feat.setGeometry(geom)

    indices_seteados = set()

    # CAMPO_DENTRO_ZONA no se pide en el formulario: sale de la intersección.
    fuera = clasificar_fuera_zona(geom) if fuera_zona is None else fuera_zona(geom)
    idx_dz = capa.fields().lookupField(CAMPO_DENTRO_ZONA)
    if idx_dz >= 0:
        if fuera is not None:
            # Acá se cruza la polaridad: el clasificador contesta "¿está fuera?"
            # y el campo guarda "dentro". De ahí el not.
            feat.setAttribute(idx_dz, _valor_dentro_zona(capa, idx_dz, not fuera))
        # Se marca como seteado en los dos casos. Si la clasificación quedó
        # indeterminada el campo tiene que quedar NULL, y sin esto la expresión
        # por defecto de la capa (si la hubiera) lo llenaría igual: "sin
        # clasificar" no es lo mismo que "fuera".
        indices_seteados.add(idx_dz)

    for nombre_campo, tipo in CAMPOS_PASO1:
        idx = capa.fields().indexOf(nombre_campo)
        if idx >= 0 and nombre_campo in datos:
            valor = datos[nombre_campo]
            if tipo == QVariant.Date and isinstance(valor, str) and valor:
                valor = QDate.fromString(valor, "dd/MM/yyyy")
            feat.setAttribute(idx, valor)
            indices_seteados.add(idx)

    # Evaluar expresiones por defecto de la capa para campos no seteados
    # (ej: "N° Trabajo" con expresión maximum("N° Trabajo") + 1)
    for idx in range(capa.fields().count()):
        if idx not in indices_seteados:
            defn = capa.defaultValueDefinition(idx)
            if defn.isValid():
                feat.setAttribute(idx, capa.defaultValue(idx))

    capa.addFeature(feat)
    capa.commitChanges()
    capa.triggerRepaint()
    return fuera
