from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.secciones.schemas import SeccionResponse
from app.shared.schemas.tree import TreeResponse
from app.shared.services.validators import validator_boolean, validator_slug_source


class CategoriaCreate(BaseModel):
    seccion_id: UUID = Field(...)
    parent_id: UUID | None = Field(default=None)
    nombre: str = Field(..., min_length=1, max_length=100)
    is_visible: bool = Field(default=True)

    @field_validator("nombre", mode="before")
    @classmethod
    def validate_nombre(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre no puede ser null.")
        return validator_slug_source(value)

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
                "parent_id": "44444444-4444-4444-8444-444444444444",
                "nombre": "Bombers",
                "is_visible": True,
            }
        },
    )


class CategoriaUpdate(BaseModel):
    """parent_id puede cambiarse para mover la categoría dentro del árbol; null la convierte en raíz."""

    seccion_id: UUID | None = Field(default=None)
    parent_id: UUID | None = Field(default=None)
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
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
        return validator_slug_source(value)

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
                "parent_id": None,
                "nombre": "Cazadoras bomber",
                "is_visible": True,
            }
        },
    )


class CategoriaResponse(BaseModel):
    id: UUID
    seccion_id: UUID
    parent_id: UUID | None
    nombre: str
    slug: str
    is_visible: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "seccion_id": "33333333-3333-4333-8333-333333333333",
                "parent_id": "44444444-4444-4444-8444-444444444444",
                "nombre": "Bombers",
                "slug": "bombers",
                "is_visible": True,
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class CategoriaResponseAudit(CategoriaResponse):
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
                "parent_id": "44444444-4444-4444-8444-444444444444",
                "nombre": "Bombers",
                "slug": "bombers",
                "is_visible": True,
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


class CategoriaListItem(CategoriaResponse):
    """seccion es referencia y se embebe; parent_id es dueño y queda como id."""

    seccion: SeccionResponse

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **CategoriaResponse.model_json_schema()["example"],
                "seccion": SeccionResponse.model_json_schema()["example"],
            }
        },
    )


class CategoriaDetail(CategoriaListItem):
    """
    Jerarquía autorreferenciada: las subcategorías bajan un solo nivel como ListItem.

    El árbol completo se expone con los schemas de shared/schemas/tree.py.
    """

    subcategorias: list[CategoriaListItem]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **CategoriaListItem.model_json_schema()["example"],
                "subcategorias": [
                    {
                        **CategoriaListItem.model_json_schema()["example"],
                        "id": "66666666-6666-4666-8666-666666666666",
                        "parent_id": "11111111-1111-4111-8111-111111111111",
                        "nombre": "Bombers acolchadas",
                        "slug": "bombers-acolchadas",
                    }
                ],
            }
        },
    )


class CategoriaArbolSeccion(BaseModel):
    """Una sección con el árbol completo de sus categorías."""

    seccion: SeccionResponse
    categorias: TreeResponse[CategoriaResponse]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "seccion": SeccionResponse.model_json_schema()["example"],
                "categorias": {
                    "total": 2,
                    "data": [
                        {
                            "data": CategoriaResponse.model_json_schema()["example"],
                            "children": [
                                {
                                    "data": {
                                        **CategoriaResponse.model_json_schema()["example"],
                                        "id": "66666666-6666-4666-8666-666666666666",
                                        "parent_id": "11111111-1111-4111-8111-111111111111",
                                        "nombre": "Bombers acolchadas",
                                        "slug": "bombers-acolchadas",
                                    },
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            }
        },
    )
