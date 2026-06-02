"""
Práctica 7 – Diseño Seguro (I)
Módulo 1: Sistema de registro seguro de actividad
"""

import hashlib
import logging
import os
from datetime import datetime, timezone
from functools import wraps

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
LOG_FILE = "RegistroSeguro.log"

_formatter = logging.Formatter(
    fmt="%(asctime)s: %(levelname)-8s | %(message)s |",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_logger: logging.Logger | None = None
_last_hash: str = ""
_current_user: str = "anonimo@uma.es"


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).digest().hex()


def _get_tiempo_legible() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")


def _leer_ultima_linea(log_file: str) -> str | None:
    if not os.path.exists(log_file) or os.path.getsize(log_file) == 0:
        return None
    with open(log_file, "r", encoding="utf-8") as f:
        lines = [l.rstrip() for l in f if l.strip()]
    return lines[-1] if lines else None


def _extraer_hash_de_linea(linea: str) -> str | None:
    try:
        partes = linea.split("'")
        if len(partes) >= 3:
            return partes[1]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Configuración y arranque del logger
# ---------------------------------------------------------------------------

def configure_logging(log_file: str = LOG_FILE) -> None:
    global _logger, _last_hash

    _logger = logging.getLogger("RegistroSeguro")
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

    if not _logger.handlers:
        fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        fh.setFormatter(_formatter)
        _logger.addHandler(fh)

    ultima = _leer_ultima_linea(log_file)
    if ultima:
        h = _extraer_hash_de_linea(ultima)
        _last_hash = h if h else ""
    else:
        _last_hash = ""


def inicializar_log(log_file: str = LOG_FILE) -> None:
    global _last_hash

    configure_logging(log_file)

    if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
        return

    tiempo = _get_tiempo_legible()
    mensaje = f"Inicialización del log en el tiempo {tiempo}"
    hash_entrada = _hash(mensaje)
    _last_hash = hash_entrada

    _logger.info(f"'{hash_entrada}': {mensaje}")


# ---------------------------------------------------------------------------
# Función principal de escritura
# ---------------------------------------------------------------------------

def anadir_al_log(nivel_log: str, log_string: str, usuario: str | None = None) -> None:
    global _last_hash

    if _logger is None:
        inicializar_log()

    uid = usuario if usuario is not None else _current_user

    contenido_para_hash = log_string + _last_hash
    hash_entrada = _hash(contenido_para_hash)
    _last_hash = hash_entrada

    mensaje = f"{uid} | '{hash_entrada}': {log_string}"

    niveles = {
        "debug":    _logger.debug,
        "info":     _logger.info,
        "warning":  _logger.warning,
        "error":    _logger.error,
        "critical": _logger.critical,
    }
    log_fn = niveles.get(nivel_log.lower(), _logger.info)
    log_fn(mensaje)


# ---------------------------------------------------------------------------
# Verificación de integridad
# ---------------------------------------------------------------------------

def verificar_cadena_hashes(log_file: str = LOG_FILE) -> bool:
    if not os.path.exists(log_file) or os.path.getsize(log_file) == 0:
        print("El fichero de log no existe o está vacío.")
        return False

    with open(log_file, "r", encoding="utf-8") as f:
        lines = [l.rstrip() for l in f if l.strip()]

    hash_anterior = ""
    for idx, linea in enumerate(lines):
        hash_en_log = _extraer_hash_de_linea(linea)
        if hash_en_log is None:
            print(f"Línea {idx+1}: no se pudo extraer el hash.")
            return False

        try:
            mensaje = linea.split(f"'{hash_en_log}': ", 1)[1].rstrip(" |")
        except IndexError:
            print(f"Línea {idx+1}: formato inesperado.")
            return False

        if idx == 0:
            hash_esperado = _hash(mensaje)
        else:
            hash_esperado = _hash(mensaje + hash_anterior)

        if hash_en_log != hash_esperado:
            print(f"Línea {idx+1}: ¡hash inválido! Log posiblemente manipulado.")
            return False

        hash_anterior = hash_en_log

    return True


# ---------------------------------------------------------------------------
# Decorador monitor1
# ---------------------------------------------------------------------------

def set_current_user(user_id: str) -> None:
    global _current_user
    _current_user = user_id


def monitor1(nivel_log: str = "info"):
    """
    Decorador de registro seguro.

    Uso:
        @monitor1(nivel_log="info")
        def mi_funcion(arg1, arg2):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            resultado = func(*args, **kwargs)

            params_parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
            if params_parts:
                params_str = ", ".join(params_parts)
                descripcion = (
                    f"Llamada a la función '{func.__name__}' "
                    f"con parámetros: {params_str} "
                    f"-> Resultado: {resultado}"
                )
            else:
                descripcion = (
                    f"Llamada a la función '{func.__name__}' "
                    f"sin parámetros "
                    f"-> Resultado: {resultado}"
                )

            anadir_al_log(nivel_log, descripcion)
            return resultado
        return wrapper
    return decorator
