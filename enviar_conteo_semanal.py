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


def armar_reporte() -> tuple[str, str]:
    """(texto plano, html) del mismo conteo."""
    sn = _cargar_sacar_numeros()
    resultado = sn.contar(leer_filas_gpkg())
    fecha = datetime.now().strftime("%d/%m/%Y")
    texto = sn.formatear_reporte(resultado, f"Inspecciones por Etapa y Contrato - {fecha}")
    return texto, armar_html(sn, resultado, fecha)


# Paleta del mail. Los estilos van inline y con bgcolor porque Outlook y Gmail
# ignoran <style> y los fondos que no vengan como atributo.
_FUENTE = "'Segoe UI',Arial,Helvetica,sans-serif"
_ROJO_OSCURO = "#7b1e1e"     # titulo, encabezado, fila TOTAL
_ROJO_TOTAL = "#a93226"      # encabezado de la columna TOTAL
_FONDO_TOTAL = "#fbeaea"     # celdas de la columna TOTAL
_FONDO_ZEBRA = "#faf4f4"
_BORDE = "#e6d3d3"
_TEXTO = "#2c1c1c"
_APAGADO = "#9a8a8a"


def _html_tabla(etiquetas_fila, etiquetas_col, celda, encabezado_fila="Categor&iacute;a") -> str:
    """Tabla con columna y fila TOTAL; celda(fila, columna) -> int."""
    def th(contenido, align, fondo):
        return (
            f'<th align="{align}" bgcolor="{fondo}" style="background:{fondo};color:#ffffff;'
            f'padding:9px 14px;font-size:12px;font-weight:600;white-space:nowrap;'
            f'font-family:{_FUENTE};">{contenido}</th>'
        )

    def td(contenido, align, fondo, *, borde, negrita=False, color=_TEXTO, tam=13):
        return (
            f'<td align="{align}" bgcolor="{fondo}" style="background:{fondo};border-top:{borde};'
            f'padding:9px 14px;font-size:{tam}px;font-weight:{700 if negrita else 400};'
            f'color:{color};font-family:{_FUENTE};">{contenido}</td>'
        )

    filas = [
        "<tr>"
        + th(encabezado_fila, "left", _ROJO_OSCURO)
        + "".join(th(escape(c), "right", _ROJO_OSCURO) for c in etiquetas_col)
        + th("Total", "right", _ROJO_TOTAL)
        + "</tr>"
    ]
    totales = [0] * len(etiquetas_col)
    borde = f"1px solid {_BORDE}"
    for i, fila in enumerate(etiquetas_fila):
        fondo = "#ffffff" if i % 2 == 0 else _FONDO_ZEBRA
        valores = [celda(fila, col) for col in etiquetas_col]
        totales = [t + v for t, v in zip(totales, valores)]
        celdas = [td(escape(fila), "left", fondo, borde=borde, negrita=True, color=_ROJO_OSCURO)]
        celdas += [
            td(v, "right", fondo, borde=borde, color=_TEXTO if v else _APAGADO) for v in valores
        ]
        celdas.append(td(sum(valores), "right", _FONDO_TOTAL, borde=borde))
        filas.append("<tr>" + "".join(celdas) + "</tr>")

    borde = f"2px solid {_ROJO_OSCURO}"
    celdas = [td("TOTAL", "left", "#ffffff", borde=borde, negrita=True, color=_ROJO_OSCURO, tam=14)]
    celdas += [td(t, "right", "#ffffff", borde=borde, negrita=True, tam=14) for t in totales]
    celdas.append(td(sum(totales), "right", _FONDO_TOTAL, borde=borde, negrita=True, tam=14))
    filas.append("<tr>" + "".join(celdas) + "</tr>")

    return (
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="border:1px solid {_BORDE};border-collapse:collapse;">{"".join(filas)}</table>'
    )


def armar_html(sn, resultado, fecha: str) -> str:
    contratos, etapas = sn._ejes(resultado)
    tabla_contrato = _html_tabla(
        etapas, contratos,
        lambda etapa, contrato: resultado.conteo.get((contrato, etapa), 0),
        encabezado_fila="Etapa",
    )
    etapas_zona = sn._etapas_presentes(resultado.conteo_zona, lambda clave: clave[1])
    tabla_zona = _html_tabla(
        etapas_zona, sn.ZONAS,
        lambda etapa, zona: resultado.conteo_zona.get((zona, etapa), 0),
        encabezado_fila="Etapa",
    )

    def titulo(texto, subtexto, margen_sup):
        return (
            f'<p style="margin:{margen_sup}px 0 2px 0;font-size:20px;font-weight:700;'
            f'color:{_ROJO_OSCURO};font-family:{_FUENTE};">{texto}</p>'
            f'<p style="margin:0 0 16px 0;font-size:13px;color:{_APAGADO};'
            f'font-family:{_FUENTE};">{subtexto}</p>'
        )

    aviso = ""
    sin_clasificar = sum(
        n for (z, _), n in resultado.conteo_zona.items() if z == sn.ZONA_SIN_CLASIFICAR
    )
    if resultado.total_zona and sin_clasificar == resultado.total_zona:
        aviso = (
            f'<p style="margin:12px 0 0 0;font-size:12px;color:{_APAGADO};font-family:{_FUENTE};">'
            f"Ninguna OS de {escape(sn.CONTRATO_POR_ZONA)} tiene {sn.CAMPO_DENTRO_ZONA} cargado "
            "(puede ser que la fuente no traiga esa columna).</p>"
        )

    return (
        '<!DOCTYPE html><html><body style="margin:0;padding:0;background:#ffffff;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
        '<tr><td style="padding:20px;">'
        + titulo("Conteo de OS", f"Inspecciones por Etapa y Contrato &middot; al {fecha}", 0)
        + tabla_contrato
        + titulo(
            escape(sn.CONTRATO_POR_ZONA),
            f"por Etapa y {sn.CAMPO_DENTRO_ZONA} &middot; {resultado.total_zona} OS",
            28,
        )
        + tabla_zona
        + aviso
        + "</td></tr></table></body></html>"
    )


def _config() -> configparser.SectionProxy:
    if not RUTA_INI.is_file():
        raise FileNotFoundError(
            f"Falta {RUTA_INI.name}. Copiar {RUTA_INI.name}.example y completarlo."
        )
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(RUTA_INI, encoding="utf-8")
    return parser["smtp"]


def enviar(reporte: str, html: str) -> None:
    cfg = _config()
    destinatarios = [d.strip() for d in cfg["destinatarios"].split(",") if d.strip()]

    mensaje = EmailMessage()
    mensaje["Subject"] = f"Conteo de OS - {datetime.now():%d/%m/%Y}"
    mensaje["From"] = cfg["remitente"]
    mensaje["To"] = ", ".join(destinatarios)
    mensaje.set_content(reporte)
    mensaje.add_alternative(html, subtype="html")

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
    parser.add_argument("--html", metavar="ARCHIVO", help="ademas guarda el HTML del mail para verlo en el navegador")
    args = parser.parse_args()

    logging.basicConfig(
        filename=RUTA_LOG, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        reporte, html = armar_reporte()
        if args.html:
            Path(args.html).write_text(html, encoding="utf-8")
        if args.probar:
            print(reporte)
            return 0
        enviar(reporte, html)
        logging.info("Enviado")
        return 0
    except Exception:
        # Desde el Programador de tareas nadie mira la consola: el log es la unica pista.
        logging.exception("Fallo el envio")
        raise


if __name__ == "__main__":
    sys.exit(main())
