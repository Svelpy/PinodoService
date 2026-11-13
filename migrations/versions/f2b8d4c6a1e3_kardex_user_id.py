"""kardex_user_id

movimientos_inventario: agrega user_id, el usuario responsable del movimiento,
con foreign key a usuarios. created_by se conserva como auditoría.

Datos: cada movimiento existente toma su created_by. Los que no lo tienen (el
saldo inicial insertado por la migración del kardex) toman el usuario que creó
el SKU. Si alguno queda sin usuario, la migración falla y no cambia nada.

Revision ID: f2b8d4c6a1e3
Revises: e5a9c3b71d20
Create Date: 2026-11-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b8d4c6a1e3'
down_revision: Union[str, Sequence[str], None] = 'e5a9c3b71d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MOVIMIENTOS = 'movimientos_inventario'
FK = 'movimientos_inventario_user_id_fkey'
INDEX = 'movimientos_inventario_idx_user_created_at'


def upgrade() -> None:
    """Agrega user_id y lo rellena desde created_by o el creador del SKU."""
    op.add_column(MOVIMIENTOS, sa.Column('user_id', sa.Uuid(), nullable=True), schema='public')
    op.execute(
        """
        UPDATE public.movimientos_inventario m
        SET user_id = COALESCE(m.created_by, s.created_by)
        FROM public.skus s
        WHERE s.id = m.sku_id
        """
    )
    op.alter_column(MOVIMIENTOS, 'user_id', nullable=False, schema='public')
    op.create_foreign_key(
        FK, MOVIMIENTOS, 'usuarios', ['user_id'], ['id'],
        source_schema='public', referent_schema='public',
    )
    op.create_index(INDEX, MOVIMIENTOS, ['user_id', 'created_at'], unique=False, schema='public')


def downgrade() -> None:
    """Quita user_id; created_by no cambia."""
    op.drop_index(INDEX, table_name=MOVIMIENTOS, schema='public')
    op.drop_constraint(FK, MOVIMIENTOS, schema='public', type_='foreignkey')
    op.drop_column(MOVIMIENTOS, 'user_id', schema='public')
