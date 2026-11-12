"""kardex_ajustes

El kardex deja de recibir movimientos sueltos: los cambios manuales de stock
pasan a ser ajustes con un motivo de una lista fija.

- tipo: INGRESO se reemplaza por INICIAL (stock con que nace un SKU) y la
  entrada de mercadería pasa a ser un AJUSTE con motivo RECEPCION.
- motivo pasa de texto libre a MotivoAjuste (solo en AJUSTE), y el texto libre
  queda en la nueva columna nota.

Datos: los INGRESO de saldo o stock inicial pasan a INICIAL sin nota; otro
INGRESO pasa a AJUSTE RECEPCION y un AJUSTE a CORRECCION, ambos conservando su
texto como nota. VENTA y ANULACION pierden su texto, que repetía el tipo.

Revision ID: e5a9c3b71d20
Revises: c7d4a1e9f203
Create Date: 2026-11-11 23:40:00.000000

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

TABLE = 'movimientos_inventario'
INICIALES = "('Saldo inicial del kardex', 'Stock inicial')"


def upgrade() -> None:
    """Pasa a tipos INICIAL/AJUSTE/VENTA/ANULACION con motivo de ajuste y nota."""
    op.drop_constraint('ck_movimientos_inventario_signo', TABLE, type_='check')
    op.drop_constraint('tipo_movimiento', TABLE, type_='check')
    op.alter_column(TABLE, 'motivo', new_column_name='nota')
    op.add_column(TABLE, sa.Column('motivo', sa.String(length=20), nullable=True))

    op.execute(f"""
        UPDATE public.{TABLE} SET tipo = 'INICIAL', nota = NULL
        WHERE tipo = 'INGRESO' AND (nota IS NULL OR nota IN {INICIALES})
    """)
    op.execute(f"UPDATE public.{TABLE} SET tipo = 'AJUSTE', motivo = 'RECEPCION' WHERE tipo = 'INGRESO'")
    op.execute(f"UPDATE public.{TABLE} SET motivo = 'CORRECCION', nota = coalesce(nota, 'Ajuste') WHERE tipo = 'AJUSTE' AND motivo IS NULL")
    op.execute(f"UPDATE public.{TABLE} SET nota = NULL WHERE tipo IN ('VENTA', 'ANULACION')")

    op.create_check_constraint(
        'tipo_movimiento', TABLE, "tipo IN ('INICIAL', 'AJUSTE', 'VENTA', 'ANULACION')"
    )
    op.create_check_constraint(
        'motivo_ajuste', TABLE,
        "motivo IN ('RECEPCION', 'CONTEO', 'MERMA', 'ROBO_PERDIDA', 'CORRECCION')",
    )
    op.create_check_constraint(
        'ck_movimientos_inventario_signo', TABLE,
        "(tipo IN ('INICIAL', 'ANULACION') AND cantidad > 0) "
        "OR (tipo = 'VENTA' AND cantidad < 0) OR tipo = 'AJUSTE'",
    )
    op.create_check_constraint(
        'ck_movimientos_inventario_motivo', TABLE, "(tipo = 'AJUSTE') = (motivo IS NOT NULL)"
    )
    op.create_check_constraint(
        'ck_movimientos_inventario_signo_motivo', TABLE,
        "motivo IS NULL OR motivo IN ('CONTEO', 'CORRECCION') "
        "OR (motivo = 'RECEPCION' AND cantidad > 0) "
        "OR (motivo IN ('MERMA', 'ROBO_PERDIDA') AND cantidad < 0)",
    )
    op.create_check_constraint(
        'ck_movimientos_inventario_anterior_no_negativo', TABLE, 'saldo - cantidad >= 0'
    )


def downgrade() -> None:
    """Vuelve a INGRESO/AJUSTE con motivo de texto libre."""
    for name in (
        'ck_movimientos_inventario_anterior_no_negativo',
        'ck_movimientos_inventario_signo_motivo',
        'ck_movimientos_inventario_motivo',
        'ck_movimientos_inventario_signo',
        'motivo_ajuste',
        'tipo_movimiento',
    ):
        op.drop_constraint(name, TABLE, type_='check')

    op.execute(f"UPDATE public.{TABLE} SET tipo = 'INGRESO', nota = 'Stock inicial' WHERE tipo = 'INICIAL'")
    op.execute(f"""
        UPDATE public.{TABLE} SET tipo = 'INGRESO'
        WHERE tipo = 'AJUSTE' AND motivo = 'RECEPCION'
    """)
    op.execute(f"""
        UPDATE public.{TABLE} SET nota = coalesce(nota, initcap(replace(motivo, '_', ' ')))
        WHERE motivo IS NOT NULL
    """)
    op.execute(f"UPDATE public.{TABLE} SET nota = 'Venta confirmada' WHERE tipo = 'VENTA'")
    op.execute(f"UPDATE public.{TABLE} SET nota = 'Venta anulada' WHERE tipo = 'ANULACION'")
    op.drop_column(TABLE, 'motivo')
    op.alter_column(
        TABLE, 'nota', new_column_name='motivo',
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=200),
    )

    op.create_check_constraint(
        'tipo_movimiento', TABLE, "tipo IN ('INGRESO', 'VENTA', 'ANULACION', 'AJUSTE')"
    )
    op.create_check_constraint(
        'ck_movimientos_inventario_signo', TABLE,
        "(tipo IN ('INGRESO', 'ANULACION') AND cantidad > 0) "
        "OR (tipo = 'VENTA' AND cantidad < 0) OR tipo = 'AJUSTE'",
    )
