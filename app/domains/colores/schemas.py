from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.services.validators import validator_hex_color, validator_non_empty_text


class ColorCreate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=60)
    codigo_hex: str = Field(..., min_length=7, max_length=7)

    @field_validator("nombre", mode="before")
    @classmethod
    def validate_nombre(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre no puede ser null.")
        return validator_non_empty_text(value)

    @field_validator("codigo_hex", mode="before")
    @classmethod
    def validate_codigo_hex(cls, value: object) -> str:
        if value is None:
            raise ValueError("El código de color no puede ser null.")
        return validator_hex_color(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "nombre": "Azul marino",
                "codigo_hex": "#1E3A8A",
            }
        },
    )


class ColorUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    codigo_hex: str | None = Field(default=None, min_length=7, max_length=7)

    @field_validator("nombre", mode="before")
    @classmethod
    def validate_nombre(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre no puede ser null.")
        return validator_non_empty_text(value)

    @field_validator("codigo_hex", mode="before")
    @classmethod
    def validate_codigo_hex(cls, value: object) -> str:
        if value is None:
            raise ValueError("El código de color no puede ser null.")
        return validator_hex_color(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "codigo_hex": "#172554",
            }
        },
    )


class ColorResponse(BaseModel):
    id: UUID
    nombre: str
    codigo_hex: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "nombre": "Azul marino",
                "codigo_hex": "#1E3A8A",
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class ColorResponseAudit(ColorResponse):
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
                "nombre": "Azul marino",
                "codigo_hex": "#1E3A8A",
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
