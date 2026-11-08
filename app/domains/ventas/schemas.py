"""
Una venta no tiene PATCH ni DELETE. Mientras está PENDIENTE se corrige con
PUT /ventas/{id}/items, que reemplaza sus ítems y los datos no sensibles; su
estado cambia con PATCH /ventas/{id}/estado. Una venta no se borra: se cancela.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.domains.venta_items.schemas import VentaItemCreate, VentaItemResponse
from app.shared.enums import CanalVenta, EstadoVenta, MetodoPago
from app.shared.services.validators import (
    validator_non_empty_text,
    validator_non_negative_money,
    validator_phone,
)

MAX_ITEMS_POR_VENTA = 100


def _validate_items(value: list[VentaItemCreate]) -> list[VentaItemCreate]:
    sku_ids = [item.sku_id for item in value]
    if len(sku_ids) != len(set(sku_ids)):
        raise ValueError(
            "Un SKU no puede repetirse dentro de la misma venta; usa la cantidad."
        )
    return value


def _validate_optional_text(value: object) -> str | None:
    if value is None:
        return None
    return validator_non_empty_text(value)


def _validate_optional_phone(value: object) -> str | None:
    if value is None:
        return None
    return validator_phone(value)


def _validate_descuento(value: object) -> Decimal:
    if value is None:
        raise ValueError("El descuento no puede ser null; usa 0 si no hay descuento.")
    return validator_non_negative_money(value)


class VentaCreate(BaseModel):
    """
    Entrada de POST /ventas/. Crea la venta con todos sus ítems.

    estado es PENDIENTE por defecto, como un pedido de WhatsApp que aún no se
    cobra; una venta de mostrador se envía como CONFIRMADA para cobrarla en la
    misma petición. Subtotal y total los calcula el service.
    """

    estado: EstadoVenta = Field(default=EstadoVenta.PENDIENTE)
    canal: CanalVenta = Field(default=CanalVenta.WHATSAPP)
    metodo_pago: MetodoPago = Field(default=MetodoPago.EFECTIVO)
    referencia: str | None = Field(default=None, min_length=1, max_length=150)
    cliente_telefono: str | None = Field(default=None, min_length=6, max_length=20)
    descuento: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    nota: str | None = Field(default=None, min_length=1)
    items: list[VentaItemCreate] = Field(..., min_length=1, max_length=MAX_ITEMS_POR_VENTA)

    @field_validator("estado")
    @classmethod
    def validate_estado(cls, value: EstadoVenta | None) -> EstadoVenta:
        if value is None:
            raise ValueError("El estado no puede ser null.")
        if value == EstadoVenta.CANCELADA:
            raise ValueError("Una venta solo puede crearse como PENDIENTE o CONFIRMADA.")
        return value

    @field_validator("canal")
    @classmethod
    def validate_canal(cls, value: CanalVenta | None) -> CanalVenta:
        if value is None:
            raise ValueError("El canal no puede ser null.")
        return value

    @field_validator("metodo_pago")
    @classmethod
    def validate_metodo_pago(cls, value: MetodoPago | None) -> MetodoPago:
        if value is None:
            raise ValueError("El método de pago no puede ser null.")
        return value

    @field_validator("referencia", "nota", mode="before")
    @classmethod
    def validate_optional_text(cls, value: object) -> str | None:
        return _validate_optional_text(value)

    @field_validator("cliente_telefono", mode="before")
    @classmethod
    def validate_cliente_telefono(cls, value: object) -> str | None:
        return _validate_optional_phone(value)

    @field_validator("descuento", mode="before")
    @classmethod
    def validate_descuento(cls, value: object) -> Decimal:
        return _validate_descuento(value)

    @field_validator("items", mode="before")
    @classmethod
    def validate_items_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Los ítems no pueden ser null.")
        return value

    @field_validator("items")
    @classmethod
    def validate_items(cls, value: list[VentaItemCreate]) -> list[VentaItemCreate]:
        return _validate_items(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "estado": "PENDIENTE",
                "canal": "WHATSAPP",
                "metodo_pago": "QR",
                "referencia": "María López",
                "cliente_telefono": "+59171234567",
                "descuento": 4.8,
                "nota": "Recoge en tienda el sábado.",
                "items": [VentaItemCreate.model_config["json_schema_extra"]["example"]],
            }
        },
    )


class VentaItemsUpdate(BaseModel):
    """
    Entrada de PUT /ventas/{id}/items, solo para ventas PENDIENTE.

    items reemplaza la lista completa: los SKUs que siguen se actualizan, los
    que faltan se eliminan y los nuevos se crean. Los datos de la venta que se
    omiten no cambian; referencia, cliente_telefono y nota aceptan null para
    quitarlos. Subtotal y total se recalculan.
    """

    canal: CanalVenta | None = Field(default=None)
    metodo_pago: MetodoPago | None = Field(default=None)
    referencia: str | None = Field(default=None, min_length=1, max_length=150)
    cliente_telefono: str | None = Field(default=None, min_length=6, max_length=20)
    descuento: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    nota: str | None = Field(default=None, min_length=1)
    items: list[VentaItemCreate] = Field(..., min_length=1, max_length=MAX_ITEMS_POR_VENTA)

    @field_validator("canal")
    @classmethod
    def validate_canal(cls, value: CanalVenta | None) -> CanalVenta:
        if value is None:
            raise ValueError("El canal no puede ser null.")
        return value

    @field_validator("metodo_pago")
    @classmethod
    def validate_metodo_pago(cls, value: MetodoPago | None) -> MetodoPago:
        if value is None:
            raise ValueError("El método de pago no puede ser null.")
        return value

    @field_validator("referencia", "nota", mode="before")
    @classmethod
    def validate_optional_text(cls, value: object) -> str | None:
        return _validate_optional_text(value)

    @field_validator("cliente_telefono", mode="before")
    @classmethod
    def validate_cliente_telefono(cls, value: object) -> str | None:
        return _validate_optional_phone(value)

    @field_validator("descuento", mode="before")
    @classmethod
    def validate_descuento(cls, value: object) -> Decimal:
        return _validate_descuento(value)

    @field_validator("items", mode="before")
    @classmethod
    def validate_items_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Los ítems no pueden ser null.")
        return value

    @field_validator("items")
    @classmethod
    def validate_items(cls, value: list[VentaItemCreate]) -> list[VentaItemCreate]:
        return _validate_items(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "canal": "WHATSAPP",
                "metodo_pago": "TRANSFERENCIA",
                "referencia": "María López",
                "cliente_telefono": "+59171234567",
                "descuento": 0,
                "nota": "Cambió la talla a M.",
                "items": [VentaItemCreate.model_config["json_schema_extra"]["example"]],
            }
        },
    )


class VentaEstadoUpdate(BaseModel):
    """
    Entrada de PATCH /ventas/{id}/estado. CONFIRMADA cobra la venta y fija
    confirmada_at; CANCELADA la anula y fija cancelada_at. Las transiciones
    válidas las comprueba el service.
    """

    estado: EstadoVenta = Field(...)

    @field_validator("estado")
    @classmethod
    def validate_estado(cls, value: EstadoVenta | None) -> EstadoVenta:
        if value is None:
            raise ValueError("El estado no puede ser null.")
        if value == EstadoVenta.PENDIENTE:
            raise ValueError("El estado solo puede cambiar a CONFIRMADA o CANCELADA.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"estado": "CONFIRMADA"}},
    )


class VentaResponse(BaseModel):
    """created_by es quien registró la venta: es un dato de negocio, no solo de auditoría."""

    id: UUID
    numero: int
    estado: EstadoVenta
    canal: CanalVenta
    metodo_pago: MetodoPago
    referencia: str | None
    cliente_telefono: str | None
    subtotal: Decimal
    descuento: Decimal
    total: Decimal
    nota: str | None
    confirmada_at: datetime | None
    cancelada_at: datetime | None
    created_at: datetime
    created_by: UUID | None
    updated_at: datetime

    @field_serializer("subtotal", "descuento", "total", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        # Igual que los precios de los SKUs: la API expone los importes como números JSON.
        return float(value)

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "66666666-6666-4666-8666-666666666666",
                "numero": 1,
                "estado": "CANCELADA",
                "canal": "WHATSAPP",
                "metodo_pago": "QR",
                "referencia": "María López",
                "cliente_telefono": "+59171234567",
                "subtotal": 84.8,
                "descuento": 4.8,
                "total": 80,
                "nota": "Recoge en tienda el sábado.",
                "confirmada_at": "2026-11-07T15:00:00Z",
                "cancelada_at": "2026-11-08T10:00:00Z",
                "created_at": "2026-11-07T14:30:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-11-08T10:00:00Z",
            }
        },
    )


class VentaResponseAudit(VentaResponse):
    """
    Respuesta de GET /ventas/{id}/audit. created_by ya está en VentaResponse, y
    una venta nunca se elimina (se cancela), así que solo añade quién hizo el
    último cambio: editarla, confirmarla o cancelarla.
    """

    updated_by: UUID | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **VentaResponse.model_config["json_schema_extra"]["example"],
                "updated_by": "33333333-3333-4333-8333-333333333333",
            }
        },
    )


class VentaDetail(VentaResponse):
    """Respuesta de GET /ventas/{id}, POST, PUT /items y PATCH /estado: la venta con sus ítems."""

    items: list[VentaItemResponse]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **VentaResponse.model_config["json_schema_extra"]["example"],
                "items": [
                    VentaItemResponse.model_config["json_schema_extra"]["example"],
                    {
                        "id": "77777777-7777-4777-8777-777777777777",
                        "sku_id": "88888888-8888-4888-8888-888888888888",
                        "cantidad": 1,
                        "precio_normal": 49.9,
                        "precio_unitario": 49.9,
                        "descuento_unitario": 5,
                        "subtotal": 44.9,
                        "producto_nombre": "Pantalón chino",
                        "color_nombre": "Beige",
                        "talla_etiqueta": "42",
                        "codigo_barras": "8412345678912",
                    },
                ],
            }
        },
    )
