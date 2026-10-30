import pytest

from app.shared.enums import Role
from app.shared.services.permissions import ROLE_LEVEL, can_manage_role


def test_todos_los_roles_tienen_nivel() -> None:
    assert set(ROLE_LEVEL) == set(Role)


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
