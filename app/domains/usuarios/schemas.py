from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.shared.enums import Role
from app.shared.services.validators import (
    validator_email,
    validator_name,
    validator_password,
    validator_phone,
)


class UsuarioCreate(BaseModel):
    """Schema para crear un usuario desde el panel administrativo."""

    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=6, max_length=20)
    nombre: str = Field(..., min_length=2, max_length=100)
    apellidos: str | None = Field(default=None, min_length=2, max_length=150)
    telefono: str | None = Field(default=None, min_length=6, max_length=30)
    rol: Role = Field(...)

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value: object) -> str:
        if value is None:
            raise ValueError("El email no puede ser null.")
        return validator_email(value)

    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, value: object) -> str:
        if value is None:
            raise ValueError("La contraseña no puede ser null.")
        return validator_password(value)

    @field_validator("nombre", mode="before")
    @classmethod
    def validate_nombre(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre no puede ser null.")
        return validator_name(value)

    @field_validator("apellidos", mode="before")
    @classmethod
    def validate_apellidos(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_name(value)

    @field_validator("telefono", mode="before")
    @classmethod
    def validate_telefono(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_phone(value)

    @field_validator("rol")
    @classmethod
    def validate_rol(cls, value: Role | None) -> Role:
        if value is None:
            raise ValueError("El rol no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "ana@tienda.com",
                "password": "Clave123",
                "nombre": "Ana",
                "apellidos": "Pérez López",
                "telefono": "71234567",
                "rol": "ADMIN",
            }
        },
    )


class UsuarioUpdateMe(BaseModel):
    """Schema para que el usuario autenticado actualice sus propios datos."""

    email: EmailStr | None = Field(default=None, max_length=255)
    nombre: str | None = Field(default=None, min_length=2, max_length=100)
    apellidos: str | None = Field(default=None, min_length=2, max_length=150)
    telefono: str | None = Field(default=None, min_length=6, max_length=30)

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value: object) -> str:
        if value is None:
            raise ValueError("El email no puede ser null.")
        return validator_email(value)

    @field_validator("nombre", mode="before")
    @classmethod
    def validate_nombre(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre no puede ser null.")
        return validator_name(value)

    @field_validator("apellidos", mode="before")
    @classmethod
    def validate_apellidos(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_name(value)

    @field_validator("telefono", mode="before")
    @classmethod
    def validate_telefono(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_phone(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "ana@tienda.com",
                "nombre": "Ana María",
                "apellidos": "Pérez López",
                "telefono": "71234567",
            }
        },
    )


class UsuarioUpdate(UsuarioUpdateMe):
    """Schema para actualizar un usuario desde el panel administrativo."""

    rol: Role | None = Field(default=None)

    @field_validator("rol")
    @classmethod
    def validate_rol(cls, value: Role | None) -> Role:
        if value is None:
            raise ValueError("El rol no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "ana@tienda.com",
                "nombre": "Ana María",
                "apellidos": "Pérez López",
                "telefono": "71234567",
                "rol": "OWNER",
            }
        },
    )


class UsuarioResetPassword(BaseModel):
    """Schema para restablecer la contraseña de un usuario desde el panel administrativo."""

    new_password: str = Field(..., min_length=6, max_length=20)

    @field_validator("new_password", mode="before")
    @classmethod
    def validate_new_password(cls, value: object) -> str:
        if value is None:
            raise ValueError("La nueva contraseña no puede ser null.")
        return validator_password(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "new_password": "NuevaClave123",
            }
        },
    )


class UsuarioChangePassword(UsuarioResetPassword):
    """Schema para que el usuario autenticado cambie su propia contraseña."""

    current_password: str = Field(..., min_length=6, max_length=20)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "current_password": "ClaveActual123",
                "new_password": "NuevaClave123",
            }
        },
    )


class UsuarioResponse(BaseModel):
    """Respuesta de usuario sin contraseña."""

    id: UUID
    email: str
    nombre: str
    apellidos: str | None
    telefono: str | None
    rol: Role
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "email": "ana@tienda.com",
                "nombre": "Ana",
                "apellidos": "Pérez López",
                "telefono": "71234567",
                "rol": "ADMIN",
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class UsuarioResponseAudit(UsuarioResponse):
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
                "email": "ana@tienda.com",
                "nombre": "Ana",
                "apellidos": "Pérez López",
                "telefono": "71234567",
                "rol": "ADMIN",
                "created_at": "2026-10-29T14:30:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-10-29T15:00:00Z",
                "updated_by": "22222222-2222-4222-8222-222222222222",
                "is_deleted": True,
                "deleted_at": "2026-10-30T09:00:00Z",
                "deleted_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )
