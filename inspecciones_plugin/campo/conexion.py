"""
Conexión a PostGIS usando la API de conexiones de QGIS (sin psycopg2).

Dos modos, elegidos en el diálogo "Configurar conexión PostGIS":
  - MODO_EXISTENTE: reutiliza una conexión PostgreSQL ya guardada en el
    Navegador de QGIS. En settings se guarda solo su nombre.
  - MODO_PROPIA: host/puerto/base/sslmode en QgsSettings; usuario y contraseña
    cifrados en QgsAuthManager (authcfg), protegidos por la contraseña maestra.
"""

import re
import unicodedata

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsDataSourceUri,
    QgsProviderRegistry,
    QgsSettings,
)

from . import config


class ConexionNoConfigurada(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Quoting SQL
# ─────────────────────────────────────────────────────────────────────────────
def qi(nombre):
    """Identificador entre comillas dobles: respeta tildes, ° y mayúsculas."""
    return '"' + str(nombre).replace('"', '""') + '"'


def ql(valor):
    """Literal de texto. Asume standard_conforming_strings=on (default desde PG 9.1)."""
    return "'" + str(valor).replace("'", "''") + "'"


def tabla_calificada(tabla, esquema=config.ESQUEMA):
    return f"{qi(esquema)}.{qi(tabla)}"


def nombre_staging(iniciales, base=config.STAGING_BASE):
    """<base>_<iniciales del operario>, saneado a [a-z0-9_] y a 63 caracteres.

    base: inspecciones_staging, fotos_staging, observaciones_staging.

    En minúsculas para que en psql se pueda escribir sin comillas: "NA" → _na.
    """
    sufijo = unicodedata.normalize("NFKD", iniciales or "").encode("ascii", "ignore").decode()
    sufijo = re.sub(r"[^a-z0-9_]+", "_", sufijo.lower()).strip("_")
    if not sufijo:
        raise ValueError("Ingresá las iniciales del operario (se usan para nombrar la tabla de staging).")
    return f"{base}_{sufijo}"[:63]


# ─────────────────────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────────────────────
def _clave(nombre):
    return config.SETTINGS_PREFIJO + nombre


def leer_config():
    s = QgsSettings()
    return {
        "modo": s.value(_clave("modo"), "", type=str),
        "conexion": s.value(_clave("conexion"), "", type=str),
        "host": s.value(_clave("host"), "", type=str),
        "puerto": s.value(_clave("puerto"), "5432", type=str),
        "base": s.value(_clave("base"), "", type=str),
        "sslmode": s.value(_clave("sslmode"), "prefer", type=str),
        "authcfg": s.value(_clave("authcfg"), "", type=str),
    }


def leer_iniciales():
    return QgsSettings().value(_clave("iniciales"), "", type=str)


def guardar_iniciales(iniciales):
    QgsSettings().setValue(_clave("iniciales"), iniciales)


def esta_configurada():
    cfg = leer_config()
    if cfg["modo"] == config.MODO_EXISTENTE:
        return bool(cfg["conexion"])
    if cfg["modo"] == config.MODO_PROPIA:
        return bool(cfg["host"] and cfg["base"] and cfg["authcfg"])
    return False


def conexiones_existentes():
    """Nombres de las conexiones PostgreSQL guardadas en el Navegador de QGIS."""
    return sorted(_metadata().connections().keys())


def guardar_existente(nombre):
    s = QgsSettings()
    s.setValue(_clave("modo"), config.MODO_EXISTENTE)
    s.setValue(_clave("conexion"), nombre)


def guardar_propia(host, puerto, base, sslmode, usuario, password):
    """Guarda los datos no secretos en settings y las credenciales en authcfg.

    Si ya había un authcfg del plugin se actualiza. Una contraseña vacía
    conserva la guardada (el diálogo no la muestra).
    """
    authcfg = _guardar_credenciales(leer_config()["authcfg"], usuario, password)
    s = QgsSettings()
    s.setValue(_clave("modo"), config.MODO_PROPIA)
    s.setValue(_clave("host"), host)
    s.setValue(_clave("puerto"), puerto)
    s.setValue(_clave("base"), base)
    s.setValue(_clave("sslmode"), sslmode)
    s.setValue(_clave("authcfg"), authcfg)


# ─────────────────────────────────────────────────────────────────────────────
# QgsAuthManager
# ─────────────────────────────────────────────────────────────────────────────
def _auth_manager():
    am = QgsApplication.authManager()
    if am.isDisabled():
        raise RuntimeError(
            "El gestor de autenticación de QGIS está deshabilitado: "
            + am.disabledMessage()
        )
    # Pide la contraseña maestra si todavía no se ingresó en esta sesión
    # (o la crea, la primera vez que se usa el gestor en este perfil).
    if not am.setMasterPassword(True):
        raise RuntimeError("Se necesita la contraseña maestra de QGIS para guardar/leer credenciales.")
    return am


def _cargar_authcfg(am, authcfg):
    cfg = QgsAuthMethodConfig()
    resultado = am.loadAuthenticationConfig(authcfg, cfg, True)
    # Según la versión de PyQGIS devuelve bool o (bool, config).
    if isinstance(resultado, tuple):
        ok, cfg = resultado
    else:
        ok = resultado
    return cfg if ok and cfg.isValid() else None


def usuario_guardado():
    """Usuario del authcfg del plugin, para precargar el diálogo (o "")."""
    authcfg = leer_config()["authcfg"]
    if not authcfg:
        return ""
    try:
        cfg = _cargar_authcfg(_auth_manager(), authcfg)
    except RuntimeError:
        return ""
    return cfg.config("username", "") if cfg else ""


def _guardar_credenciales(authcfg, usuario, password):
    am = _auth_manager()
    existente = _cargar_authcfg(am, authcfg) if authcfg else None

    if existente is not None:
        existente.setConfig("username", usuario)
        if password:
            existente.setConfig("password", password)
        if not am.updateAuthenticationConfig(existente):
            raise RuntimeError("No se pudieron actualizar las credenciales en el gestor de QGIS.")
        return existente.id()

    if not password:
        raise ValueError("Ingresá la contraseña.")
    cfg = QgsAuthMethodConfig("Basic")
    cfg.setName(config.NOMBRE_AUTHCFG)
    cfg.setConfig("username", usuario)
    cfg.setConfig("password", password)
    resultado = am.storeAuthenticationConfig(cfg)
    if isinstance(resultado, tuple):
        ok, cfg = resultado
    else:
        ok = resultado
    if not ok or not cfg.id():
        raise RuntimeError("No se pudieron guardar las credenciales en el gestor de QGIS.")
    return cfg.id()


# ─────────────────────────────────────────────────────────────────────────────
# Conexión
# ─────────────────────────────────────────────────────────────────────────────
def _metadata():
    return QgsProviderRegistry.instance().providerMetadata("postgres")


def uri_base():
    """QgsDataSourceUri con los datos de conexión (sin tabla)."""
    cfg = leer_config()
    if cfg["modo"] == config.MODO_EXISTENTE and cfg["conexion"]:
        conexion = _metadata().findConnection(cfg["conexion"])
        if conexion is None:
            raise ConexionNoConfigurada(
                f"La conexión '{cfg['conexion']}' ya no existe en el Navegador de QGIS."
            )
        return QgsDataSourceUri(conexion.uri())

    if cfg["modo"] == config.MODO_PROPIA and esta_configurada():
        uri = QgsDataSourceUri()
        uri.setConnection(
            cfg["host"], cfg["puerto"], cfg["base"], "", "",
            QgsDataSourceUri.decodeSslMode(cfg["sslmode"]), cfg["authcfg"],
        )
        return uri

    raise ConexionNoConfigurada("Falta configurar la conexión a PostGIS.")


def conectar():
    """Conexión con executeSql(). Lanza excepción si no se puede conectar."""
    return _metadata().createConnection(uri_base().uri(False), {})


def ejecutar(conexion, sql):
    """Ejecuta SQL y devuelve las filas como lista de listas (vacía si no hay resultado)."""
    return conexion.executeSql(sql)


def probar():
    """Devuelve un texto corto con usuario y base, o lanza excepción."""
    filas = ejecutar(conectar(), "SELECT current_user, current_database()")
    usuario, base = filas[0]
    return f"Conectado como '{usuario}' a la base '{base}'."
