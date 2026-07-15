"""
Extracción de datos de OS desde el PDF del Sistema Único de Respuesta (IM).
Requiere pdfplumber (no viene con QGIS/OSGeo4W por defecto).
"""

import re


def pdfplumber_disponible():
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


def instalar_pdfplumber():
    """
    Instala pdfplumber en el intérprete de QGIS. Pensado para llamarse
    desde un botón de la UI, con confirmación previa del usuario
    (no se ejecuta automáticamente).
    Devuelve (ok, salida) con el resultado del proceso de pip.
    """
    import subprocess
    import sys
    import os

    target = os.path.join(sys.prefix, "Lib", "site-packages")
    resultado = subprocess.run(
        [
            os.path.join(sys.prefix, "python.exe"),
            "-m", "pip", "install", "pdfplumber", "--target", target,
        ],
        capture_output=True, text=True,
    )
    salida = (resultado.stdout or "") + (resultado.stderr or "")
    return resultado.returncode == 0, salida


def parsear_pdf_os(ruta_pdf):
    """
    Extrae los datos de la OS desde el PDF del Sistema Único de Respuesta (IM).
    Devuelve dict con los campos del formulario.
    Lanza ImportError con instrucciones si falta pdfplumber.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "Falta la librería pdfplumber.\n\n"
            "Instalala ejecutando en la consola de QGIS:\n"
            "  import subprocess, sys, os\n"
            "  target = os.path.join(sys.prefix, 'Lib', 'site-packages')\n"
            "  subprocess.call([os.path.join(sys.prefix, 'python.exe'),\n"
            "      '-m', 'pip', 'install', 'pdfplumber', '--target', target])"
        )

    datos = {}
    with pdfplumber.open(ruta_pdf) as pdf:
        texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

    # ── N°_OS ──────────────────────────────────────────────────────────
    m = re.search(r'Orden de Servicio\s+(\d+)', texto)
    if m:
        datos['orden_servicio'] = m.group(1)

    # ── Fecha_Ingreso — timestamp arriba a la derecha (antes del título,
    # presente en ambos tipos de OS) ───────────────────────────────
    m = re.search(r'(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}.*?Orden de Servicio', texto, re.DOTALL)
    if m:
        datos['fecha_ingreso'] = m.group(1)

    # ── Descripción — entre "Observación:" y "Problema Nº:" ───────────
    m = re.search(r'Observaci[oó]n:\s*(.+?)\s*Problema\s*N[°º]:', texto, re.DOTALL)
    if m:
        datos['descripcion'] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # ── Ubicación — entre "Ubicación:" y "Observación:" ───────────────
    m = re.search(r'Ubicaci[oó]n:\s*(.+?)\s*Observaci[oó]n:', texto, re.DOTALL)
    if m:
        ubic = re.sub(r'\s+', ' ', m.group(1)).strip()
        ubic = re.sub(r'N[°º]:\s*', 'Nº ', ubic)
        datos['ubicacion'] = ubic

        # ── Padrón — entre "[Padron: " y "]" dentro de la Ubicación ────
        m_pad = re.search(r'\[Padron:\s*(\d+)\]', ubic, re.IGNORECASE)
        if m_pad:
            datos['padron'] = m_pad.group(1)

    # ── N_Problema — entre "Problema N°:" y "Fecha Problema" ──────────
    m = re.search(r'Problema\s*N[°º]:\s*(.+?)\s*Fecha problema:', texto, re.DOTALL)
    if m:
        datos['n_problema'] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # ── Sector — entre "Sector:" y "Generada" ──────────────────────────
    m = re.search(r'Sector:\s*(.+?)\s*Generada', texto, re.DOTALL)
    if m:
        datos['sector'] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # ── Tipo — entre "Tipo:" y "Grupo:" ─────────────────────────────
    m = re.search(r'Tipo:\s*(.+?)\s*Grupo:', texto, re.DOTALL)
    if m:
        datos['tipo'] = re.sub(r'\s+', ' ', m.group(1)).strip()

    return datos
