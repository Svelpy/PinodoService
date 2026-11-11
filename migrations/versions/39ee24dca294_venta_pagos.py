"""venta_pagos

Pagos mixtos y anticipos: los pagos pasan de ventas.metodo_pago a la tabla
venta_pagos, y ventas.total_pagado guarda su suma.

No traspasa datos: las ventas existentes eran de prueba y se vaciaron antes de
migrar. Si quedara alguna venta CONFIRMADA, ck_ventas_confirmada_pagada falla
y la migración completa se revierte sin cambiar nada.

Revision ID: 39ee24dca294
Revises: 974e21a3c165
Create Date: 2026-11-11 14:59:31.107080

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '39ee24dca294'
down_revision: Union[str, Sequence[str], None] = '974e21a3c165'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea venta_pagos, agrega ventas.total_pagado y retira ventas.metodo_pago."""
    op.create_table('venta_pagos',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Uuid(), nullable=True),
    sa.Column('venta_id', sa.Uuid(), nullable=False),
    sa.Column('metodo', sa.Enum('EFECTIVO', 'QR', 'TRANSFERENCIA', name='metodo_pago', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('monto', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('referencia', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('comprobante_url', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.CheckConstraint('monto > 0', name='ck_venta_pagos_monto_positivo'),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_public_venta_pagos_is_deleted'), 'venta_pagos', ['is_deleted'], unique=False)
    op.create_index('venta_pagos_idx_venta_pagos_metodo_created_at', 'venta_pagos', ['metodo', 'created_at'], unique=False)
    op.create_index('venta_pagos_idx_venta_pagos_venta', 'venta_pagos', ['venta_id'], unique=False)

    # El server_default solo rellena las filas existentes; el model asigna el valor.
    op.add_column(
        'ventas',
        sa.Column('total_pagado', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
    )
    op.alter_column('ventas', 'total_pagado', server_default=None)
    op.create_check_constraint('ck_ventas_total_pagado_no_negativo', 'ventas', 'total_pagado >= 0')
    op.create_check_constraint('ck_ventas_total_pagado_hasta_total', 'ventas', 'total_pagado <= total')
    op.create_check_constraint(
        'ck_ventas_confirmada_pagada',
        'ventas',
        "estado <> 'CONFIRMADA' OR total_pagado = total",
    )
    # Su CHECK metodo_pago se elimina junto con la columna.
    op.drop_column('ventas', 'metodo_pago')


def downgrade() -> None:
    """
    Restaura ventas.metodo_pago (EFECTIVO en las filas existentes) y elimina
    venta_pagos y total_pagado: los pagos registrados se pierden.
    """
    op.add_column(
        'ventas',
        sa.Column('metodo_pago', sa.VARCHAR(length=20), nullable=False, server_default='EFECTIVO'),
    )
    op.alter_column('ventas', 'metodo_pago', server_default=None)
    op.create_check_constraint(
        'metodo_pago',
        'ventas',
        "metodo_pago IN ('EFECTIVO', 'QR', 'TRANSFERENCIA')",
    )
    op.drop_constraint('ck_ventas_confirmada_pagada', 'ventas', type_='check')
    op.drop_constraint('ck_ventas_total_pagado_hasta_total', 'ventas', type_='check')
    op.drop_constraint('ck_ventas_total_pagado_no_negativo', 'ventas', type_='check')
    op.drop_column('ventas', 'total_pagado')
    op.drop_index('venta_pagos_idx_venta_pagos_venta', table_name='venta_pagos')
    op.drop_index('venta_pagos_idx_venta_pagos_metodo_created_at', table_name='venta_pagos')
    op.drop_index(op.f('ix_public_venta_pagos_is_deleted'), table_name='venta_pagos')
    op.drop_table('venta_pagos')
