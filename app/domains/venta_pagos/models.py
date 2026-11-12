from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlmodel import Field

from app.core.base_model import BaseModel
from app.shared.enums import MetodoPago


class VentaPago(BaseModel, table=True):
    """
    Cobro de una venta, registrado a mano (sin pasarela). Una venta puede tener
    varios (pagos mixtos), registrados todos juntos al cobrarla y cubriendo su
    total exacto: no hay anticipos. Un pago no se anula ni se reembolsa por
    separado: la devolución se hace anulando la venta completa, que devuelve
    todos sus pagos en cancelada_at. Su suma se guarda en Venta.total_pagado.
    """

    __tablename__ = "venta_pagos"
    __table_args__ = (
        Index("venta_pagos_idx_venta_pagos_venta", "venta_id"),
        # Conciliación y arqueo: pagos de un método en un rango de fechas.
        Index("venta_pagos_idx_venta_pagos_metodo_created_at", "metodo", "created_at"),
        CheckConstraint("monto > 0", name="ck_venta_pagos_monto_positivo"),
        {"schema": "public"},
    )

    venta_id: UUID = Field(foreign_key="public.ventas.id", nullable=False)
    metodo: MetodoPago = Field(sa_type=SQLAlchemyEnum(MetodoPago,name="metodo_pago",native_enum=False,create_constraint=True,length=20,),nullable=False,)
    # Monto aplicado a la venta; en efectivo no incluye el vuelto.
    monto: Decimal = Field(sa_type=Numeric(12, 2), nullable=False)
    # Número de operación del QR o de la transferencia, para conciliar con el banco.
    referencia: str | None = Field(default=None, max_length=100, nullable=True)
    comprobante_url: str | None = Field(default=None, max_length=500, nullable=True)
