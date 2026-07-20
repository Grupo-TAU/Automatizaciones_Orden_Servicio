"""
Regenera Lanzamientos/registrar_os_plugin.zip a partir de la carpeta
registrar_os_plugin/, y sincroniza la version en plugins.xml con la
declarada en metadata.txt.

Correr despues de cada edicion al plugin, antes de pushear:
    python generar_lanzamiento.py
"""

import os
import re
import zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
CARPETA_PLUGIN = os.path.join(RAIZ, "registrar_os_plugin")
CARPETA_LANZAMIENTOS = os.path.join(RAIZ, "Lanzamientos")
ZIP_DESTINO = os.path.join(CARPETA_LANZAMIENTOS, "registrar_os_plugin.zip")
PLUGINS_XML = os.path.join(RAIZ, "plugins.xml")
METADATA_TXT = os.path.join(CARPETA_PLUGIN, "metadata.txt")

EXCLUIR_ARCHIVOS = {"README_MIGRACION.md"}
EXCLUIR_EXTENSIONES = (".pyc",)
EXCLUIR_CARPETAS = {"__pycache__"}


def leer_version_metadata():
    with open(METADATA_TXT, encoding="utf-8") as f:
        for linea in f:
            m = re.match(r"version\s*=\s*(.+)", linea.strip())
            if m:
                return m.group(1).strip()
    raise ValueError(f"No se encontró 'version=' en {METADATA_TXT}")


def generar_zip():
    os.makedirs(CARPETA_LANZAMIENTOS, exist_ok=True)
    with zipfile.ZipFile(ZIP_DESTINO, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(CARPETA_PLUGIN):
            dirs[:] = [d for d in dirs if d not in EXCLUIR_CARPETAS]
            for nombre in files:
                if nombre in EXCLUIR_ARCHIVOS or nombre.endswith(EXCLUIR_EXTENSIONES):
                    continue
                ruta_completa = os.path.join(root, nombre)
                ruta_en_zip = os.path.join(
                    "registrar_os_plugin", os.path.relpath(ruta_completa, CARPETA_PLUGIN)
                )
                zf.write(ruta_completa, ruta_en_zip)
    print(f"Generado {ZIP_DESTINO}")


def sincronizar_version_plugins_xml(version):
    with open(PLUGINS_XML, encoding="utf-8") as f:
        contenido = f.read()

    nuevo, n1 = re.subn(
        r'(<pyqgis_plugin name="[^"]+" version=")[^"]+(")',
        r"\g<1>" + version + r"\g<2>",
        contenido,
    )
    nuevo, n2 = re.subn(r"(<version>)[^<]+(</version>)", r"\g<1>" + version + r"\g<2>", nuevo)

    if n1 == 0 or n2 == 0:
        raise ValueError("No se pudo encontrar la version en plugins.xml para actualizar.")

    if nuevo != contenido:
        with open(PLUGINS_XML, "w", encoding="utf-8") as f:
            f.write(nuevo)
        print(f"plugins.xml actualizado a version {version}")
    else:
        print(f"plugins.xml ya está en version {version}")


if __name__ == "__main__":
    version = leer_version_metadata()
    generar_zip()
    sincronizar_version_plugins_xml(version)
