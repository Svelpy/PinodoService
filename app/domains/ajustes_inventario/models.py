from sqlalchemy import BigInteger, Column, Identity, Index
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlmodel import Field

from app.core.base_model import BaseModel
from app.shared.enums import MotivoAjuste


class AjusteInventario(BaseModel, table=True):
    """
    Documento de un ajuste de stock: la cabecera que agrupa los movimientos
    AJUSTE del kardex registrados en una misma operación, con su motivo y su
    nota. No se edita ni se elimina, igual que sus movimientos.

    INICIAL lo genera el sistema al crear SKUs con stock (uno por petición);
    los demás motivos, POST /ajustes-inventario/.
    """

    __tablename__ = "ajustes_inventario"
    __table_args__ = (
        Index("uq_ajustes_inventario_numero", "numero", unique=True),
        Index("ajustes_inventario_idx_motivo_created_at", "motivo", "created_at"),
        {"schema": "public"},
    )

    # Correlativo para mostrar ("Ajuste #12"). Una operación que falla puede
    # dejar un salto en la numeración, igual que en las ventas.
    numero: int | None = Field(default=None,sa_column=Column(BigInteger, Identity(always=True, start=1), nullable=False))
    motivo: MotivoAjuste = Field(sa_type=SQLAlchemyEnum(MotivoAjuste,name="motivo_ajuste",native_enum=False,create_constraint=True,length=20),nullable=False)
    # Texto libre ("Factura 4521"); obligatorio en CORRECCION.
    nota: str | None = Field(default=None, max_length=200, nullable=True)
