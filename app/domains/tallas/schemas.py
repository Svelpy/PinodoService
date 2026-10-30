from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.services.validators import validator_non_empty_text


class TallaCreate(BaseModel):
    etiqueta: str = Field(..., min_length=1, max_length=30)

    @field_validator("etiqueta", mode="before")
    @classmethod
    def validate_etiqueta(cls, value: object) -> str:
        if value is None:
            raise ValueError("La etiqueta no puede ser null.")
        return validator_non_empty_text(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "etiqueta": "M",
            }
        },
    )


class TallaUpdate(BaseModel):
    etiqueta: str | None = Field(default=None, min_length=1, max_length=30)

    @field_validator("etiqueta", mode="before")
    @classmethod
    def validate_etiqueta(cls, value: object) -> str:
        if value is None:
            raise ValueError("La etiqueta no puede ser null.")
        return validator_non_empty_text(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "etiqueta": "6-7 años",
            }
        },
    )


class TallaResponse(BaseModel):
    id: UUID
    etiqueta: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "etiqueta": "M",
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class TallaResponseAudit(TallaResponse):
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
                "etiqueta": "M",
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
