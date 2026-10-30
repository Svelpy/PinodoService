"""
shared/services/permissions.py

Única fuente de verdad de "quién puede hacer qué, sobre qué módulo".
Si agregás un rol o un módulo nuevo, TODO el cambio pasa por este
archivo — no se tocan las rutas.
"""

from app.shared.enums import Role, Module, Action


ALL_ACTIONS = {Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}
SIN_ELIMINAR = {Action.CREATE, Action.READ, Action.UPDATE}
SIN_ELIMINAR_SIN_CREAR = {Action.READ, Action.UPDATE}
SOLO_LECTURA = {Action.READ}

# dict[Role, dict[Module, set[Action]]]
# Un módulo ausente en el dict de un rol == sin acceso a ese módulo
# (ni siquiera lectura).
ROLE_PERMISSIONS: dict[Role, dict[Module, set[Action]]] = {
    Role.SUPERADMIN: {
        Module.USUARIO: ALL_ACTIONS,
        Module.CONFIG: ALL_ACTIONS,
        Module.SECCION: ALL_ACTIONS,
        Module.CATEGORIA: ALL_ACTIONS,
        Module.PRODUCTO: ALL_ACTIONS,
        Module.CATEGORIA_PRODUCTO: ALL_ACTIONS,
        Module.COLOR: ALL_ACTIONS,
        Module.PRODUCTO_COLOR: ALL_ACTIONS,
        Module.IMAGEN: ALL_ACTIONS,
        Module.TALLA: ALL_ACTIONS,
        Module.SKU: ALL_ACTIONS,
    },
    Role.OWNER: {
        Module.USUARIO: ALL_ACTIONS,
        Module.CONFIG: ALL_ACTIONS,
        Module.SECCION: ALL_ACTIONS,
        Module.CATEGORIA: ALL_ACTIONS,
        Module.PRODUCTO: ALL_ACTIONS,
        Module.CATEGORIA_PRODUCTO: ALL_ACTIONS,
        Module.COLOR: ALL_ACTIONS,
        Module.PRODUCTO_COLOR: ALL_ACTIONS,
        Module.IMAGEN: ALL_ACTIONS,
        Module.TALLA: ALL_ACTIONS,
        Module.SKU: ALL_ACTIONS,
    },
    Role.ADMIN: {
        # Sin Module.USUARIO: no tiene roles inferiores que gestionar.
        Module.CONFIG: SOLO_LECTURA,
        Module.SECCION: SIN_ELIMINAR,
        Module.CATEGORIA: ALL_ACTIONS,
        Module.PRODUCTO: ALL_ACTIONS,
        Module.CATEGORIA_PRODUCTO: ALL_ACTIONS,
        Module.COLOR: ALL_ACTIONS,
        Module.PRODUCTO_COLOR: ALL_ACTIONS,
        Module.IMAGEN: ALL_ACTIONS,
        Module.TALLA: ALL_ACTIONS,
        Module.SKU: ALL_ACTIONS,
    },
}


# Jerarquía de roles: un número mayor es un rango superior.
# Todo rol de Role debe figurar aquí.
ROLE_LEVEL: dict[Role, int] = {
    Role.ADMIN: 1,
    Role.OWNER: 2,
    Role.SUPERADMIN: 3,
}


def has_permission(role: Role, module: Module, action: Action) -> bool:
    """True si el rol tiene la acción habilitada en ese módulo."""
    return action in ROLE_PERMISSIONS.get(role, {}).get(module, set())


def can_manage_role(actor_role: Role, target_role: Role) -> bool:
    """True si actor_role es estrictamente superior a target_role."""
    return ROLE_LEVEL[target_role] < ROLE_LEVEL[actor_role]
