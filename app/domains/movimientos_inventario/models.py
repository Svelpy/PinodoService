from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlmodel import Field, Relationship

from app.core.base_model import BaseModel
from app.domains.skus.models import Sku
from app.domains.ventas.models import Venta
from app.shared.enums import MotivoAjuste, TipoMovimiento


class MovimientoInventario(BaseModel, table=True):
    """
    Kardex: cada cambio de stock de un SKU queda como un movimiento que no se
    edita ni se elimina. El stock del SKU es el saldo de su último movimiento.
    Ninguna ruta escribe aquí directamente: cada movimiento lo registra la
    operación que lo causa.

    - INICIAL: stock con que nace un SKU, a su costo.
    - AJUSTE: ajuste manual con un motivo. RECEPCION entra a costo_unitario y
      recalcula el costo promedio; CONTEO, MERMA, ROBO_PERDIDA y CORRECCION
      usan el costo actual y no lo cambian.
    - VENTA: sale al confirmar una venta, al costo promedio del momento.
    - ANULACION: vuelve al cancelar una venta confirmada, al costo con que salió.

    costo_promedio es el costo del SKU después del movimiento, para valorizar
    el saldo (saldo × costo_promedio) en cualquier punto del kardex.
    """

    __tablename__ = "movimientos_inventario"
    __table_args__ = (
        Index("movimientos_inventario_idx_sku_created_at", "sku_id", "created_at"),
        Index("movimientos_inventario_idx_venta", "venta_id"),
        Index("movimientos_inventario_idx_tipo_created_at", "tipo", "created_at"),
        CheckConstraint("cantidad <> 0", name="ck_movimientos_inventario_cantidad_no_cero"),
        CheckConstraint("saldo >= 0", name="ck_movimientos_inventario_saldo_no_negativo"),
        CheckConstraint("saldo - cantidad >= 0", name="ck_movimientos_inventario_anterior_no_negativo"),
        CheckConstraint("costo_unitario >= 0", name="ck_movimientos_inventario_costo_no_negativo"),
        CheckConstraint("costo_promedio >= 0", name="ck_movimientos_inventario_promedio_no_negativo"),
        CheckConstraint(
            "(tipo IN ('INICIAL', 'ANULACION') AND cantidad > 0) "
            "OR (tipo = 'VENTA' AND cantidad < 0) OR tipo = 'AJUSTE'",
            name="ck_movimientos_inventario_signo",
        ),
        CheckConstraint(
            "(tipo IN ('VENTA', 'ANULACION')) = (venta_id IS NOT NULL)",
            name="ck_movimientos_inventario_venta",
        ),
        CheckConstraint(
            "(tipo = 'AJUSTE') = (motivo IS NOT NULL)",
            name="ck_movimientos_inventario_motivo",
        ),
        CheckConstraint(
            "motivo IS NULL OR motivo IN ('CONTEO', 'CORRECCION') "
            "OR (motivo = 'RECEPCION' AND cantidad > 0) "
            "OR (motivo IN ('MERMA', 'ROBO_PERDIDA') AND cantidad < 0)",
            name="ck_movimientos_inventario_signo_motivo",
        ),
        {"schema": "public"},
    )

    sku_id: UUID = Field(foreign_key="public.skus.id", nullable=False)
    tipo: TipoMovimiento = Field(sa_type=SQLAlchemyEnum(TipoMovimiento,name="tipo_movimiento",native_enum=False,create_constraint=True,length=20),nullable=False)
    # Solo en AJUSTE.
    motivo: MotivoAjuste | None = Field(default=None, sa_type=SQLAlchemyEnum(MotivoAjuste,name="motivo_ajuste",native_enum=False,create_constraint=True,length=20),nullable=True)
    # Positiva si entra, negativa si sale.
    cantidad: int = Field(nullable=False)
    # Stock del SKU después del movimiento.
    saldo: int = Field(nullable=False)
    costo_unitario: Decimal = Field(sa_type=Numeric(12, 2), nullable=False)
    costo_promedio: Decimal = Field(sa_type=Numeric(12, 2), nullable=False)
    # Texto libre del ajuste ("Lote de noviembre"); obligatorio en CORRECCION.
    nota: str | None = Field(default=None, max_length=200, nullable=True)
    venta_id: UUID | None = Field(default=None, foreign_key="public.ventas.id", nullable=True)

    sku: Sku | None = Relationship(sa_relationship_kwargs={"lazy": "raise"})
    venta: Venta | None = Relationship(sa_relationship_kwargs={"lazy": "raise"})
