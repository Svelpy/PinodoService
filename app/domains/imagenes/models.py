from uuid import UUID

from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import Index, case
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


# Orden de la galería: primero las fotos con modelo, luego la prenda sola y al
# final los detalles; dentro de cada tipo, por orden de subida.
GALERIA_ORDER = (
    case(
        (Imagen.tipo == TipoImagen.MODELO, 0),
        (Imagen.tipo == TipoImagen.PRENDA, 1),
        else_=2,
    ),
    Imagen.created_at,
    Imagen.id,
)
