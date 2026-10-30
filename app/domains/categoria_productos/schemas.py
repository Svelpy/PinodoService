from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.categorias.schemas import CategoriaResponse
from app.domains.productos.schemas import ProductoResponse


class CategoriaProductoCreate(BaseModel):
    categoria_id: UUID = Field(...)
    producto_id: UUID = Field(...)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "categoria_id": "44444444-4444-4444-8444-444444444444",
                "producto_id": "55555555-5555-4555-8555-555555555555",
            }
        },
    )


class CategoriaProductoUpdate(BaseModel):
    categoria_id: UUID | None = Field(default=None)
    producto_id: UUID | None = Field(default=None)

    @field_validator("categoria_id")
    @classmethod
    def validate_categoria_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("La categoría no puede ser null.")
        return value

    @field_validator("producto_id")
    @classmethod
    def validate_producto_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("El producto no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "categoria_id": "66666666-6666-4666-8666-666666666666",
            }
        },
    )


class CategoriaProductoResponse(BaseModel):
    id: UUID
    categoria_id: UUID
    producto_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "categoria_id": "44444444-4444-4444-8444-444444444444",
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class CategoriaProductoResponseAudit(CategoriaProductoResponse):
    created_by: UUID | None
    updated_by: UUID | None
    is_deleted: bool
    deleted_at: datetime | None
    deleted_by: UUID | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "categoria_id": "44444444-4444-4444-8444-444444444444",
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "created_at": "2026-10-29T14:30:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-10-29T15:00:00Z",
                "updated_by": "22222222-2222-4222-8222-222222222222",
                "is_deleted": False,
                "deleted_at": None,
                "deleted_by": None,
            }
        },
    )


class CategoriaProductoListItem(CategoriaProductoResponse):
    """Tabla de enlace: ambas foreign keys son referencia y se embeben."""

    categoria: CategoriaResponse
    producto: ProductoResponse

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **CategoriaProductoResponse.model_json_schema()["example"],
                "categoria": CategoriaResponse.model_json_schema()["example"],
                "producto": ProductoResponse.model_json_schema()["example"],
            }
        },
    )


class CategoriaProductoDetail(CategoriaProductoListItem):
    """Sin hijos propios: no añade campos respecto a CategoriaProductoListItem."""
