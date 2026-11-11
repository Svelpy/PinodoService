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
        Module.COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.PRODUCTO_COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.IMAGEN: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.TALLA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.SKU: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.VENTA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),  # DELETE = anular una venta confirmada
        Module.VENTA_PAGO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
        Module.MOVIMIENTO_INVENTARIO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE, Action.AUDIT}),
    },
    # Dueño de la tienda. La auditoría (AUDIT) queda para SUPERADMIN.
    Role.OWNER: {
        Module.USUARIO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.CONFIG: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.SECCION: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.CATEGORIA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.PRODUCTO: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.PRODUCTO_COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.IMAGEN: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.TALLA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.SKU: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),
        Module.VENTA: frozenset({Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE}),  # DELETE = anular una venta confirmada
        Module.VENTA_PAGO: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),  # sin DELETE: un pago no se anula; se cancela la venta
        Module.MOVIMIENTO_INVENTARIO: frozenset({Action.CREATE, Action.READ}),  # el kardex no se edita ni se elimina: se corrige con otro AJUSTE
    },
    # Encargado que administra la tienda por el dueño. No elimina (DELETE) en ningún módulo.
    Role.ADMIN: {
        Module.USUARIO: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),  # la jerarquía lo limita a gestionar cajeros
        Module.CONFIG: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),  
        Module.SECCION: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),  # estructura de la tienda: oculta con is_visible
        Module.CATEGORIA: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),
        Module.PRODUCTO: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),
        Module.COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),
        Module.PRODUCTO_COLOR: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),
        Module.IMAGEN: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),
        Module.TALLA: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),
        Module.SKU: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),
        Module.VENTA: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),  # sin DELETE: no anula ventas confirmadas
        Module.VENTA_PAGO: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),  # sin DELETE: un pago no se anula; se cancela la venta
        Module.MOVIMIENTO_INVENTARIO: frozenset({Action.CREATE, Action.READ}),  # el kardex no se edita ni se elimina: se corrige con otro AJUSTE
    },
    # Atiende la caja: registra ventas y consulta el catálogo, precios y stock sin modificarlos.
    Role.CAJERO: {
        Module.USUARIO: frozenset(),  # no gestiona usuarios; su perfil lo edita desde /me
        Module.CONFIG: frozenset({Action.READ}),  # solo consulta los datos de la tienda
        Module.SECCION: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.CATEGORIA: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.PRODUCTO: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.COLOR: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.PRODUCTO_COLOR: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.IMAGEN: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.TALLA: frozenset({Action.READ}),  # el catálogo lo mantienen ADMIN y OWNER
        Module.SKU: frozenset({Action.READ}),  # consulta precios y stock; no los ajusta
        Module.VENTA: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),  # cobra y cancela pendientes; anular una venta confirmada (DELETE) y la auditoría quedan para roles superiores
        Module.VENTA_PAGO: frozenset({Action.CREATE, Action.READ, Action.UPDATE}),  # cobra sus ventas; sin DELETE: un pago no se anula
        Module.MOVIMIENTO_INVENTARIO: frozenset(),  # no ve costos ni mueve stock: las ventas lo mueven solas
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


# Alcance de las ventas (segunda puerta, AGENTS.md §14): estos roles ven y
# gestionan todas las ventas; los de VENTA_OWN_SCOPE_ROLES, solo las que
# registraron. Un rol ausente de ambos grupos no ve ninguna. Los pagos de
# venta heredan este alcance: se ven y se gestionan a través de su venta.
VENTA_GLOBAL_SCOPE_ROLES: frozenset[Role] = frozenset({Role.SUPERADMIN, Role.OWNER, Role.ADMIN})
VENTA_OWN_SCOPE_ROLES: frozenset[Role] = frozenset({Role.CAJERO})


def has_permission(role: Role, module: Module, action: Action) -> bool:
    """True si el rol tiene la acción habilitada en ese módulo."""
    return action in ROLE_PERMISSIONS.get(role, {}).get(module, frozenset())


def can_manage_role(actor_role: Role, target_role: Role) -> bool:
    """True si actor_role es estrictamente superior a target_role."""
    return ROLE_LEVEL[target_role] < ROLE_LEVEL[actor_role]
