import importlib
import importlib.util
import pkgutil

import pytest

import app.domains
from app.shared.enums import Action, Module, Role
from app.shared.services.permissions import (
    ROLE_LEVEL,
    ROLE_PERMISSIONS,
    VENTA_GLOBAL_SCOPE_ROLES,
    VENTA_OWN_SCOPE_ROLES,
    can_manage_role,
)


def test_todos_los_roles_tienen_nivel() -> None:
    assert set(ROLE_LEVEL) == set(Role)


def test_cada_rol_lista_todos_los_modulos() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    for modules in ROLE_PERMISSIONS.values():
        assert set(modules) == set(Module)
        assert all(isinstance(actions, frozenset) for actions in modules.values())


@pytest.mark.parametrize(
    ("actor_role", "target_role", "expected"),
    [
        (Role.SUPERADMIN, Role.OWNER, True),
        (Role.SUPERADMIN, Role.ADMIN, True),
        (Role.OWNER, Role.ADMIN, True),
        (Role.SUPERADMIN, Role.SUPERADMIN, False),
        (Role.OWNER, Role.OWNER, False),
        (Role.ADMIN, Role.ADMIN, False),
        (Role.OWNER, Role.SUPERADMIN, False),
        (Role.ADMIN, Role.OWNER, False),
        (Role.ADMIN, Role.SUPERADMIN, False),
        (Role.SUPERADMIN, Role.CAJERO, True),
        (Role.OWNER, Role.CAJERO, True),
        (Role.ADMIN, Role.CAJERO, True),
        (Role.CAJERO, Role.CAJERO, False),
        (Role.CAJERO, Role.ADMIN, False),
        (Role.CAJERO, Role.OWNER, False),
        (Role.CAJERO, Role.SUPERADMIN, False),
    ],
)
def test_can_manage_role_solo_roles_estrictamente_inferiores(
    actor_role: Role,
    target_role: Role,
    expected: bool,
) -> None:
    assert can_manage_role(actor_role, target_role) is expected


def test_cajero_solo_lee_y_no_gestiona_usuarios() -> None:
    cajero = ROLE_PERMISSIONS[Role.CAJERO]
    assert cajero[Module.USUARIO] == frozenset()
    for module, actions in cajero.items():
        if module not in {Module.USUARIO, Module.VENTA, Module.VENTA_PAGO, Module.MOVIMIENTO_INVENTARIO}:
            assert actions == frozenset({Action.READ}), module


def test_cajero_vende_pero_no_anula_ventas_confirmadas() -> None:
    # DELETE es la capacidad de anular una venta confirmada.
    assert ROLE_PERMISSIONS[Role.CAJERO][Module.VENTA] == frozenset(
        {Action.CREATE, Action.READ, Action.UPDATE}
    )
    for role in (Role.SUPERADMIN, Role.OWNER):
        assert Action.DELETE in ROLE_PERMISSIONS[role][Module.VENTA], role


def test_kardex_no_se_edita_y_el_cajero_no_ve_costos() -> None:
    # Un movimiento se corrige con otro AJUSTE; los costos solo los ve quien accede al kardex.
    for role in (Role.OWNER, Role.ADMIN):
        assert ROLE_PERMISSIONS[role][Module.MOVIMIENTO_INVENTARIO] == frozenset(
            {Action.CREATE, Action.READ}
        ), role
    assert ROLE_PERMISSIONS[Role.CAJERO][Module.MOVIMIENTO_INVENTARIO] == frozenset()


def test_pagos_de_venta_no_se_anulan_salvo_superadmin() -> None:
    # Ningún endpoint elimina pagos; la devolución se hace cancelando la venta.
    for role in (Role.OWNER, Role.ADMIN, Role.CAJERO):
        assert ROLE_PERMISSIONS[role][Module.VENTA_PAGO] == frozenset(
            {Action.CREATE, Action.READ, Action.UPDATE}
        ), role


def test_superadmin_tiene_todas_las_acciones_en_todos_los_modulos() -> None:
    for module, actions in ROLE_PERMISSIONS[Role.SUPERADMIN].items():
        assert actions == frozenset(Action), module


def test_owner_no_audita() -> None:
    for module, actions in ROLE_PERMISSIONS[Role.OWNER].items():
        assert Action.AUDIT not in actions, module


def test_admin_no_elimina() -> None:
    for module, actions in ROLE_PERMISSIONS[Role.ADMIN].items():
        assert Action.DELETE not in actions, module


def test_todo_rol_con_acceso_a_ventas_tiene_alcance() -> None:
    for module in (Module.VENTA, Module.VENTA_PAGO):
        con_acceso = {role for role in Role if ROLE_PERMISSIONS[role][module]}
        assert con_acceso == VENTA_GLOBAL_SCOPE_ROLES | VENTA_OWN_SCOPE_ROLES, module
    assert not VENTA_GLOBAL_SCOPE_ROLES & VENTA_OWN_SCOPE_ROLES


def test_las_rutas_de_auditoria_exigen_la_accion_audit() -> None:
    audit_routes = [
        route
        for info in pkgutil.iter_modules(app.domains.__path__)
        if info.ispkg and importlib.util.find_spec(f"app.domains.{info.name}.routes")
        for route in importlib.import_module(f"app.domains.{info.name}.routes").router.routes
        if route.path.endswith("/audit")
    ]
    assert len(audit_routes) >= 10
    for route in audit_routes:
        closures = [
            cell.cell_contents
            for dependency in route.dependant.dependencies
            for cell in (getattr(dependency.call, "__closure__", None) or ())
        ]
        assert Action.AUDIT in closures, route.path
