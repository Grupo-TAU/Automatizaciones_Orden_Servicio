"""
Copia las fotos de una OS desde la carpeta de QField hacia la carpeta
destino en Drive, y marca la OS como procesada en el GeoPackage.

Pensado para invocarse como acción de QGIS sobre la capa inspecciones_OS
(acción de tipo "Ejecutar un comando", corre como proceso aparte, sin
acceso a PyQGIS):
    python "C:/ruta/al/repo/copiar_fotos_os_test.py" --os [% "N°_OS" %]

Sin argumentos, abre una ventana tkinter para elegir la OS a mano.
"""

import argparse
import datetime
import glob
import os
import shutil
import sqlite3
import sys

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN — CONFIRMAR contra el GeoPackage real antes de usar
# ─────────────────────────────────────────────────────────────────────────────
TABLA_OS = "inspecciones_nuevas_OS"              # CONFIRMAR: nombre exacto de la tabla en el GeoPackage
CAMPO_N_OS = "N°_OS"                      # CONFIRMAR: nombre exacto del campo (incluye el carácter °)
CAMPO_FECHA_COPIA = "fecha_copia_fotos"   # CONFIRMAR: columna a crear/actualizar en TABLA_OS
CAMPO_CONTRATO = "Contrato"                # CONFIRMAR
CAMPO_N_TRABAJO = "N° Trabajo"             # CONFIRMAR
CAMPO_UBICACION = "Ubicación"              # CONFIRMAR
CAMPO_N_PROBLEMA = "N_Problema"            # CONFIRMAR

TABLA_FOTOS = "fotos_OS"                  # CONFIRMAR: tabla con una fila por foto
CAMPO_FOTOS_N_OS = "N°_OS"                # CONFIRMAR: FK hacia la OS en TABLA_FOTOS
CAMPO_RUTA_RELATIVA = "ruta_relativa"     # CONFIRMAR: campo con la ruta relativa del archivo

RUTA_GPKG_DEFAULT = r"C:\Proyectos-QGisCloud\QField\cloud\inspecciones_os\inspecciones_OS.gpkg"
CARPETA_ORIGEN_FOTOS = r"C:\Proyectos-QGisCloud\QField\cloud\inspecciones_OS"  # ruta_relativa ya incluye DCIM\FOTOS_OS

# mod_spatialite: lo necesitan los triggers del GeoPackage (mantienen el índice
# espacial R-tree) incluso al actualizar una columna no geométrica. Se busca
# automáticamente porque la versión de QGIS instalada varía entre PCs.
PATRON_MOD_SPATIALITE = r"C:\Program Files\QGIS *\bin\mod_spatialite.dll"

# Bases del destino en Drive — según la expresión QGIS existente, difiere por Contrato.
# RUTA_BASE_DLR incluye el año actual (calculado al momento de correr, no al importar el módulo).
RUTA_BASE_DLR = r"G:\Unidades compartidas\GRUPO TAU\INTENDENCIA DE MONTEVIDEO\01 - INSPECCIONES IM\02 - EN PROCESO\00 - INSPECCIONES"
RUTA_BASE_ZONA8 = r"G:\Unidades compartidas\GRUPO TAU\INTENDENCIA DE MONTEVIDEO\02 - ZONA 8\02 - EN PROCESO\05 - SUR\0 - NUEVO SUR"


def _ruta_gpkg_default():
    return RUTA_GPKG_DEFAULT


def _cargar_mod_spatialite(con):
    """
    Carga mod_spatialite en la conexión para que los triggers del GeoPackage
    (ST_IsEmpty y similares, usados para mantener el índice R-tree) no fallen
    con "no such function" al hacer UPDATE/ALTER TABLE.
    """
    candidatos = glob.glob(PATRON_MOD_SPATIALITE)
    if not candidatos:
        raise RuntimeError(
            f"No se encontró mod_spatialite.dll (buscado en '{PATRON_MOD_SPATIALITE}'). "
            "Ajustá PATRON_MOD_SPATIALITE a la instalación de QGIS de esta PC."
        )
    ruta_dll = candidatos[0]

    carpeta_bin = os.path.dirname(ruta_dll)
    os.environ["PATH"] = carpeta_bin + os.pathsep + os.environ.get("PATH", "")

    con.enable_load_extension(True)
    try:
        con.load_extension(ruta_dll)
    finally:
        con.enable_load_extension(False)


def _asegurar_columna_fecha(con):
    columnas = {fila[1] for fila in con.execute(f'PRAGMA table_info("{TABLA_OS}")').fetchall()}
    if CAMPO_FECHA_COPIA not in columnas:
        con.execute(f'ALTER TABLE "{TABLA_OS}" ADD COLUMN "{CAMPO_FECHA_COPIA}" TEXT')


def _obtener_rutas_fotos(con, n_os):
    cur = con.execute(
        f'SELECT "{CAMPO_RUTA_RELATIVA}" FROM "{TABLA_FOTOS}" WHERE "{CAMPO_FOTOS_N_OS}" = ?',
        (n_os,),
    )
    return [fila[0] for fila in cur.fetchall() if fila[0]]


def _marcar_procesada(con, n_os):
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    con.execute(
        f'UPDATE "{TABLA_OS}" SET "{CAMPO_FECHA_COPIA}" = ? WHERE "{CAMPO_N_OS}" = ?',
        (timestamp, n_os),
    )


def _obtener_datos_os(con, n_os):
    """Devuelve (contrato, n_trabajo, ubicacion, n_problema) para n_os, o None si no existe."""
    cur = con.execute(
        f'SELECT "{CAMPO_CONTRATO}", "{CAMPO_N_TRABAJO}", "{CAMPO_UBICACION}", "{CAMPO_N_PROBLEMA}" '
        f'FROM "{TABLA_OS}" WHERE "{CAMPO_N_OS}" = ?',
        (n_os,),
    )
    return cur.fetchone()


def calcular_carpeta_destino(contrato, n_trabajo, ubicacion, n_problema) -> str:
    """
    Replica la expresión QGIS existente para la carpeta destino en Drive,
    que difiere según el Contrato de la OS.
    """
    if contrato == "DLR":
        nombre = f"{(n_trabajo or '').strip()} - {(ubicacion or '').strip().replace(':', '')}"
        return os.path.join(RUTA_BASE_DLR, str(datetime.datetime.now().year), nombre)
    return os.path.join(RUTA_BASE_ZONA8, str(n_problema), "2- Inspección")


def copiar_fotos_de_os(n_os: str, ruta_gpkg: str, carpeta_destino: str = None) -> dict:
    """
    Copia las fotos de la OS n_os desde CARPETA_ORIGEN_FOTOS hacia
    carpeta_destino (calculado con calcular_carpeta_destino si no se
    especifica), y marca la OS como procesada en el GeoPackage si el
    copiado fue exitoso (al menos una foto copiada y ningún error).
    Devuelve un resumen: {'n_os', 'copiadas', 'errores', 'ok'}.
    """
    resumen = {"n_os": n_os, "copiadas": 0, "errores": 0, "ok": False}

    try:
        con = sqlite3.connect(ruta_gpkg, timeout=10)
    except sqlite3.OperationalError as e:
        print(f"No se pudo abrir el GeoPackage '{ruta_gpkg}' (¿bloqueado?): {e}", file=sys.stderr)
        return resumen

    try:
        _cargar_mod_spatialite(con)
    except Exception as e:
        print(f"No se pudo cargar mod_spatialite: {e}", file=sys.stderr)
        con.close()
        return resumen

    try:
        _asegurar_columna_fecha(con)
        con.commit()

        rutas = _obtener_rutas_fotos(con, n_os)
        if not rutas:
            print(f"No se encontraron fotos para la OS {n_os} en '{TABLA_FOTOS}'.", file=sys.stderr)
            return resumen

        destino = carpeta_destino
        if destino is None:
            datos_os = _obtener_datos_os(con, n_os)
            if datos_os is None:
                print(f"No se encontró la OS {n_os} en '{TABLA_OS}'; no se pudo calcular el destino.", file=sys.stderr)
                return resumen
            destino = calcular_carpeta_destino(*datos_os)

        os.makedirs(destino, exist_ok=True)

        for ruta_relativa in rutas:
            ruta_origen = os.path.normpath(os.path.join(CARPETA_ORIGEN_FOTOS, ruta_relativa))
            try:
                if not os.path.isfile(ruta_origen):
                    raise FileNotFoundError(ruta_origen)
                shutil.copy2(ruta_origen, os.path.join(destino, os.path.basename(ruta_origen)))
                resumen["copiadas"] += 1
            except Exception as e:
                print(f"Error copiando '{ruta_origen}': {e}", file=sys.stderr)
                resumen["errores"] += 1

        resumen["ok"] = resumen["copiadas"] > 0 and resumen["errores"] == 0
        if resumen["ok"]:
            try:
                _marcar_procesada(con, n_os)
                con.commit()
            except sqlite3.OperationalError as e:
                resumen["ok"] = False
                print(
                    f"Fotos copiadas pero no se pudo marcar '{CAMPO_FECHA_COPIA}' "
                    f"(¿el GeoPackage está abierto/en edición en QGIS?): {e}",
                    file=sys.stderr,
                )

    except sqlite3.OperationalError as e:
        print(f"Error de base de datos sobre '{ruta_gpkg}' (¿GeoPackage bloqueado?): {e}", file=sys.stderr)
    finally:
        con.close()

    return resumen


def _modo_cli(args):
    resumen = copiar_fotos_de_os(args.os, args.gpkg)
    print(resumen)
    sys.exit(0 if resumen["ok"] else 1)


def _modo_interactivo(ruta_gpkg):
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()

    n_os = simpledialog.askstring("Copiar fotos de OS", "N° de OS a procesar:")
    if not n_os:
        return

    resumen = copiar_fotos_de_os(n_os.strip(), ruta_gpkg)

    if resumen["ok"]:
        messagebox.showinfo(
            "Copia completa",
            f"OS {resumen['n_os']}: {resumen['copiadas']} foto(s) copiada(s).",
        )
    else:
        messagebox.showerror(
            "Copia con errores",
            f"OS {resumen['n_os']}: {resumen['copiadas']} copiada(s), "
            f"{resumen['errores']} error(es).\nRevisá la consola para el detalle.",
        )


def main():
    parser = argparse.ArgumentParser(description="Copia las fotos de una OS y marca el GeoPackage.")
    parser.add_argument("--os", dest="os", help="N° de OS a procesar (modo CLI).")
    parser.add_argument("--gpkg", dest="gpkg", default=None, help="Ruta al GeoPackage (default: junto al script).")
    args = parser.parse_args()

    if args.gpkg is None:
        args.gpkg = _ruta_gpkg_default()

    if args.os is not None:
        _modo_cli(args)
    else:
        _modo_interactivo(args.gpkg)


if __name__ == "__main__":
    main()
