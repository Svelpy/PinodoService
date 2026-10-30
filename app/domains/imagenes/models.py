from uuid import UUID

from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import Index
from sqlmodel import Field

from app.core.base_model import BaseModel
from app.shared.enums import TipoImagen


class Imagen(BaseModel, table=True):
    __tablename__ = "imagenes"
    __table_args__ = (
        Index("imagenes_idx_imagenes_prodcolor", "producto_color_id"),
        {"schema": "public"},
    )

    producto_color_id: UUID = Field(foreign_key="public.producto_colores.id",nullable=False)
    url: str = Field(max_length=500, nullable=False)
    tipo: TipoImagen = Field(default=TipoImagen.MODELO,sa_type=SQLAlchemyEnum(TipoImagen,name="tipo_imagen",native_enum=False,create_constraint=True,length=20,),nullable=False,)
