from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlmodel import Field, Relationship

from app.core.base_model import BaseModel
from app.domains.ajustes_inventario.models import AjusteInventario
from app.domains.ventas.models import Venta
from app.shared.enums import TipoMovimiento


class MovimientoInventario(BaseModel, table=True):
    """
    Kardex: libro de movimientos de stock. Cada cambio de stock de un SKU
    queda como una fila que no se edita ni se elimina, y el stock del SKU es
    el saldo de su último movimiento. Ninguna ruta escribe aquí directamente:
    cada fila la registra el documento que la causa.

    - AJUSTE: un documento de ajustes_inventario (ajuste_id). Con costo
      (INICIAL, RECEPCION) recalcula el costo promedio; sin él usa el actual.
    - VENTA: sale al confirmar una venta (venta_id), al costo promedio.
    - ANULACION: vuelve al cancelar esa venta, al costo con que salió.

    costo_promedio es el costo del SKU después del movimiento, para valorizar
    el saldo (saldo × costo_promedio) en cualquier punto del kardex.

    user_id es el usuario responsable del movimiento, con foreign key a
    usuarios. created_by sigue siendo auditoría y no tiene foreign key.
    """

    __tablename__ = "movimientos_inventario"
    __table_args__ = (
        Index("movimientos_inventario_idx_sku_created_at", "sku_id", "created_at"),
        Index("movimientos_inventario_idx_venta", "venta_id"),
        Index("movimientos_inventario_idx_ajuste", "ajuste_id"),
        Index("movimientos_inventario_idx_tipo_created_at", "tipo", "created_at"),
        Index("movimientos_inventario_idx_user_created_at", "user_id", "created_at"),
        CheckConstraint("cantidad <> 0", name="ck_movimientos_inventario_cantidad_no_cero"),
        CheckConstraint("saldo >= 0", name="ck_movimientos_inventario_saldo_no_negativo"),
        CheckConstraint("saldo - cantidad >= 0", name="ck_movimientos_inventario_anterior_no_negativo"),
        CheckConstraint("costo_unitario >= 0", name="ck_movimientos_inventario_costo_no_negativo"),
        CheckConstraint("costo_promedio >= 0", name="ck_movimientos_inventario_promedio_no_negativo"),
        CheckConstraint(
            "(tipo = 'ANULACION' AND cantidad > 0) OR (tipo = 'VENTA' AND cantidad < 0) OR tipo = 'AJUSTE'",
            name="ck_movimientos_inventario_signo",
        ),
        CheckConstraint(
            "(tipo IN ('VENTA', 'ANULACION')) = (venta_id IS NOT NULL)",
            name="ck_movimientos_inventario_venta",
        ),
        CheckConstraint(
            "(tipo = 'AJUSTE') = (ajuste_id IS NOT NULL)",
            name="ck_movimientos_inventario_ajuste",
        ),
        {"schema": "public"},
    )

    sku_id: UUID = Field(foreign_key="public.skus.id", nullable=False)
    tipo: TipoMovimiento = Field(sa_type=SQLAlchemyEnum(TipoMovimiento,name="tipo_movimiento",native_enum=False,create_constraint=True,length=20),nullable=False)
    # Positiva si entra, negativa si sale.
    cantidad: int = Field(nullable=False)
    # Stock del SKU después del movimiento.
    saldo: int = Field(nullable=False)
    costo_unitario: Decimal = Field(sa_type=Numeric(12, 2), nullable=False)
    costo_promedio: Decimal = Field(sa_type=Numeric(12, 2), nullable=False)
    # Documento de origen: un ajuste o una venta, nunca ambos.
    ajuste_id: UUID | None = Field(default=None, foreign_key="public.ajustes_inventario.id", nullable=True)
    venta_id: UUID | None = Field(default=None, foreign_key="public.ventas.id", nullable=True)
    # Usuario responsable: quien registró el ajuste, confirmó o anuló la venta.
    user_id: UUID = Field(foreign_key="public.usuarios.id", nullable=False)

    ajuste: AjusteInventario | None = Relationship(sa_relationship_kwargs={"lazy": "raise"})
    venta: Venta | None = Relationship(sa_relationship_kwargs={"lazy": "raise"})
