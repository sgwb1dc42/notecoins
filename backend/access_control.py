"""
Práctica 7 – Diseño Seguro (I) — adaptado para Práctica 9
Módulo 2: Control de acceso con Diseño por Contrato
"""

from functools import wraps
from secure_log import anadir_al_log, set_current_user

# ---------------------------------------------------------------------------
# Reglas de acceso y jerarquía de roles
# ---------------------------------------------------------------------------

access_rules: dict[str, dict] = {
    "admin":               {"rol": "admin"},
    "distribute_dividend": {"rol": "admin"},
}

role_hierarchy: dict[str, dict] = {
    "admin":   {"implied_roles": {"student"}},
    "student": {"implied_roles": set()},
}

_active_user_info: dict | None = None


# ---------------------------------------------------------------------------
# Utilidades de rol
# ---------------------------------------------------------------------------

def _get_all_roles(rol: str) -> set[str]:
    roles: set[str] = {rol}
    to_visit = list(role_hierarchy.get(rol, {}).get("implied_roles", set()))
    while to_visit:
        r = to_visit.pop()
        if r not in roles:
            roles.add(r)
            to_visit.extend(role_hierarchy.get(r, {}).get("implied_roles", set()))
    return roles


def _check_access(func_name: str, user_info: dict | None) -> bool:
    if func_name not in access_rules:
        return True
    required_rol = access_rules[func_name]["rol"]
    if user_info is None:
        return False
    return required_rol in _get_all_roles(user_info["rol"])


def set_active_user(
    user_id: int | None,
    rol: str | None = None,
    email: str | None = None,
) -> None:
    """Establece el usuario activo para las comprobaciones de acceso y el log."""
    global _active_user_info
    if user_id is None:
        _active_user_info = None
        set_current_user("anonimo@uma.es")
    else:
        _active_user_info = {"id": user_id, "rol": rol or "student"}
        set_current_user(email or f"user_{user_id}@uma.es")


# ---------------------------------------------------------------------------
# Decorador access_control
# ---------------------------------------------------------------------------

def access_control(func):
    """
    Decorador de control de acceso (Diseño por Contrato).

    Precondición : el usuario activo tiene el rol requerido para func.__name__.
    Postcondición: si la precondición no se cumple, lanza PermissionError
                   y registra la denegación en el log seguro.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        func_name  = func.__name__
        user_info  = _active_user_info

        params_parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
        params_desc  = (
            "con parámetros: " + ", ".join(params_parts)
            if params_parts else "sin parámetros"
        )

        if _check_access(func_name, user_info):
            resultado = func(*args, **kwargs)

            assert resultado is not None, (
                f"Postcondición fallida: '{func_name}' devolvió None."
            )

            anadir_al_log("info", f"Acceso concedido a '{func_name}' {params_desc}")
            return resultado
        else:
            uid = user_info["id"] if user_info else "anonimo"
            anadir_al_log(
                "warning",
                f"Acceso denegado a '{func_name}' para usuario '{uid}' {params_desc}",
            )
            raise PermissionError(
                f"Acceso denegado: usuario '{uid}' no tiene permiso para '{func_name}'."
            )

    return wrapper
