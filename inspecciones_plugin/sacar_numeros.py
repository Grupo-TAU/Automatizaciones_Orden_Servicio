"""
Conteo de OS de inspecciones por Etapa y Contrato.

Arma dos tablas:
    1. Una fila por Etapa (Pendiente, Pendiente_Visual, Realizada, No_Realizada,
       Limpieza, Finalizada) y una columna por Contrato (DLR, Baderery-Giberol)
       mas el TOTAL.
    2. Debajo, solo las OS de Baderery-Giberol abiertas por Etapa (filas) y
       Dentro_Zona (columnas: Dentro / Fuera / Sin clasificar).

La misma matriz se puede sacar de dos fuentes, y las dos comparten las mismas
funciones de clasificacion, asi que si los numeros no cierran la diferencia
esta en los datos, nunca en el criterio de conteo:
    1. La planilla que se baja del sistema (CSV o XLSX; del XLSX se usa la
       primera hoja salvo que se pida otra).
    2. La capa inspecciones_OS cargada en QGIS.

Este modulo es el motor de conteo del plugin: no tiene interfaz. La ventana
que lo usa es dialogo_conteo.DialogoConteo, y desde la consola de Python de
QGIS se puede llamar directo:

    from inspecciones_plugin import sacar_numeros
    sacar_numeros.resumen()                              # la capa del proyecto
    sacar_numeros.resumen(expresion="Restringir IS NULL")
    sacar_numeros.resumen(detalle=True)                  # abre cada fila/columna en los valores crudos
    sacar_numeros.imprimir_reporte(sacar_numeros.contar_planilla("inspecciones.xlsx"))

Sin dependencias: csv, zipfile y ElementTree son de la biblioteca estandar
(el xlsx se lee a mano, sin openpyxl), que en el Python de QGIS no esta.
"""

from __future__ import annotations

import csv
import io
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACION
# ─────────────────────────────────────────────────────────────────────────────
CAMPO_CONTRATO = "Contrato"
CAMPO_ETAPA = "Etapa"
# Dentro_Zona lo completa solo el alta de la OS (ver capa_utils). Es opcional:
# si la fuente no lo trae, esas OS quedan como "Sin clasificar".
CAMPO_DENTRO_ZONA = "Dentro_Zona"
CAPA_QGIS = "inspecciones_OS"

# Columnas de la matriz, en el orden en que se imprimen. Cada entrada es
# (nombre a mostrar, otras escrituras que tienen que caer en esa columna).
# El match es EXACTO sobre el valor normalizado (minusculas, sin acentos y con
# guiones / guiones bajos convertidos en espacios), no por subcadena: asi
# "Pendiente" no se come a "Pendiente_Visual".
CONTRATOS: list[tuple[str, tuple[str, ...]]] = [
    ("DLR", ()),
    ("Baderery-Giberol", ("Baderey-Giberol", "Giberol")),
]

# Filas de la matriz, en el orden en que se imprimen.
ETAPAS: list[tuple[str, tuple[str, ...]]] = [
    ("Pendiente", ()),
    ("Pendiente_Visual", ()),
    ("Realizada", ()),
    ("No_Realizada", ()),
    ("Limpieza", ()),
    ("Finalizada", ()),
]

# Todo lo que no matchea cae en OTROS, y los valores vacios en SIN_DATO. Las
# dos salen como fila / columna aparte solo si tienen algo, para que los
# subtotales sumen siempre exactamente el TOTAL y nada quede escondido.
OTROS = "Otros"
SIN_DATO = "(sin dato)"

# Segunda tabla: un solo contrato, abierto por Dentro_Zona. Las tres columnas se
# muestran siempre — "Sin clasificar" no es un caso raro que convenga esconder,
# es justamente lo que hay que ver.
CONTRATO_POR_ZONA = "Baderery-Giberol"
ZONA_DENTRO = "Dentro"
ZONA_FUERA = "Fuera"
ZONA_SIN_CLASIFICAR = "Sin clasificar"
ZONAS = [ZONA_DENTRO, ZONA_FUERA, ZONA_SIN_CLASIFICAR]


# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICACION (la unica fuente de verdad, compartida por las dos fuentes)
# ─────────────────────────────────────────────────────────────────────────────
def normalizar(texto) -> str:
    """Minusculas, sin acentos, con guiones y guiones bajos pasados a espacio y
    los espacios colapsados: 'Pendiente_Visual', 'pendiente visual' y
    'Pendiente  Visual' tienen que caer todos en la misma fila."""
    if texto is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    for caracter in "_-/":
        s = s.replace(caracter, " ")
    return " ".join(s.casefold().split())


def _mapa(definiciones: list[tuple[str, tuple[str, ...]]]) -> dict[str, str]:
    """valor normalizado -> nombre a mostrar. Se arma una sola vez al importar,
    no en cada fila."""
    mapa: dict[str, str] = {}
    for nombre, alias in definiciones:
        for escritura in (nombre,) + tuple(alias):
            mapa[normalizar(escritura)] = nombre
    return mapa


_MAPA_CONTRATOS = _mapa(CONTRATOS)
_MAPA_ETAPAS = _mapa(ETAPAS)


def _clasificar(valor, mapa: dict[str, str]) -> str:
    v = normalizar(valor)
    if not v:
        return SIN_DATO
    return mapa.get(v, OTROS)


def clasificar_contrato(valor) -> str:
    return _clasificar(valor, _MAPA_CONTRATOS)


def clasificar_etapa(valor) -> str:
    return _clasificar(valor, _MAPA_ETAPAS)


# Los datos historicos de Dentro_Zona pueden venir como texto, bool o entero
# mezclados, segun como se hayan cargado.
_TEXTOS_DENTRO = {"si", "s", "true", "t", "1", "dentro"}
_TEXTOS_FUERA = {"no", "n", "false", "f", "0", "fuera"}


def leer_dentro_zona(valor):
    """Interpreta un valor de CAMPO_DENTRO_ZONA: True dentro / False fuera /
    None sin clasificar (NULL, vacio o algo que no se reconoce).

    Un NULL NO es un "fuera": son cosas distintas, y contarlos juntos infla el
    numero de OS fuera de zona. Por eso nunca se compara contra "Si" directo.
    """
    # QVariant sin importar PyQt5: este modulo es stdlib puro a proposito, asi
    # que se lo reconoce por su interfaz en vez de por su tipo.
    if hasattr(valor, "isNull") and hasattr(valor, "value"):
        if valor.isNull():
            return None
        valor = valor.value()
    if valor is None:
        return None
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)

    texto = str(valor).strip().casefold()
    if texto in _TEXTOS_DENTRO:
        return True
    if texto in _TEXTOS_FUERA:
        return False
    return None


def clasificar_zona(valor) -> str:
    """Nombre de columna de la segunda tabla para un valor de Dentro_Zona."""
    dentro = leer_dentro_zona(valor)
    if dentro is None:
        return ZONA_SIN_CLASIFICAR
    return ZONA_DENTRO if dentro else ZONA_FUERA


class Resultado(NamedTuple):
    conteo: Counter          # (contrato, etapa) -> cantidad
    conteo_zona: Counter     # (zona, etapa) -> cantidad, solo CONTRATO_POR_ZONA
    crudos: defaultdict      # (campo, nombre a mostrar) -> Counter de los valores originales

    @property
    def total(self) -> int:
        return sum(self.conteo.values())

    @property
    def total_zona(self) -> int:
        return sum(self.conteo_zona.values())


def contar(filas) -> Resultado:
    """filas: iterable de ternas (contrato, etapa, dentro_zona), venga de la
    planilla o de QGIS. dentro_zona puede ser "" si la fuente no trae el campo.
    """
    conteo: Counter = Counter()
    conteo_zona: Counter = Counter()
    crudos: defaultdict = defaultdict(Counter)
    for contrato, etapa, zona in filas:
        c = clasificar_contrato(contrato)
        e = clasificar_etapa(etapa)
        conteo[(c, e)] += 1
        crudos[(CAMPO_CONTRATO, c)][str(contrato).strip() or "(vacio)"] += 1
        crudos[(CAMPO_ETAPA, e)][str(etapa).strip() or "(vacio)"] += 1

        # La segunda tabla es de un contrato solo: el resto no se cuenta ahi.
        if c == CONTRATO_POR_ZONA:
            z = clasificar_zona(zona)
            conteo_zona[(z, e)] += 1
            crudos[(CAMPO_DENTRO_ZONA, z)][str(zona).strip() or "(vacio)"] += 1
    return Resultado(conteo, conteo_zona, crudos)


# ─────────────────────────────────────────────────────────────────────────────
# FUENTE 1: la planilla (CSV o XLSX)
# ─────────────────────────────────────────────────────────────────────────────
def _leer_texto(ruta: Path) -> str:
    """Los CSV del sistema vienen a veces en UTF-8 y a veces en cp1252; leerlos
    con el encoding equivocado rompe los acentos y descoloca la clasificacion."""
    crudo = Path(ruta).read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return crudo.decode(encoding)
        except UnicodeDecodeError:
            continue
    return crudo.decode("latin-1", errors="replace")


def _detectar_delimitador(muestra: str) -> str:
    try:
        return csv.Sniffer().sniff(muestra, delimiters=",;\t|").delimiter
    except csv.Error:
        # El Sniffer falla con encabezados raros o de una sola columna.
        return max(",;\t|", key=muestra.count)


# El xlsx se lee con zipfile + ElementTree en vez de openpyxl: la consola de
# QGIS no trae openpyxl instalado y la fuente 2 se corre justamente ahi.
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _indice_de_columna(ref: str) -> int:
    """'B7' -> 1. Las celdas vacias no se escriben en el XML, asi que la
    posicion hay que sacarla de la referencia y no del orden de aparicion."""
    n = 0
    for caracter in ref:
        if caracter.isalpha():
            n = n * 26 + (ord(caracter.upper()) - 64)
    return n - 1


def _texto_de(elemento) -> str:
    return "".join(nodo.text or "" for nodo in elemento.iter(f"{_NS}t"))


def leer_filas_xlsx(ruta, hoja=None) -> list[list[str]]:
    """
    Devuelve las filas de una hoja como listas de strings. hoja puede ser el
    nombre o el indice; None = la primera, que es de donde salen los calculos.
    Las fechas quedan como numero de serie de Excel: no se usan para contar.
    """
    with zipfile.ZipFile(ruta) as z:
        compartidas = []
        if "xl/sharedStrings.xml" in z.namelist():
            raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
            compartidas = [_texto_de(si) for si in raiz.findall(f"{_NS}si")]

        libro = ET.fromstring(z.read("xl/workbook.xml"))
        hojas = libro.find(f"{_NS}sheets").findall(f"{_NS}sheet")
        nombres = ", ".join(h.get("name") for h in hojas)

        if hoja is None:
            elegida = hojas[0]
        elif isinstance(hoja, int):
            elegida = hojas[hoja]
        else:
            objetivo = normalizar(hoja)
            elegida = next((h for h in hojas if normalizar(h.get("name")) == objetivo), None)
            if elegida is None:
                raise ValueError(f"El archivo no tiene la hoja {hoja!r}. Hojas: {nombres}")

        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        destinos = {r.get("Id"): r.get("Target") for r in rels.findall(f"{_NS_PKG}Relationship")}
        destino = destinos[elegida.get(f"{_NS_REL}id")].lstrip("/")
        raiz = ET.fromstring(z.read(destino if destino.startswith("xl/") else f"xl/{destino}"))

    filas = []
    for fila_el in raiz.iter(f"{_NS}row"):
        celdas: dict[int, str] = {}
        for celda in fila_el.findall(f"{_NS}c"):
            tipo = celda.get("t")
            if tipo == "inlineStr":
                bloque = celda.find(f"{_NS}is")
                valor = _texto_de(bloque) if bloque is not None else ""
            else:
                v = celda.find(f"{_NS}v")
                valor = (v.text or "") if v is not None else ""
                if tipo == "s" and valor:
                    valor = compartidas[int(valor)]
            if valor != "":
                celdas[_indice_de_columna(celda.get("r") or "")] = valor
        filas.append([celdas.get(i, "") for i in range(max(celdas) + 1)] if celdas else [])
    return filas


def _filas_de_xlsx(ruta, requeridos, opcionales, hoja=None) -> list[tuple[str, ...]]:
    filas = leer_filas_xlsx(ruta, hoja)

    # El encabezado no siempre es la primera fila (puede haber un titulo arriba),
    # asi que se busca la primera fila que tenga todas las columnas requeridas.
    for n, fila in enumerate(filas):
        posiciones = {normalizar(celda): i for i, celda in enumerate(fila) if celda}
        if all(normalizar(c) in posiciones for c in requeridos):
            # -1 marca una columna opcional que la planilla no trae; abajo sale "".
            indices = [posiciones[normalizar(c)] for c in requeridos]
            indices += [posiciones.get(normalizar(c), -1) for c in opcionales]
            return [
                tuple(f[i] if 0 <= i < len(f) else "" for i in indices)
                for f in filas[n + 1:]
                if any(celda.strip() for celda in f)   # saltear las filas vacias del final
            ]

    primera = ", ".join(c for c in (filas[0] if filas else []) if c)
    pedidas = ", ".join(repr(c) for c in requeridos)
    raise ValueError(f"La hoja no tiene las columnas {pedidas}. Primera fila: {primera or '(vacia)'}")


def _filas_de_csv(ruta, requeridos, opcionales) -> list[tuple[str, ...]]:
    texto = _leer_texto(ruta)
    lector = csv.DictReader(io.StringIO(texto), delimiter=_detectar_delimitador(texto[:4096]))
    encabezados = lector.fieldnames or []

    def buscar(campo):
        objetivo = normalizar(campo)
        return next((h for h in encabezados if normalizar(h) == objetivo), None)

    columnas = []
    for campo in requeridos:
        columna = buscar(campo)
        if columna is None:
            raise ValueError(
                f"El CSV no tiene la columna '{campo}'.\n"
                f"Columnas encontradas: {', '.join(encabezados) or '(ninguna)'}"
            )
        columnas.append(columna)
    # None = columna opcional ausente; esas filas salen como "".
    columnas += [buscar(campo) for campo in opcionales]

    return [
        tuple((fila.get(c) or "") if c else "" for c in columnas)
        for fila in lector
    ]


def leer_filas(
    ruta,
    campo_contrato: str = CAMPO_CONTRATO,
    campo_etapa: str = CAMPO_ETAPA,
    campo_zona: str = CAMPO_DENTRO_ZONA,
    hoja=None,
) -> list[tuple[str, str, str]]:
    """Ternas (contrato, etapa, dentro_zona). Contrato y Etapa son obligatorias;
    si la planilla no trae la de zona, esa posicion viene vacia."""
    requeridos = (campo_contrato, campo_etapa)
    opcionales = (campo_zona,)
    if Path(ruta).suffix.lower() in (".xlsx", ".xlsm"):
        return _filas_de_xlsx(ruta, requeridos, opcionales, hoja)
    return _filas_de_csv(ruta, requeridos, opcionales)


def contar_planilla(
    ruta,
    campo_contrato: str = CAMPO_CONTRATO,
    campo_etapa: str = CAMPO_ETAPA,
    campo_zona: str = CAMPO_DENTRO_ZONA,
    hoja=None,
) -> Resultado:
    return contar(leer_filas(ruta, campo_contrato, campo_etapa, campo_zona, hoja))


# ─────────────────────────────────────────────────────────────────────────────
# FUENTE 2: la capa de QGIS
# ─────────────────────────────────────────────────────────────────────────────
def contar_capa_qgis(
    nombre_capa: str = CAPA_QGIS,
    campo_contrato: str = CAMPO_CONTRATO,
    campo_etapa: str = CAMPO_ETAPA,
    campo_zona: str = CAMPO_DENTRO_ZONA,
    expresion: str | None = None,
) -> Resultado:
    """
    Cuenta los features de la capa cargada en el proyecto. Respeta el filtro de
    la capa (subset string) porque usa getFeatures(); si la capa esta filtrada
    en el panel de capas, los numeros van a ser los del filtro.

    expresion: filtro adicional opcional, en sintaxis de QGIS
    (ej: "Etapa = 'Pendiente'").
    """
    from qgis.core import QgsProject, QgsFeatureRequest
    from PyQt5.QtCore import QVariant

    capas = QgsProject.instance().mapLayersByName(nombre_capa)
    if not capas:
        # mapLayersByName distingue mayusculas y los nombres del proyecto no
        # siempre respetan el mismo casing.
        objetivo = nombre_capa.casefold()
        capas = [
            c for c in QgsProject.instance().mapLayers().values()
            if c.name().casefold() == objetivo
        ]
    if not capas:
        disponibles = ", ".join(sorted(c.name() for c in QgsProject.instance().mapLayers().values()))
        raise ValueError(f"No se encontro la capa '{nombre_capa}'.\nCapas del proyecto: {disponibles}")

    capa = capas[0]
    indices = []
    for campo in (campo_contrato, campo_etapa):
        idx = capa.fields().lookupField(campo)
        if idx < 0:
            raise ValueError(
                f"La capa '{capa.name()}' no tiene el campo '{campo}'.\n"
                f"Campos: {', '.join(capa.fields().names())}"
            )
        indices.append(idx)

    # Dentro_Zona es opcional: una capa vieja puede no tenerlo todavia, y eso no
    # tiene por que romper el conteo principal. -1 = ausente, se lee como "".
    indices.append(capa.fields().lookupField(campo_zona))

    solicitud = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)
    if expresion:
        # Con filtro no se recortan los atributos: la expresion puede mirar
        # otros campos y quedaria sin poder evaluarlos.
        solicitud.setFilterExpression(expresion)
    else:
        solicitud.setSubsetOfAttributes([i for i in indices if i >= 0])

    def _valor(feature, idx):
        if idx < 0:
            return ""
        valor = feature[idx]
        if valor is None or (isinstance(valor, QVariant) and valor.isNull()):
            return ""
        return valor

    filas = [
        tuple(_valor(feature, idx) for idx in indices)
        for feature in capa.getFeatures(solicitud)
    ]
    return contar(filas)


# ─────────────────────────────────────────────────────────────────────────────
# SALIDA
# ─────────────────────────────────────────────────────────────────────────────
def _etapas_presentes(conteo: Counter, sacar_etapa) -> list[str]:
    """Las etapas fijas siempre, y Otros / (sin dato) solo si tienen algo."""
    con_datos = {sacar_etapa(clave) for clave, n in conteo.items() if n}
    return [n for n, _ in ETAPAS] + [x for x in (OTROS, SIN_DATO) if x in con_datos]


def _ejes(resultado: Resultado) -> tuple[list[str], list[str]]:
    """Columnas (contratos) y filas (etapas) de la tabla principal."""
    contratos_con_datos = {c for (c, _), n in resultado.conteo.items() if n}
    contratos = [n for n, _ in CONTRATOS] + [x for x in (OTROS, SIN_DATO) if x in contratos_con_datos]
    etapas = _etapas_presentes(resultado.conteo, lambda clave: clave[1])
    return contratos, etapas


# El formateo devuelve texto en vez de imprimir: las mismas tablas van a la
# consola de QGIS con imprimir_reporte() y al cuadro de texto del dialogo.
def _formatear_tabla(titulo, etiquetas_fila, etiquetas_col, celda) -> str:
    """Render generico de una tabla con fila y columna de TOTAL.

    celda(fila, columna) -> int. Las dos tablas se dibujan con esto para que no
    se despeguen los anchos ni el formato.
    """
    columnas = etiquetas_col + ["TOTAL"]
    ancho_fila = max(len(e) for e in etiquetas_fila + ["TOTAL"])
    anchos = [max(len(c), 7) for c in columnas]

    def _linea(etiqueta: str, valores: list[int]) -> str:
        celdas = "".join(f"  {v:>{a}}" for v, a in zip(valores, anchos))
        return f"{etiqueta:<{ancho_fila}}{celdas}"

    encabezado = f"{'':<{ancho_fila}}" + "".join(f"  {c:>{a}}" for c, a in zip(columnas, anchos))
    regla = "-" * len(encabezado)

    lineas = [titulo, "", encabezado, regla]
    totales = [0] * len(etiquetas_col)
    for fila in etiquetas_fila:
        valores = [celda(fila, col) for col in etiquetas_col]
        totales = [t + v for t, v in zip(totales, valores)]
        lineas.append(_linea(fila, valores + [sum(valores)]))
    lineas.append(regla)
    lineas.append(_linea("TOTAL", totales + [sum(totales)]))
    return "\n".join(lineas)


def formatear_matriz(resultado: Resultado, titulo: str = "Inspecciones por Etapa y Contrato") -> str:
    contratos, etapas = _ejes(resultado)
    return _formatear_tabla(
        titulo, etapas, contratos,
        lambda etapa, contrato: resultado.conteo.get((contrato, etapa), 0),
    )


def formatear_matriz_zona(resultado: Resultado, titulo: str | None = None) -> str:
    """Segunda tabla: solo CONTRATO_POR_ZONA, por Etapa y Dentro_Zona."""
    if titulo is None:
        titulo = f"{CONTRATO_POR_ZONA} por Etapa y {CAMPO_DENTRO_ZONA}"

    etapas = _etapas_presentes(resultado.conteo_zona, lambda clave: clave[1])
    texto = _formatear_tabla(
        titulo, etapas, ZONAS,
        lambda etapa, zona: resultado.conteo_zona.get((zona, etapa), 0),
    )

    # Si TODO cayo en "Sin clasificar" lo mas probable es que la fuente no traiga
    # el campo, no que ninguna OS este clasificada. Decirlo evita leer mal la tabla.
    sin_clasificar = sum(
        n for (z, _), n in resultado.conteo_zona.items() if z == ZONA_SIN_CLASIFICAR
    )
    if resultado.total_zona and sin_clasificar == resultado.total_zona:
        texto += (
            f"\n\nNinguna OS de {CONTRATO_POR_ZONA} tiene {CAMPO_DENTRO_ZONA} cargado "
            "(puede ser que la fuente no traiga esa columna)."
        )
    return texto


def formatear_reporte(resultado: Resultado, titulo: str = "Inspecciones por Etapa y Contrato") -> str:
    """Las dos tablas, una debajo de la otra."""
    return formatear_matriz(resultado, titulo) + "\n\n\n" + formatear_matriz_zona(resultado)


def formatear_detalle(resultado: Resultado, titulo: str = "Valores crudos") -> str:
    """Abre cada columna y cada fila en los valores tal cual vienen en los datos.
    Sirve para auditar que 'Otros' no se este comiendo algo que deberia estar
    clasificado (un 'Pendiente Visual' escrito distinto, por ejemplo)."""
    ejes = [
        (CAMPO_CONTRATO, [n for n, _ in CONTRATOS] + [OTROS, SIN_DATO]),
        (CAMPO_ETAPA, [n for n, _ in ETAPAS] + [OTROS, SIN_DATO]),
        (CAMPO_DENTRO_ZONA, ZONAS),
    ]
    lineas = [titulo]
    for campo, nombres in ejes:
        lineas.append(f"\n  {campo}")
        for nombre in nombres:
            contador = resultado.crudos.get((campo, nombre))
            if not contador:
                continue
            lineas.append(f"    {nombre} ({sum(contador.values())})")
            for valor, n in contador.most_common():
                lineas.append(f"      {n:>5}  {valor}")
    return "\n".join(lineas)


def imprimir_matriz(resultado: Resultado, titulo: str = "Inspecciones por Etapa y Contrato") -> None:
    print(f"\n{formatear_matriz(resultado, titulo)}")


def imprimir_reporte(resultado: Resultado, titulo: str = "Inspecciones por Etapa y Contrato") -> None:
    print(f"\n{formatear_reporte(resultado, titulo)}")


def imprimir_detalle(resultado: Resultado, titulo: str = "Valores crudos") -> None:
    print(f"\n{formatear_detalle(resultado, titulo)}")


def resumen(
    nombre_capa: str = CAPA_QGIS,
    campo_contrato: str = CAMPO_CONTRATO,
    campo_etapa: str = CAMPO_ETAPA,
    campo_zona: str = CAMPO_DENTRO_ZONA,
    expresion: str | None = None,
    detalle: bool = False,
) -> Resultado:
    """Cuenta la capa del proyecto y la imprime. Para usar desde la consola de
    Python de QGIS, que es donde la capa esta disponible."""
    resultado = contar_capa_qgis(nombre_capa, campo_contrato, campo_etapa, campo_zona, expresion)
    titulo = f"Capa '{nombre_capa}'" + (f" filtrada por {expresion!r}" if expresion else "")
    imprimir_reporte(resultado, titulo)
    if detalle:
        imprimir_detalle(resultado)
    return resultado
