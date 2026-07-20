"""
Copia las imágenes asociadas a una OS (capa fotos_os, campo ruta_relativa)
hacia una carpeta destino elegida por el usuario. El destino no está
hardcodeado (a diferencia de RAIZ_IMAGENES) porque varía según el contrato
al que pertenece la OS.
"""

import os
import shutil

from .capa_utils import buscar_rutas_fotos_os


def copiar_imagenes_os(numero_os, carpeta_destino):
    """
    Copia a carpeta_destino cada archivo listado en ruta_relativa para las
    fotos de numero_os. Devuelve (copiadas, faltantes):
      - copiadas: rutas origen copiadas con éxito.
      - faltantes: rutas origen que no existen en disco (no se copian).
    """
    rutas = buscar_rutas_fotos_os(numero_os)

    copiadas = []
    faltantes = []
    for ruta_origen in rutas:
        ruta_origen = str(ruta_origen).strip()
        if not ruta_origen or not os.path.isfile(ruta_origen):
            faltantes.append(ruta_origen)
            continue
        ruta_destino = os.path.join(carpeta_destino, os.path.basename(ruta_origen))
        shutil.copy2(ruta_origen, ruta_destino)
        copiadas.append(ruta_origen)

    return copiadas, faltantes
