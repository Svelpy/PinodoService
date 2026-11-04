import importlib
import importlib.util
import pkgutil

import pytest

import app.domains
from app.shared.enums import Action, Module, Role
from app.shared.services.permissions import ROLE_LEVEL, ROLE_PERMISSIONS, can_manage_role


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
    ],
)
def test_can_manage_role_solo_roles_estrictamente_inferiores(
    actor_role: Role,
    target_role: Role,
    expected: bool,
) -> None:
    assert can_manage_role(actor_role, target_role) is expected


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
