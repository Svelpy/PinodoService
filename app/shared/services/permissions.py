"""
shared/services/permissions.py

Única fuente de verdad de "quién puede hacer qué, sobre qué módulo".
Si agregás un rol o un módulo nuevo, TODO el cambio pasa por este
archivo — no se tocan las rutas.
"""

from app.shared.enums import Role, Module, Action


# Cada rol lista todos los módulos, para que la matriz se lea como una tabla.
# frozenset() == sin acceso a ese módulo (ni siquiera lectura).
# Se deniega por defecto: un rol o módulo ausente también equivale a sin acceso.
ROLE_PERMISSIONS: dict[Role, dict[Module, frozenset[Action]]] = {
    # Desarrolladores.
    Role.SUPERADMIN: {
        Module.USUARIO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.CONFIG: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.SECCION: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.CATEGORIA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.PRODUCTO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.CATEGORIA_PRODUCTO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.PRODUCTO_COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.IMAGEN: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.TALLA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.SKU: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
    },
    # Dueño de la tienda.
    Role.OWNER: {
        Module.USUARIO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.CONFIG: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.SECCION: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.CATEGORIA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.PRODUCTO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.CATEGORIA_PRODUCTO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.PRODUCTO_COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.IMAGEN: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.TALLA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.SKU: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
    },
    # Encargado que administra la tienda por el dueño.
    Role.ADMIN: {
        Module.USUARIO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),  # la jerarquía lo limita a gestionar cajeros
        Module.CONFIG: frozenset({Action.READ}),  # la identidad de la tienda la decide el dueño
        Module.SECCION: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.AUDIT}),  # estructura de la tienda: oculta con is_visible
        Module.CATEGORIA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.PRODUCTO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.CATEGORIA_PRODUCTO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.PRODUCTO_COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.IMAGEN: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.TALLA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.SKU: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
    },
    # Atiende la caja: consulta el catálogo, precios y stock sin modificarlos.
    Role.CAJERO: {
        Module.USUARIO: frozenset(),  # no gestiona usuarios; su perfil lo edita desde /me
        Module.CONFIG: frozenset({Action.READ}),  # solo consulta los datos de la tienda
        Module.SECCION: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.CATEGORIA: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.PRODUCTO: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.CATEGORIA_PRODUCTO: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.COLOR: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.PRODUCTO_COLOR: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.IMAGEN: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.TALLA: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.SKU: frozenset({Action.READ}),  # consulta precios y stock; no los ajusta
    },
}


# Jerarquía de roles: un número mayor es un rango superior.
# Todo rol de Role debe figurar aquí.
ROLE_LEVEL: dict[Role, int] = {
    Role.CAJERO: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
    Role.SUPERADMIN: 4,
}


def has_permission(role: Role, module: Module, action: Action) -> bool:
    """True si el rol tiene la acción habilitada en ese módulo."""
    return action in ROLE_PERMISSIONS.get(role, {}).get(module, frozenset())


def can_manage_role(actor_role: Role, target_role: Role) -> bool:
    """True si actor_role es estrictamente superior a target_role."""
    return ROLE_LEVEL[target_role] < ROLE_LEVEL[actor_role]
