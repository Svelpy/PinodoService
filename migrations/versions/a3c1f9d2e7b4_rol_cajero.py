"""rol cajero

Revision ID: a3c1f9d2e7b4
Revises: 6352324b511d
Create Date: 2026-11-04 01:15:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a3c1f9d2e7b4'
down_revision: Union[str, Sequence[str], None] = '6352324b511d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Admite el rol CAJERO en el CHECK de usuarios.rol."""
    op.drop_constraint('rol_usuario', 'usuarios', type_='check')
    op.create_check_constraint(
        'rol_usuario',
        'usuarios',
        "rol IN ('SUPERADMIN', 'OWNER', 'ADMIN', 'CAJERO')",
    )


def downgrade() -> None:
    """Retira CAJERO del CHECK; falla si quedan usuarios con ese rol."""
    op.drop_constraint('rol_usuario', 'usuarios', type_='check')
    op.create_check_constraint(
        'rol_usuario',
        'usuarios',
        "rol IN ('SUPERADMIN', 'OWNER', 'ADMIN')",
    )
