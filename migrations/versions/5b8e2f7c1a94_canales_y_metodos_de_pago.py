"""canales y metodos de pago

Amplía los CHECK de ventas.canal (canal_venta) y venta_pagos.metodo
(metodo_pago) a los valores actuales de CanalVenta y MetodoPago. Los enums no
son nativos, así que autogenerate no detecta el cambio de valores: se escribe
a mano.

Las listas se copian aquí en lugar de importar los enums, para que la
migración no cambie si el código cambia después.

Revision ID: 5b8e2f7c1a94
Revises: cda1265a4278
Create Date: 2026-11-11 19:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5b8e2f7c1a94'
down_revision: Union[str, Sequence[str], None] = 'cda1265a4278'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CANALES = (
    'TIENDA',
    'WHATSAPP',
    'TIKTOK_LIVE',
    'TIKTOK',
    'INSTAGRAM',
    'FACEBOOK',
    'PAGINA_WEB',
    'OTROS',
)
CANALES_ANTERIORES = ('WHATSAPP', 'TIENDA')

METODOS = ('EFECTIVO', 'TARJETA', 'CHEQUE', 'VALES', 'OTROS', 'QR', 'TRANSFERENCIA')
METODOS_ANTERIORES = ('EFECTIVO', 'QR', 'TRANSFERENCIA')


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _replace_check(name: str, table: str, column: str, values: Sequence[str]) -> None:
    op.drop_constraint(name, table, type_='check')
    op.create_check_constraint(name, table, _in(column, values))


def upgrade() -> None:
    """Amplía los valores admitidos de ventas.canal y venta_pagos.metodo."""
    _replace_check('canal_venta', 'ventas', 'canal', CANALES)
    _replace_check('metodo_pago', 'venta_pagos', 'metodo', METODOS)


def downgrade() -> None:
    """
    Restaura los valores anteriores. Falla, y no cambia nada, si alguna venta
    o pago usa un valor nuevo: hay que reasignarlos antes de revertir.
    """
    _replace_check('metodo_pago', 'venta_pagos', 'metodo', METODOS_ANTERIORES)
    _replace_check('canal_venta', 'ventas', 'canal', CANALES_ANTERIORES)
