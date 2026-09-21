"""
Envia por mail el conteo de OS por Etapa y Contrato (las dos tablas de
inspecciones_plugin/sacar_numeros.py), leyendo directo del GeoPackage.

No necesita QGIS: el GeoPackage es SQLite, asi que se lee con sqlite3 y se
reutiliza la clasificacion de sacar_numeros para que los numeros coincidan con
los del plugin.

Pensado para correr desatendido desde el Programador de tareas de Windows
(cada lunes 12:30). La configuracion del mail vive en envio_conteo.ini, que no
se sube al repo; hay un envio_conteo.ini.example para copiar.

    python enviar_conteo_semanal.py            # cuenta y envia
    python enviar_conteo_semanal.py --probar   # cuenta e imprime, sin enviar
"""

from __future__ import annotations

import argparse
import configparser
import importlib.util
import logging
import smtplib
import sqlite3
import sys
from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RUTA_INI = AQUI / "envio_conteo.ini"
RUTA_LOG = AQUI / "envio_conteo.log"

RUTA_GPKG = r"C:\Proyectos-QGisCloud\QField\cloud\inspecciones_os\inspecciones_OS.gpkg"
# Es la tabla que la capa "inspecciones_OS" del proyecto QGIS tiene cargada.
TABLA_OS = "inspecciones_nuevas_OS"


def _cargar_sacar_numeros():
    """Se carga por ruta y no como inspecciones_plugin.sacar_numeros: importar el
    paquete ejecuta su __init__, que trae qgis, y fuera de QGIS no esta."""
    ruta = AQUI / "inspecciones_plugin" / "sacar_numeros.py"
    spec = importlib.util.spec_from_file_location("sacar_numeros", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["sacar_numeros"] = modulo  # NamedTuple lo necesita registrado
    spec.loader.exec_module(modulo)
    return modulo


def leer_filas_gpkg(ruta: str = RUTA_GPKG, tabla: str = TABLA_OS) -> list[tuple[str, str, str]]:
    """Ternas (contrato, etapa, dentro_zona). Solo lectura: si QGIS o QField
    Sync tienen el archivo abierto, esto no lo bloquea ni lo modifica."""
    if not Path(ruta).is_file():
        raise FileNotFoundError(f"No existe el GeoPackage: {ruta}")
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=30)
    try:
        cursor = con.execute(f'SELECT "Contrato", "Etapa", "Dentro_Zona" FROM "{tabla}"')
        return [tuple("" if v is None else v for v in fila) for fila in cursor]
    finally:
        con.close()


def armar_reporte() -> str:
    sn = _cargar_sacar_numeros()
    resultado = sn.contar(leer_filas_gpkg())
    fecha = datetime.now().strftime("%d/%m/%Y")
    return sn.formatear_reporte(resultado, f"Inspecciones por Etapa y Contrato - {fecha}")


def _config() -> configparser.SectionProxy:
    if not RUTA_INI.is_file():
        raise FileNotFoundError(
            f"Falta {RUTA_INI.name}. Copiar {RUTA_INI.name}.example y completarlo."
        )
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(RUTA_INI, encoding="utf-8")
    return parser["smtp"]


def enviar(reporte: str) -> None:
    cfg = _config()
    destinatarios = [d.strip() for d in cfg["destinatarios"].split(",") if d.strip()]

    mensaje = EmailMessage()
    mensaje["Subject"] = f"Conteo de OS - {datetime.now():%d/%m/%Y}"
    mensaje["From"] = cfg["remitente"]
    mensaje["To"] = ", ".join(destinatarios)
    mensaje.set_content(reporte)
    # Las tablas estan alineadas con espacios: en HTML sin <pre> se desarman.
    mensaje.add_alternative(
        f'<pre style="font-family: Consolas, monospace; font-size: 13px">{escape(reporte)}</pre>',
        subtype="html",
    )

    servidor, puerto = cfg["servidor"], cfg.getint("puerto", 587)
    if puerto == 465:
        smtp = smtplib.SMTP_SSL(servidor, puerto, timeout=60)
    else:
        smtp = smtplib.SMTP(servidor, puerto, timeout=60)
        smtp.starttls()
    with smtp:
        smtp.login(cfg["usuario"], cfg["clave"])
        smtp.send_message(mensaje)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--probar", action="store_true", help="imprime el reporte sin enviar el mail")
    args = parser.parse_args()

    logging.basicConfig(
        filename=RUTA_LOG, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        reporte = armar_reporte()
        if args.probar:
            print(reporte)
            return 0
        enviar(reporte)
        logging.info("Enviado")
        return 0
    except Exception:
        # Desde el Programador de tareas nadie mira la consola: el log es la unica pista.
        logging.exception("Fallo el envio")
        raise


if __name__ == "__main__":
    sys.exit(main())
