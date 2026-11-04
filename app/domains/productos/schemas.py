from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.domains.categorias.schemas import CategoriaResponse
from app.domains.producto_colores.schemas import ProductoColorDetail, ProductoColorDetailCreate
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


class ProductoDetailCreate(ProductoCreate):
    """
    Entrada de POST /productos/: crea el producto y, en la misma transacción,
    sus categorías y su árbol de hijos (colores, con sus imágenes y SKUs).

    Es el espejo de entrada de ProductoDetail, que es su respuesta. Sin
    categoria_ids ni colores equivale a ProductoCreate.
    """

    categoria_ids: list[UUID] = Field(default_factory=list, max_length=100)
    colores: list[ProductoColorDetailCreate] = Field(default_factory=list, max_length=30)

    @field_validator("categoria_ids", "colores", mode="before")
    @classmethod
    def validate_lists(cls, value: object) -> object:
        if value is None:
            raise ValueError("La lista no puede ser null; usa [] si no hay elementos.")
        return value

    @field_validator("categoria_ids")
    @classmethod
    def remove_duplicate_categorias(cls, value: list[UUID]) -> list[UUID]:
        # Igual que PUT /productos/{id}/categorias: se conserva la primera aparición.
        return list(dict.fromkeys(value))

    @field_validator("colores")
    @classmethod
    def validate_colores_unicos(
        cls, value: list[ProductoColorDetailCreate]
    ) -> list[ProductoColorDetailCreate]:
        color_ids = [color.color_id for color in value]
        if len(color_ids) != len(set(color_ids)):
            raise ValueError("Un color no puede repetirse dentro del mismo producto.")
        codigos = [
            sku.codigo_barras
            for color in value
            for sku in color.skus
            if sku.codigo_barras is not None
        ]
        if len(codigos) != len(set(codigos)):
            raise ValueError("Un código de barras no puede repetirse dentro del mismo producto.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                **ProductoCreate.model_config["json_schema_extra"]["example"],
                "categoria_ids": ["44444444-4444-4444-8444-444444444444"],
                "colores": [ProductoColorDetailCreate.model_config["json_schema_extra"]["example"]],
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
                "is_deleted": True,
                "deleted_at": "2026-10-30T09:00:00Z",
                "deleted_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )


class ProductoResumenColor(BaseModel):
    """Muestra de un color del producto para el listado."""

    nombre: str
    codigo_hex: str

    model_config = ConfigDict(
        json_schema_extra={"example": {"nombre": "Azul marino", "codigo_hex": "#1E3A8A"}},
    )


class ProductoResumen(BaseModel):
    """
    Datos agregados de los hijos activos del producto, para mostrarlo en un
    listado sin cargar su árbol completo.

    portada_url es la primera imagen, en orden de galería, del primer color que
    tenga imágenes.
    precio_desde y precio_hasta usan el precio vigente hoy de cada SKU; son null
    si el producto no tiene SKUs, igual que portada_url si no tiene imágenes.
    """

    portada_url: str | None
    precio_desde: Decimal | None
    precio_hasta: Decimal | None
    stock_total: int
    colores: list[ProductoResumenColor]

    @field_serializer("precio_desde", "precio_hasta", when_used="json")
    def serialize_money(self, value: Decimal | None) -> float | None:
        return None if value is None else float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "portada_url": "https://res.cloudinary.com/demo/image/upload/camisa-oxford-azul.jpg",
                "precio_desde": 19.95,
                "precio_hasta": 29.95,
                "stock_total": 42,
                "colores": [ProductoResumenColor.model_config["json_schema_extra"]["example"]],
            }
        },
    )


class ProductoListItem(ProductoResponse):
    """
    seccion es referencia y se embebe.

    Excepción del proyecto a la regla del ListItem: resumen agrega datos de los
    hijos (portada, precios, stock y colores) para la tabla de productos, sin
    embeberlos. Lo calcula el service; el Detail lo hereda con los mismos valores.
    """

    seccion: SeccionResponse
    resumen: ProductoResumen

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **ProductoResponse.model_json_schema()["example"],
                "seccion": SeccionResponse.model_json_schema()["example"],
                "resumen": ProductoResumen.model_config["json_schema_extra"]["example"],
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
