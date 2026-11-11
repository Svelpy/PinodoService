"""kardex_costos

Costo + kardex: crea movimientos_inventario, agrega skus.costo (costo promedio
ponderado) y venta_items.costo_unitario (costo copiado al confirmar).

Datos: cada SKU activo con stock recibe un INGRESO inicial por su cantidad
actual, a costo 0, para que su saldo en el kardex coincida con su stock. El
costo real se carga después editando el SKU. Los ítems de ventas ya
confirmadas quedan con costo_unitario null (sin costo conocido).

Revision ID: cda1265a4278
Revises: 39ee24dca294
Create Date: 2026-11-11 16:24:48.174157

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'cda1265a4278'
down_revision: Union[str, Sequence[str], None] = '39ee24dca294'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea el kardex, agrega los costos y registra el saldo inicial de cada SKU."""
    op.create_table('movimientos_inventario',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Uuid(), nullable=True),
    sa.Column('sku_id', sa.Uuid(), nullable=False),
    sa.Column('tipo', sa.Enum('INGRESO', 'VENTA', 'ANULACION', 'AJUSTE', name='tipo_movimiento', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('cantidad', sa.Integer(), nullable=False),
    sa.Column('saldo', sa.Integer(), nullable=False),
    sa.Column('costo_unitario', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('costo_promedio', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('motivo', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
    sa.Column('venta_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("(tipo IN ('INGRESO', 'ANULACION') AND cantidad > 0) OR (tipo = 'VENTA' AND cantidad < 0) OR tipo = 'AJUSTE'", name='ck_movimientos_inventario_signo'),
    sa.CheckConstraint("(tipo IN ('VENTA', 'ANULACION')) = (venta_id IS NOT NULL)", name='ck_movimientos_inventario_venta'),
    sa.CheckConstraint('cantidad <> 0', name='ck_movimientos_inventario_cantidad_no_cero'),
    sa.CheckConstraint('costo_promedio >= 0', name='ck_movimientos_inventario_promedio_no_negativo'),
    sa.CheckConstraint('costo_unitario >= 0', name='ck_movimientos_inventario_costo_no_negativo'),
    sa.CheckConstraint('saldo >= 0', name='ck_movimientos_inventario_saldo_no_negativo'),
    sa.ForeignKeyConstraint(['sku_id'], ['skus.id'], ),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_public_movimientos_inventario_is_deleted'), 'movimientos_inventario', ['is_deleted'], unique=False)
    op.create_index('movimientos_inventario_idx_sku_created_at', 'movimientos_inventario', ['sku_id', 'created_at'], unique=False)
    op.create_index('movimientos_inventario_idx_tipo_created_at', 'movimientos_inventario', ['tipo', 'created_at'], unique=False)
    op.create_index('movimientos_inventario_idx_venta', 'movimientos_inventario', ['venta_id'], unique=False)
    op.add_column(
        'skus',
        sa.Column('costo', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
    )
    op.alter_column('skus', 'costo', server_default=None)
    op.create_check_constraint('ck_skus_costo_no_negativo', 'skus', 'costo >= 0')
    op.add_column('venta_items', sa.Column('costo_unitario', sa.Numeric(precision=12, scale=2), nullable=True))
    op.create_check_constraint('ck_venta_items_costo_no_negativo', 'venta_items', 'costo_unitario >= 0')

    op.execute(
        """
        INSERT INTO public.movimientos_inventario (
            id, created_at, updated_at, is_deleted,
            sku_id, tipo, cantidad, saldo, costo_unitario, costo_promedio, motivo
        )
        SELECT
            gen_random_uuid(), now(), now(), false,
            id, 'INGRESO', (stock->>'cantidad')::int, (stock->>'cantidad')::int, 0, 0,
            'Saldo inicial del kardex'
        FROM public.skus
        WHERE is_deleted = false AND (stock->>'cantidad')::int > 0
        """
    )


def downgrade() -> None:
    """Elimina el kardex y los costos; el stock de cada SKU no cambia."""
    op.drop_constraint('ck_venta_items_costo_no_negativo', 'venta_items', type_='check')
    op.drop_column('venta_items', 'costo_unitario')
    op.drop_constraint('ck_skus_costo_no_negativo', 'skus', type_='check')
    op.drop_column('skus', 'costo')
    op.drop_index('movimientos_inventario_idx_venta', table_name='movimientos_inventario')
    op.drop_index('movimientos_inventario_idx_tipo_created_at', table_name='movimientos_inventario')
    op.drop_index('movimientos_inventario_idx_sku_created_at', table_name='movimientos_inventario')
    op.drop_index(op.f('ix_public_movimientos_inventario_is_deleted'), table_name='movimientos_inventario')
    op.drop_table('movimientos_inventario')
