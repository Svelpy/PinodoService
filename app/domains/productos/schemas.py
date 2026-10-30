from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.categorias.schemas import CategoriaResponse
from app.domains.producto_colores.schemas import ProductoColorDetail
from app.domains.secciones.schemas import SeccionResponse
from app.shared.services.validators import validator_boolean, validator_non_empty_text


class ProductoCreate(BaseModel):
    seccion_id: UUID = Field(...)
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str | None = Field(default=None, min_length=1)
    cuidados: str | None = Field(default=None, min_length=1)
    composicion: str | None = Field(default=None, min_length=1)
    is_visible: bool = Field(default=True)

    @field_validator("nombre", mode="before")
    @classmethod
    def validate_nombre(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre no puede ser null.")
        return validator_non_empty_text(value)

    @field_validator("descripcion", "cuidados", "composicion", mode="before")
    @classmethod
    def validate_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_non_empty_text(value)

    @field_validator("is_visible", mode="before")
    @classmethod
    def validate_is_visible(cls, value: object) -> bool:
        if value is None:
            raise ValueError("La visibilidad no puede ser null.")
        return validator_boolean(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "seccion_id": "33333333-3333-4333-8333-333333333333",
                "nombre": "Camisa Oxford",
                "descripcion": "Camisa de corte regular confeccionada en tejido Oxford.",
                "cuidados": "Lavar a máquina a 30 °C. No usar secadora.",
                "composicion": "100 % algodón",
                "is_visible": False,
            }
        },
    )


class ProductoUpdate(BaseModel):
    seccion_id: UUID | None = Field(default=None)
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    descripcion: str | None = Field(default=None, min_length=1)
    cuidados: str | None = Field(default=None, min_length=1)
    composicion: str | None = Field(default=None, min_length=1)
    is_visible: bool | None = Field(default=None)

    @field_validator("seccion_id")
    @classmethod
    def validate_seccion_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("La sección no puede ser null.")
        return value

    @field_validator("nombre", mode="before")
    @classmethod
    def validate_nombre(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre no puede ser null.")
        return validator_non_empty_text(value)

    @field_validator("descripcion", "cuidados", "composicion", mode="before")
    @classmethod
    def validate_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_non_empty_text(value)

    @field_validator("is_visible", mode="before")
    @classmethod
    def validate_is_visible(cls, value: object) -> bool:
        if value is None:
            raise ValueError("La visibilidad no puede ser null.")
        return validator_boolean(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "seccion_id": "33333333-3333-4333-8333-333333333333",
                "nombre": "Camisa Oxford slim",
                "descripcion": "Camisa de corte slim confeccionada en tejido Oxford.",
                "cuidados": "Lavar a máquina a 30 °C. No usar secadora.",
                "composicion": "100 % algodón",
                "is_visible": True,
            }
        },
    )


class ProductoResponse(BaseModel):
    id: UUID
    seccion_id: UUID
    nombre: str
    descripcion: str | None
    cuidados: str | None
    composicion: str | None
    is_visible: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "seccion_id": "33333333-3333-4333-8333-333333333333",
                "nombre": "Camisa Oxford",
                "descripcion": "Camisa de corte regular confeccionada en tejido Oxford.",
                "cuidados": "Lavar a máquina a 30 °C. No usar secadora.",
                "composicion": "100 % algodón",
                "is_visible": True,
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class ProductoResponseAudit(ProductoResponse):
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
                "seccion_id": "33333333-3333-4333-8333-333333333333",
                "nombre": "Camisa Oxford",
                "descripcion": "Camisa de corte regular confeccionada en tejido Oxford.",
                "cuidados": "Lavar a máquina a 30 °C. No usar secadora.",
                "composicion": "100 % algodón",
                "is_visible": True,
                "created_at": "2026-10-29T14:30:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-10-29T15:00:00Z",
                "updated_by": "22222222-2222-4222-8222-222222222222",
                "is_deleted": False,
                "deleted_at": "2026-10-30T09:00:00Z",
                "deleted_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )


class ProductoListItem(ProductoResponse):
    """seccion es referencia y se embebe."""

    seccion: SeccionResponse

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **ProductoResponse.model_json_schema()["example"],
                "seccion": SeccionResponse.model_json_schema()["example"],
            }
        },
    )


class ProductoDetail(ProductoListItem):
    """
    Añade sus hijos propios (colores, con sus imágenes y SKUs) y sus categorías.

    categorias es una asociación N:M acotada: se embebe el extremo lejano sin
    exponer la tabla de enlace categoria_productos.
    """

    categorias: list[CategoriaResponse]
    colores: list[ProductoColorDetail]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **ProductoListItem.model_json_schema()["example"],
                "categorias": [CategoriaResponse.model_json_schema()["example"]],
                "colores": [ProductoColorDetail.model_json_schema()["example"]],
            }
        },
    )
