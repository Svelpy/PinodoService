from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.shared.services.validators import (
    validator_address,
    validator_boolean,
    validator_email,
    validator_http_url,
    validator_non_empty_text,
    validator_phone,
    validator_schedule,
    validator_social_links,
)


class ConfigCreate(BaseModel):
    """Schema para crear la única fila de configuración de la tienda."""

    nombre_tienda: str = Field(..., min_length=1, max_length=150)
    descripcion: str | None = Field(default=None, min_length=1)
    logo_url: str | None = Field(default=None, max_length=500)
    favicon_url: str | None = Field(default=None, max_length=500)
    email_contacto: EmailStr | None = Field(default=None, max_length=255)
    telefono: str | None = Field(default=None, min_length=6, max_length=30)
    whatsapp: str | None = Field(default=None, min_length=6, max_length=30)
    direccion: str | None = Field(default=None, min_length=1, max_length=255)
    map_url: str | None = Field(default=None, max_length=500)
    ciudad: str | None = Field(default=None, min_length=1, max_length=100)
    horario: dict[str, str] = Field(default_factory=dict)
    redes_sociales: dict[str, str] = Field(default_factory=dict)
    en_mantenimiento: bool = Field(default=False)

    @field_validator("nombre_tienda", mode="before")
    @classmethod
    def validate_nombre_tienda(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre de la tienda no puede ser null.")
        return validator_non_empty_text(value)

    @field_validator("descripcion", "ciudad", mode="before")
    @classmethod
    def validate_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_non_empty_text(value)

    @field_validator("logo_url", "favicon_url", "map_url", mode="before")
    @classmethod
    def validate_optional_url(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_http_url(value)

    @field_validator("email_contacto", mode="before")
    @classmethod
    def validate_email_contacto(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_email(value)

    @field_validator("telefono", "whatsapp", mode="before")
    @classmethod
    def validate_optional_phone(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_phone(value)

    @field_validator("direccion", mode="before")
    @classmethod
    def validate_direccion(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_address(value)

    @field_validator("horario", mode="before")
    @classmethod
    def validate_horario(cls, value: object) -> dict[str, str]:
        if value is None:
            raise ValueError("El horario no puede ser null; usa {} para no indicar horario.")
        return validator_schedule(value)

    @field_validator("redes_sociales", mode="before")
    @classmethod
    def validate_redes_sociales(cls, value: object) -> dict[str, str]:
        if value is None:
            raise ValueError("Las redes sociales no pueden ser null; usa {} para no indicar ninguna.")
        return validator_social_links(value)

    @field_validator("en_mantenimiento", mode="before")
    @classmethod
    def validate_en_mantenimiento(cls, value: object) -> bool:
        if value is None:
            raise ValueError("El modo mantenimiento no puede ser null.")
        return validator_boolean(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "nombre_tienda": "Tienda Moda",
                "descripcion": "Ropa para mujer, hombre y niños.",
                "logo_url": "https://res.cloudinary.com/demo/image/upload/logo.png",
                "favicon_url": "https://res.cloudinary.com/demo/image/upload/favicon.png",
                "email_contacto": "contacto@tienda.com",
                "telefono": "71234567",
                "whatsapp": "+59171234567",
                "direccion": "Avenida Principal 123",
                "map_url": "https://maps.google.com/?q=-17.78,-63.18",
                "ciudad": "Santa Cruz",
                "horario": {"lunes": "09:00-20:00", "sábado": "10:00-14:00"},
                "redes_sociales": {"instagram": "https://instagram.com/tiendamoda"},
                "en_mantenimiento": False,
            }
        },
    )


class ConfigUpdate(BaseModel):
    nombre_tienda: str | None = Field(default=None, min_length=1, max_length=150)
    descripcion: str | None = Field(default=None, min_length=1)
    logo_url: str | None = Field(default=None, max_length=500)
    favicon_url: str | None = Field(default=None, max_length=500)
    email_contacto: EmailStr | None = Field(default=None, max_length=255)
    telefono: str | None = Field(default=None, min_length=6, max_length=30)
    whatsapp: str | None = Field(default=None, min_length=6, max_length=30)
    direccion: str | None = Field(default=None, min_length=1, max_length=255)
    map_url: str | None = Field(default=None, max_length=500)
    ciudad: str | None = Field(default=None, min_length=1, max_length=100)
    horario: dict[str, str] | None = Field(default=None)
    redes_sociales: dict[str, str] | None = Field(default=None)
    en_mantenimiento: bool | None = Field(default=None)

    @field_validator("nombre_tienda", mode="before")
    @classmethod
    def validate_nombre_tienda(cls, value: object) -> str:
        if value is None:
            raise ValueError("El nombre de la tienda no puede ser null.")
        return validator_non_empty_text(value)

    @field_validator("descripcion", "ciudad", mode="before")
    @classmethod
    def validate_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_non_empty_text(value)

    @field_validator("logo_url", "favicon_url", "map_url", mode="before")
    @classmethod
    def validate_optional_url(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_http_url(value)

    @field_validator("email_contacto", mode="before")
    @classmethod
    def validate_email_contacto(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_email(value)

    @field_validator("telefono", "whatsapp", mode="before")
    @classmethod
    def validate_optional_phone(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_phone(value)

    @field_validator("direccion", mode="before")
    @classmethod
    def validate_direccion(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_address(value)

    @field_validator("horario", mode="before")
    @classmethod
    def validate_horario(cls, value: object) -> dict[str, str]:
        if value is None:
            raise ValueError("El horario no puede ser null; usa {} para borrarlo.")
        return validator_schedule(value)

    @field_validator("redes_sociales", mode="before")
    @classmethod
    def validate_redes_sociales(cls, value: object) -> dict[str, str]:
        if value is None:
            raise ValueError("Las redes sociales no pueden ser null; usa {} para borrarlas.")
        return validator_social_links(value)

    @field_validator("en_mantenimiento", mode="before")
    @classmethod
    def validate_en_mantenimiento(cls, value: object) -> bool:
        if value is None:
            raise ValueError("El modo mantenimiento no puede ser null.")
        return validator_boolean(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "nombre_tienda": "Tienda Moda",
                "descripcion": "Ropa para mujer, hombre y niños.",
                "logo_url": "https://res.cloudinary.com/demo/image/upload/logo.png",
                "favicon_url": "https://res.cloudinary.com/demo/image/upload/favicon.png",
                "email_contacto": "contacto@tienda.com",
                "telefono": "71234567",
                "whatsapp": None,
                "direccion": "Avenida Principal 123",
                "map_url": "https://maps.google.com/?q=-17.78,-63.18",
                "ciudad": "Santa Cruz",
                "horario": {"lunes": "09:00-21:00"},
                "redes_sociales": {"instagram": "https://instagram.com/tiendamoda"},
                "en_mantenimiento": True,
            }
        },
    )


class ConfigResponse(BaseModel):
    nombre_tienda: str
    descripcion: str | None
    logo_url: str | None
    favicon_url: str | None
    email_contacto: str | None
    telefono: str | None
    whatsapp: str | None
    direccion: str | None
    map_url: str | None
    ciudad: str | None
    horario: dict[str, str]
    redes_sociales: dict[str, str]
    en_mantenimiento: bool
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "nombre_tienda": "Tienda Moda",
                "descripcion": "Ropa para mujer, hombre y niños.",
                "logo_url": "https://res.cloudinary.com/demo/image/upload/logo.png",
                "favicon_url": "https://res.cloudinary.com/demo/image/upload/favicon.png",
                "email_contacto": "contacto@tienda.com",
                "telefono": "71234567",
                "whatsapp": "+59171234567",
                "direccion": "Avenida Principal 123",
                "map_url": "https://maps.google.com/?q=-17.78,-63.18",
                "ciudad": "Santa Cruz",
                "horario": {"lunes": "09:00-20:00", "sábado": "10:00-14:00"},
                "redes_sociales": {"instagram": "https://instagram.com/tiendamoda"},
                "en_mantenimiento": False,
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class ConfigResponseAudit(ConfigResponse):
    """Config no hereda BaseModel: su única auditoría es updated_by."""

    updated_by: UUID | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "nombre_tienda": "Tienda Moda",
                "descripcion": "Ropa para mujer, hombre y niños.",
                "logo_url": "https://res.cloudinary.com/demo/image/upload/logo.png",
                "favicon_url": "https://res.cloudinary.com/demo/image/upload/favicon.png",
                "email_contacto": "contacto@tienda.com",
                "telefono": "71234567",
                "whatsapp": "+59171234567",
                "direccion": "Avenida Principal 123",
                "map_url": "https://maps.google.com/?q=-17.78,-63.18",
                "ciudad": "Santa Cruz",
                "horario": {"lunes": "09:00-20:00", "sábado": "10:00-14:00"},
                "redes_sociales": {"instagram": "https://instagram.com/tiendamoda"},
                "en_mantenimiento": False,
                "updated_at": "2026-10-29T15:00:00Z",
                "updated_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )
