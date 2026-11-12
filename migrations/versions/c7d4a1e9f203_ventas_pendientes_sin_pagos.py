"""ventas pendientes sin pagos

Sin anticipos: los pagos de una venta se registran todos juntos al cobrarla
(al crearla o al confirmarla) y cubren exactamente su total. Una venta
PENDIENTE, por tanto, nunca tiene pagos.

Si quedara alguna venta pendiente con anticipos, el CHECK falla y la
migración completa se revierte sin cambiar nada: hay que confirmarla o
cancelarla antes de migrar.

Revision ID: c7d4a1e9f203
Revises: 5b8e2f7c1a94
Create Date: 2026-11-11 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c7d4a1e9f203'
down_revision: Union[str, Sequence[str], None] = '5b8e2f7c1a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Una venta pendiente no tiene pagos."""
    op.create_check_constraint(
        'ck_ventas_pendiente_sin_pagos',
        'ventas',
        "estado <> 'PENDIENTE' OR total_pagado = 0",
    )


def downgrade() -> None:
    """Vuelve a permitir anticipos en las ventas pendientes."""
    op.drop_constraint('ck_ventas_pendiente_sin_pagos', 'ventas', type_='check')
