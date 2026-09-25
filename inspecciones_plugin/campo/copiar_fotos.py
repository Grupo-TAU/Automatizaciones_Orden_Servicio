"""
Copia de los archivos físicos de fotos (la tabla fotos solo guarda la ruta).

Origen:  carpeta del GeoPackage importado + ruta_relativa
         (DCIM/FOTOS_OS/<N°_OS>/<N°_OS>-<timestamp>.<ext>, tal como la escribe QField).
Destino: /srv/backups/fotos/inspecciones_os/ + la MISMA ruta_relativa, así la
         columna de la base sigue siendo válida sin tocarla.

Dos formas de llegar al servidor (se elige en "Configurar conexión PostGIS"):
  - DESTINO_CARPETA: carpeta compartida o unidad de red (\\\\servidor\\... o Z:\\...).
  - DESTINO_SSH: ssh.exe del sistema (OpenSSH, viene con Windows 10+) con clave,
    sin contraseña: no hay forma de tipearla desde el plugin.

Los errores son por archivo: uno que falla no corta la copia de los demás.
"""

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field

from qgis.core import QgsSettings

from . import config

TIMEOUT_SSH = 60


# ─────────────────────────────────────────────────────────────────────────────
# Configuración del destino (QgsSettings, sin secretos: SSH usa clave)
# ─────────────────────────────────────────────────────────────────────────────
def _clave(nombre):
    return config.SETTINGS_PREFIJO + "fotos/" + nombre


def leer_destino():
    s = QgsSettings()
    return {
        "modo": s.value(_clave("modo"), "", type=str),
        "carpeta": s.value(_clave("carpeta"), "", type=str),
        "host": s.value(_clave("host"), "", type=str),
        "usuario": s.value(_clave("usuario"), "", type=str),
        "puerto": s.value(_clave("puerto"), "22", type=str),
        "clave_privada": s.value(_clave("clave_privada"), "", type=str),
        "ruta_remota": s.value(_clave("ruta_remota"), config.RUTA_REMOTA_FOTOS, type=str),
    }


def guardar_destino(**valores):
    s = QgsSettings()
    for nombre, valor in valores.items():
        s.setValue(_clave(nombre), valor)


def destino_configurado():
    d = leer_destino()
    if d["modo"] == config.DESTINO_CARPETA:
        return bool(d["carpeta"])
    if d["modo"] == config.DESTINO_SSH:
        return bool(d["host"] and d["usuario"] and d["ruta_remota"])
    return False


def describir_destino():
    d = leer_destino()
    if d["modo"] == config.DESTINO_CARPETA:
        return d["carpeta"]
    if d["modo"] == config.DESTINO_SSH:
        return f"{d['usuario']}@{d['host']}:{d['ruta_remota']}"
    return "(sin configurar)"


# ─────────────────────────────────────────────────────────────────────────────
# Resultado
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ResultadoCopia:
    copiadas: list = field(default_factory=list)          # rutas relativas
    ya_existian: list = field(default_factory=list)       # mismo archivo ya en destino (solo carpeta)
    fallidas: list = field(default_factory=list)          # [(fid, ruta, motivo)]
    rutas_invalidas: list = field(default_factory=list)   # [(fid, ruta)] no siguen el patrón

    def texto(self):
        lineas = [
            f"Destino: {describir_destino()}",
            f"  Copiadas:              {len(self.copiadas)}",
        ]
        if self.ya_existian:
            lineas.append(f"  Ya estaban en destino: {len(self.ya_existian)}")
        lineas.append(f"  Fallaron:              {len(self.fallidas)}")
        if self.rutas_invalidas:
            lineas.append(f"  Ruta fuera de patrón:  {len(self.rutas_invalidas)} (no se intentaron)")
        if self.fallidas:
            lineas += ["", "Fallos:"] + [f"  fid {fid}  {ruta}\n      → {motivo}" for fid, ruta, motivo in self.fallidas]
        if self.rutas_invalidas:
            lineas += ["", "Rutas que no siguen DCIM/FOTOS_OS/<N°_OS>/<archivo>:"]
            lineas += [f"  fid {fid}  {ruta!r}" for fid, ruta in self.rutas_invalidas]
        return "\n".join(lineas)


def ruta_valida(ruta):
    return (bool(ruta) and re.match(config.PATRON_RUTA_FOTO, ruta) is not None
            and ".." not in ruta.split("/"))


# ─────────────────────────────────────────────────────────────────────────────
# Copia
# ─────────────────────────────────────────────────────────────────────────────
def copiar(fotos, carpeta_origen):
    """fotos: [(fid, ruta_relativa)]. carpeta_origen: carpeta del gpkg importado."""
    if not destino_configurado():
        raise RuntimeError("Falta configurar el destino de las fotos.")
    resultado = ResultadoCopia()

    pendientes = []
    for fid, ruta in fotos:
        ruta = (ruta or "").strip()
        if not ruta_valida(ruta):
            resultado.rutas_invalidas.append((fid, ruta))
            continue
        origen = os.path.join(carpeta_origen, *ruta.split("/"))
        if not os.path.isfile(origen):
            resultado.fallidas.append((fid, ruta, f"no existe en el origen: {origen}"))
            continue
        pendientes.append((fid, ruta, origen))

    if not pendientes:
        return resultado
    if leer_destino()["modo"] == config.DESTINO_SSH:
        _copiar_ssh(pendientes, resultado)
    else:
        _copiar_carpeta(pendientes, resultado)
    return resultado


def _copiar_carpeta(pendientes, resultado):
    raiz = leer_destino()["carpeta"]
    if not os.path.isdir(raiz):
        for fid, ruta, _ in pendientes:
            resultado.fallidas.append((fid, ruta, f"no se accede a la carpeta destino {raiz}"))
        return
    for fid, ruta, origen in pendientes:
        destino = os.path.join(raiz, *ruta.split("/"))
        try:
            if os.path.isfile(destino) and os.path.getsize(destino) == os.path.getsize(origen):
                resultado.ya_existian.append(ruta)
                continue
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            shutil.copy2(origen, destino)
            resultado.copiadas.append(ruta)
        except OSError as e:
            resultado.fallidas.append((fid, ruta, str(e)))


# ── SSH ─────────────────────────────────────────────────────────────────────
def _ssh_exe():
    sistema = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", "ssh.exe")
    return sistema if os.path.isfile(sistema) else (shutil.which("ssh") or "ssh")


def _ssh(comando_remoto, entrada=None):
    """Ejecuta un comando en el servidor. Devuelve (ok, mensaje de error)."""
    d = leer_destino()
    args = [_ssh_exe(), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=15", "-p", d["puerto"] or "22"]
    if d["clave_privada"]:
        args += ["-i", d["clave_privada"]]
    args += [f"{d['usuario']}@{d['host']}", comando_remoto]
    try:
        proceso = subprocess.run(
            args, stdin=entrada or subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT_SSH,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return False, "no se encontró ssh.exe (OpenSSH de Windows)"
    except subprocess.TimeoutExpired:
        return False, f"sin respuesta del servidor en {TIMEOUT_SSH} s"
    if proceso.returncode != 0:
        error = proceso.stderr.decode("utf-8", "replace").strip() or f"código {proceso.returncode}"
        return False, error
    return True, ""


def _remota(ruta_relativa):
    return leer_destino()["ruta_remota"].rstrip("/") + "/" + ruta_relativa


def _copiar_ssh(pendientes, resultado):
    # Todas las carpetas en una sola conexión.
    carpetas = sorted({os.path.dirname(_remota(ruta)) for _, ruta, _ in pendientes})
    ok, error = _ssh("mkdir -p -- " + " ".join(shlex.quote(c) for c in carpetas))
    if not ok:
        for fid, ruta, _ in pendientes:
            resultado.fallidas.append((fid, ruta, f"no se pudieron crear las carpetas: {error}"))
        return
    # Un archivo por conexión: el éxito o fallo queda por archivo.
    for fid, ruta, origen in pendientes:
        with open(origen, "rb") as archivo:
            ok, error = _ssh(f"cat > {shlex.quote(_remota(ruta))}", entrada=archivo)
        if ok:
            resultado.copiadas.append(ruta)
        else:
            resultado.fallidas.append((fid, ruta, error))


def probar_destino():
    """Verifica que se pueda escribir en el destino. Devuelve texto o lanza excepción."""
    d = leer_destino()
    if d["modo"] == config.DESTINO_CARPETA:
        if not os.path.isdir(d["carpeta"]):
            raise RuntimeError(f"No se accede a la carpeta {d['carpeta']}")
        prueba = os.path.join(d["carpeta"], ".prueba_escritura_plugin")
        with open(prueba, "w") as f:
            f.write("ok")
        os.remove(prueba)
        return f"✓ Se puede escribir en {d['carpeta']}"
    if d["modo"] == config.DESTINO_SSH:
        ruta = shlex.quote(d["ruta_remota"])
        ok, error = _ssh(f"mkdir -p -- {ruta} && test -w {ruta}")
        if not ok:
            raise RuntimeError(f"SSH: {error}")
        return f"✓ SSH OK: se puede escribir en {describir_destino()}"
    raise RuntimeError("Elegí cómo llegar al servidor.")
