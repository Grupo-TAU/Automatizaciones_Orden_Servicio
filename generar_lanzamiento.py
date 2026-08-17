"""
Publica una nueva versión del plugin registrar_os_plugin.

metadata.txt es la única fuente de verdad de la versión (y de las versiones
mínima/máxima de QGIS). Este script deriva plugins.xml de ahí — no edites
plugins.xml a mano.

Uso, después de cada edición al plugin y antes de pushear:
    python generar_lanzamiento.py --lanzamiento

Hace todo el ciclo:
  1. Empaqueta registrar_os_plugin/ en Lanzamientos/registrar_os_plugin.zip,
     con la carpeta del plugin en la raíz del zip (formato que espera QGIS).
  2. Escribe el zip con nombre fijo (sin número de versión: el download_url
     de plugins.xml es una URL estática).
  3. Reescribe version / qgis_minimum_version / qgis_maximum_version en
     plugins.xml a partir de metadata.txt.
  4. Verifica que el download_url de plugins.xml apunte al zip recién escrito.
  5. Imprime los comandos de git que faltan (los usuarios bajan del repo
     remoto, no de tu disco).
"""

import argparse
import os
import re
import sys
import zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
CARPETA_PLUGIN = os.path.join(RAIZ, "registrar_os_plugin")
NOMBRE_CARPETA_PLUGIN = os.path.basename(CARPETA_PLUGIN)
CARPETA_LANZAMIENTOS = os.path.join(RAIZ, "Lanzamientos")
ZIP_DESTINO = os.path.join(CARPETA_LANZAMIENTOS, "registrar_os_plugin.zip")
PLUGINS_XML = os.path.join(RAIZ, "plugins.xml")
METADATA_TXT = os.path.join(CARPETA_PLUGIN, "metadata.txt")

EXCLUIR_ARCHIVOS = {"README_MIGRACION.md", "Thumbs.db", ".DS_Store"}
EXCLUIR_EXTENSIONES = (".pyc", ".pyo")
EXCLUIR_CARPETAS = {"__pycache__", ".git"}
EXCLUIR_SUFIJOS = ("~",)

# Paquetes propios que el plugin importa desde FUERA de registrar_os_plugin/
# (un "core" compartido, por ejemplo). QGIS solo copia la carpeta del plugin
# al perfil del usuario, así que tienen que viajar vendorizados adentro.
# Hoy el plugin no depende de ninguno; si se agrega uno, sumar acá el nombre
# de la subcarpeta vendorizada (ej: "core") para que se verifique al empaquetar.
PAQUETES_VENDORIZADOS = []


def leer_metadata():
    """Lee version / qgisMinimumVersion / qgisMaximumVersion de metadata.txt."""
    claves = ("version", "qgisMinimumVersion", "qgisMaximumVersion")
    valores = {}
    with open(METADATA_TXT, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            for clave in claves:
                m = re.match(rf"{clave}\s*=\s*(.*)", linea)
                if m:
                    valores[clave] = m.group(1).strip()
    if "version" not in valores or not valores["version"]:
        raise ValueError(f"No se encontró 'version=' en {METADATA_TXT}")
    return valores


def _incluir_archivo(nombre):
    if nombre in EXCLUIR_ARCHIVOS:
        return False
    if nombre.endswith(EXCLUIR_EXTENSIONES):
        return False
    if nombre.endswith(EXCLUIR_SUFIJOS):
        return False
    return True


def empaquetar_zip():
    """Escribe el zip y devuelve el set de rutas (dentro del zip) que debería contener."""
    os.makedirs(CARPETA_LANZAMIENTOS, exist_ok=True)
    esperados = set()
    with zipfile.ZipFile(ZIP_DESTINO, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(CARPETA_PLUGIN):
            dirs[:] = [d for d in dirs if d not in EXCLUIR_CARPETAS]
            for nombre in files:
                if not _incluir_archivo(nombre):
                    continue
                ruta_completa = os.path.join(root, nombre)
                ruta_en_zip = os.path.join(
                    NOMBRE_CARPETA_PLUGIN, os.path.relpath(ruta_completa, CARPETA_PLUGIN)
                ).replace(os.sep, "/")
                zf.write(ruta_completa, ruta_en_zip)
                esperados.add(ruta_en_zip)
    print(f"Generado {ZIP_DESTINO} ({len(esperados)} archivos)")
    return esperados


def verificar_zip_completo(esperados):
    """Reabre el zip y confirma que su contenido coincide con lo que se escribió."""
    with zipfile.ZipFile(ZIP_DESTINO) as zf:
        reales = set(zf.namelist())

    if reales != esperados:
        faltantes = esperados - reales
        sobrantes = reales - esperados
        detalle = []
        if faltantes:
            detalle.append(f"faltan: {sorted(faltantes)}")
        if sobrantes:
            detalle.append(f"sobran: {sorted(sobrantes)}")
        raise ValueError(f"El zip generado no coincide con lo esperado ({'; '.join(detalle)}).")

    obligatorios = {
        f"{NOMBRE_CARPETA_PLUGIN}/__init__.py",
        f"{NOMBRE_CARPETA_PLUGIN}/metadata.txt",
    }
    faltan = obligatorios - reales
    if faltan:
        raise ValueError(f"Faltan archivos obligatorios en el zip: {sorted(faltan)}")

    print("Verificación de contenido del zip: OK")


def verificar_paquetes_vendorizados(esperados):
    for paquete in PAQUETES_VENDORIZADOS:
        init_esperado = f"{NOMBRE_CARPETA_PLUGIN}/{paquete}/__init__.py"
        if init_esperado not in esperados:
            raise ValueError(
                f"El paquete vendorizado '{paquete}' no tiene __init__.py dentro de "
                f"{NOMBRE_CARPETA_PLUGIN}/ — sin eso QGIS no puede importarlo."
            )
    if PAQUETES_VENDORIZADOS:
        print(f"Paquetes vendorizados verificados: {PAQUETES_VENDORIZADOS}")


def reescribir_plugins_xml(metadata):
    """Sincroniza version / qgis_minimum_version / qgis_maximum_version desde metadata.txt."""
    if not os.path.isfile(PLUGINS_XML):
        raise FileNotFoundError(f"No se encontró {PLUGINS_XML}")

    with open(PLUGINS_XML, encoding="utf-8") as f:
        contenido = f.read()
    original = contenido

    version = metadata["version"]
    minima = metadata.get("qgisMinimumVersion")
    maxima = metadata.get("qgisMaximumVersion")

    contenido, n1 = re.subn(
        r'(<pyqgis_plugin name="[^"]+" version=")[^"]+(")',
        lambda m: m.group(1) + version + m.group(2),
        contenido,
    )
    contenido, n2 = re.subn(
        r"(<version>)[^<]+(</version>)", lambda m: m.group(1) + version + m.group(2), contenido
    )
    if n1 == 0 or n2 == 0:
        raise ValueError("No se encontró el atributo/elemento version en plugins.xml para actualizar.")

    if minima:
        if re.search(r"<qgis_minimum_version>", contenido):
            contenido, n3 = re.subn(
                r"(<qgis_minimum_version>)[^<]+(</qgis_minimum_version>)",
                lambda m: m.group(1) + minima + m.group(2),
                contenido,
            )
        else:
            contenido, n3 = re.subn(
                r"(<version>[^<]+</version>)",
                lambda m: m.group(1) + f"\n    <qgis_minimum_version>{minima}</qgis_minimum_version>",
                contenido,
                count=1,
            )
        if n3 == 0:
            raise ValueError("No se pudo sincronizar qgis_minimum_version en plugins.xml.")

    if maxima:
        if re.search(r"<qgis_maximum_version>", contenido):
            contenido, n4 = re.subn(
                r"(<qgis_maximum_version>)[^<]+(</qgis_maximum_version>)",
                lambda m: m.group(1) + maxima + m.group(2),
                contenido,
            )
        else:
            contenido, n4 = re.subn(
                r"(<qgis_minimum_version>[^<]+</qgis_minimum_version>)",
                lambda m: m.group(1) + f"\n    <qgis_maximum_version>{maxima}</qgis_maximum_version>",
                contenido,
                count=1,
            )
        if n4 == 0:
            raise ValueError("No se pudo sincronizar qgis_maximum_version en plugins.xml.")

    if contenido != original:
        with open(PLUGINS_XML, "w", encoding="utf-8") as f:
            f.write(contenido)
        print(f"plugins.xml actualizado (version={version}, qgis_minimum_version={minima}, qgis_maximum_version={maxima})")
    else:
        print(f"plugins.xml ya estaba sincronizado (version={version})")


def verificar_download_url():
    """Confirma que <download_url> en plugins.xml apunta al zip que se acaba de escribir."""
    with open(PLUGINS_XML, encoding="utf-8") as f:
        contenido = f.read()

    m = re.search(r"<download_url>([^<]+)</download_url>", contenido)
    if not m:
        raise ValueError("plugins.xml no tiene <download_url>.")
    url = m.group(1).strip()

    m2 = re.match(r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+/(.+)$", url)
    if not m2:
        raise ValueError(f"No se pudo interpretar download_url como URL de GitHub raw: {url}")
    ruta_url = os.path.normpath(m2.group(1))

    ruta_zip = os.path.normpath(os.path.relpath(ZIP_DESTINO, RAIZ))

    if ruta_url != ruta_zip:
        raise ValueError(
            f"El download_url de plugins.xml apunta a '{ruta_url}', pero el zip se "
            f"escribió en '{ruta_zip}'. Los usuarios van a bajar el archivo equivocado "
            "(o nada) — corregí uno de los dos antes de pushear."
        )
    print(f"download_url verificado: coincide con {ruta_zip}")


def imprimir_advertencias():
    print()
    print("Recordatorios:")
    print("  - Límite de 260 caracteres de ruta en Windows: si el perfil de QGIS del")
    print("    usuario queda en una ruta larga, los .py del plugin pueden no cargar")
    print("    (ModuleNotFoundError que no menciona el largo de ruta). Avisar antes de instalar.")
    print("  - Después de instalar hay que reiniciar QGIS (o desactivar/reactivar el plugin):")
    print("    Python no recarga módulos ya importados.")


def imprimir_comandos_git(version):
    ruta_zip_rel = os.path.relpath(ZIP_DESTINO, RAIZ)
    ruta_xml_rel = os.path.relpath(PLUGINS_XML, RAIZ)
    print()
    print("Los usuarios bajan del repositorio remoto, no de tu disco. Falta:")
    print(f'  git add "{ruta_zip_rel}" "{ruta_xml_rel}"')
    print(f'  git commit -m "Release {NOMBRE_CARPETA_PLUGIN} {version}"')
    print("  git push")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--lanzamiento",
        action="store_true",
        help="Corre el ciclo completo de publicación (empaquetar, sincronizar plugins.xml, verificar).",
    )
    args = parser.parse_args()

    if not args.lanzamiento:
        parser.print_help()
        sys.exit(1)

    try:
        metadata = leer_metadata()
        esperados = empaquetar_zip()
        verificar_zip_completo(esperados)
        verificar_paquetes_vendorizados(esperados)
        reescribir_plugins_xml(metadata)
        verificar_download_url()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    imprimir_advertencias()
    imprimir_comandos_git(metadata["version"])


if __name__ == "__main__":
    main()
