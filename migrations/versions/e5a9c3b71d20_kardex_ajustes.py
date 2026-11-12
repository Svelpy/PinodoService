"""kardex_ajustes

El kardex pasa a ser un libro de movimientos en el que cada fila apunta a su
documento de origen: un ajuste (ajustes_inventario) o una venta.

- Crea ajustes_inventario: documento con número correlativo, motivo
  (INICIAL, RECEPCION, CONTEO, MERMA, ROBO_PERDIDA, CORRECCION) y nota.
- movimientos_inventario: agrega ajuste_id; tipo queda AJUSTE, VENTA o
  ANULACION (INGRESO pasa a AJUSTE) y se quita motivo, que pasa al documento.

Datos: los INGRESO y AJUSTE existentes se agrupan en documentos por instante,
autor, tipo y texto de motivo, que queda como nota. Un INGRESO de saldo o
stock inicial (o sin texto) es INICIAL; otro INGRESO, RECEPCION; un AJUSTE,
CORRECCION. El saldo inicial de la migración del kardex queda como un único
documento INICIAL.

Revision ID: e5a9c3b71d20
Revises: c7d4a1e9f203
Create Date: 2026-11-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e5a9c3b71d20'
down_revision: Union[str, Sequence[str], None] = 'c7d4a1e9f203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MOVIMIENTOS = 'movimientos_inventario'
MOTIVO_DOCUMENTO = """
    CASE
        WHEN m.tipo = 'INGRESO' AND (m.motivo IS NULL OR m.motivo IN ('Saldo inicial del kardex', 'Stock inicial'))
            THEN 'INICIAL'
        WHEN m.tipo = 'INGRESO' THEN 'RECEPCION'
        ELSE 'CORRECCION'
    END
"""


def upgrade() -> None:
    """Crea los documentos de ajuste y enlaza a ellos los movimientos."""
    op.create_table('ajustes_inventario',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Uuid(), nullable=True),
    sa.Column('numero', sa.BigInteger(), sa.Identity(always=True, start=1), nullable=False),
    sa.Column('motivo', sa.Enum('INICIAL', 'RECEPCION', 'CONTEO', 'MERMA', 'ROBO_PERDIDA', 'CORRECCION', name='motivo_ajuste', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('nota', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    schema='public'
    )
    op.create_index('ajustes_inventario_idx_motivo_created_at', 'ajustes_inventario', ['motivo', 'created_at'], unique=False, schema='public')
    op.create_index(op.f('ix_public_ajustes_inventario_is_deleted'), 'ajustes_inventario', ['is_deleted'], unique=False, schema='public')
    op.create_index('uq_ajustes_inventario_numero', 'ajustes_inventario', ['numero'], unique=True, schema='public')

    op.add_column(MOVIMIENTOS, sa.Column('ajuste_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(None, MOVIMIENTOS, 'ajustes_inventario', ['ajuste_id'], ['id'], referent_schema='public')
    op.create_index('movimientos_inventario_idx_ajuste', MOVIMIENTOS, ['ajuste_id'], unique=False)

    # Un documento por (instante, autor, tipo, texto), numerados por antigüedad.
    op.execute(f"""
        INSERT INTO public.ajustes_inventario (id, created_at, created_by, updated_at, updated_by, is_deleted, motivo, nota)
        SELECT gen_random_uuid(), g.created_at, g.created_by, g.created_at, g.created_by, false, g.motivo_documento, g.nota
        FROM (
            SELECT DISTINCT m.created_at, m.created_by, {MOTIVO_DOCUMENTO} AS motivo_documento, m.motivo AS nota
            FROM public.{MOVIMIENTOS} m
            WHERE m.tipo IN ('INGRESO', 'AJUSTE')
        ) g
        ORDER BY g.created_at
    """)
    op.execute(f"""
        UPDATE public.{MOVIMIENTOS} m SET ajuste_id = a.id
        FROM public.ajustes_inventario a
        WHERE m.tipo IN ('INGRESO', 'AJUSTE')
          AND a.created_at = m.created_at
          AND a.created_by IS NOT DISTINCT FROM m.created_by
          AND a.nota IS NOT DISTINCT FROM m.motivo
          AND a.motivo = {MOTIVO_DOCUMENTO}
    """)

    op.drop_constraint('ck_movimientos_inventario_signo', MOVIMIENTOS, type_='check')
    op.drop_constraint('tipo_movimiento', MOVIMIENTOS, type_='check')
    op.execute(f"UPDATE public.{MOVIMIENTOS} SET tipo = 'AJUSTE' WHERE tipo = 'INGRESO'")
    op.drop_column(MOVIMIENTOS, 'motivo')

    op.create_check_constraint('tipo_movimiento', MOVIMIENTOS, "tipo IN ('AJUSTE', 'VENTA', 'ANULACION')")
    op.create_check_constraint(
        'ck_movimientos_inventario_signo', MOVIMIENTOS,
        "(tipo = 'ANULACION' AND cantidad > 0) OR (tipo = 'VENTA' AND cantidad < 0) OR tipo = 'AJUSTE'",
    )
    op.create_check_constraint(
        'ck_movimientos_inventario_ajuste', MOVIMIENTOS, "(tipo = 'AJUSTE') = (ajuste_id IS NOT NULL)"
    )
    op.create_check_constraint(
        'ck_movimientos_inventario_anterior_no_negativo', MOVIMIENTOS, 'saldo - cantidad >= 0'
    )


def downgrade() -> None:
    """Vuelve a INGRESO/AJUSTE con motivo de texto libre y elimina los documentos."""
    for name in (
        'ck_movimientos_inventario_anterior_no_negativo',
        'ck_movimientos_inventario_ajuste',
        'ck_movimientos_inventario_signo',
        'tipo_movimiento',
    ):
        op.drop_constraint(name, MOVIMIENTOS, type_='check')

    op.add_column(MOVIMIENTOS, sa.Column('motivo', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True))
    op.execute(f"""
        UPDATE public.{MOVIMIENTOS} m
        SET tipo = CASE WHEN a.motivo IN ('INICIAL', 'RECEPCION') AND m.cantidad > 0 THEN 'INGRESO' ELSE 'AJUSTE' END,
            motivo = coalesce(a.nota, CASE a.motivo WHEN 'INICIAL' THEN 'Stock inicial'
                                                    ELSE initcap(replace(a.motivo, '_', ' ')) END)
        FROM public.ajustes_inventario a
        WHERE a.id = m.ajuste_id
    """)
    op.execute(f"UPDATE public.{MOVIMIENTOS} SET motivo = 'Venta confirmada' WHERE tipo = 'VENTA'")
    op.execute(f"UPDATE public.{MOVIMIENTOS} SET motivo = 'Venta anulada' WHERE tipo = 'ANULACION'")

    op.drop_index('movimientos_inventario_idx_ajuste', table_name=MOVIMIENTOS)
    op.drop_constraint('movimientos_inventario_ajuste_id_fkey', MOVIMIENTOS, type_='foreignkey')
    op.drop_column(MOVIMIENTOS, 'ajuste_id')

    op.create_check_constraint(
        'tipo_movimiento', MOVIMIENTOS, "tipo IN ('INGRESO', 'VENTA', 'ANULACION', 'AJUSTE')"
    )
    op.create_check_constraint(
        'ck_movimientos_inventario_signo', MOVIMIENTOS,
        "(tipo IN ('INGRESO', 'ANULACION') AND cantidad > 0) OR (tipo = 'VENTA' AND cantidad < 0) OR tipo = 'AJUSTE'",
    )

    op.drop_index('uq_ajustes_inventario_numero', table_name='ajustes_inventario', schema='public')
    op.drop_index(op.f('ix_public_ajustes_inventario_is_deleted'), table_name='ajustes_inventario', schema='public')
    op.drop_index('ajustes_inventario_idx_motivo_created_at', table_name='ajustes_inventario', schema='public')
    op.drop_table('ajustes_inventario', schema='public')
