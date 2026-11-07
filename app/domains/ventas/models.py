from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Identity, Index, Numeric, Text
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlmodel import Field, Relationship

from app.core.base_model import BaseModel
from app.domains.venta_items.models import VentaItem
from app.shared.enums import CanalVenta, EstadoVenta, MetodoPago


class Venta(BaseModel, table=True):
    """
    Venta registrada por un usuario de la tienda (created_by), sin cliente
    registrado ni pasarela de pagos.
    """

    __tablename__ = "ventas"
    __table_args__ = (
        Index("uq_ventas_numero", "numero", unique=True),
        Index("ventas_idx_ventas_created_by", "created_by"),
        Index("ventas_idx_ventas_estado", "estado"),
        Index("ventas_idx_ventas_created_at", "created_at"),
        CheckConstraint("subtotal >= 0", name="ck_ventas_subtotal_no_negativo"),
        CheckConstraint("descuento >= 0", name="ck_ventas_descuento_no_negativo"),
        CheckConstraint("descuento <= subtotal", name="ck_ventas_descuento_hasta_subtotal"),
        CheckConstraint("total = subtotal - descuento", name="ck_ventas_total"),
        {"schema": "public"},
    )

    # Número legible (#1, #2...). Lo genera PostgreSQL; nunca se envía en un INSERT.
    numero: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, Identity(always=True, start=1), nullable=False),
    )
    canal: CanalVenta = Field(default=CanalVenta.WHATSAPP,sa_type=SQLAlchemyEnum(CanalVenta,name="canal_venta",native_enum=False,create_constraint=True,length=20,),nullable=False,)
    estado: EstadoVenta = Field(default=EstadoVenta.PENDIENTE,sa_type=SQLAlchemyEnum(EstadoVenta,name="estado_venta",native_enum=False,create_constraint=True,length=20,),nullable=False,)
    metodo_pago: MetodoPago = Field(default=MetodoPago.EFECTIVO,sa_type=SQLAlchemyEnum(MetodoPago,name="metodo_pago",native_enum=False,create_constraint=True,length=20,),nullable=False,)
    referencia: str | None = Field(default=None, max_length=150, nullable=True)
    cliente_telefono: str | None = Field(default=None, max_length=30, nullable=True)
    subtotal: Decimal = Field(default=Decimal("0"), sa_type=Numeric(12, 2), nullable=False)
    descuento: Decimal = Field(default=Decimal("0"), sa_type=Numeric(12, 2), nullable=False)
    total: Decimal = Field(default=Decimal("0"), sa_type=Numeric(12, 2), nullable=False)
    nota: str | None = Field(default=None, sa_type=Text, nullable=True)
    confirmada_at: datetime | None = Field(default=None,sa_type=DateTime(timezone=True),nullable=True)
    cancelada_at: datetime | None = Field(default=None,sa_type=DateTime(timezone=True),nullable=True)

    # Los repositories la cargan filtrando los ítems eliminados.
    items: list[VentaItem] = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise",
            "order_by": "(VentaItem.created_at, VentaItem.id)",
        }
    )
