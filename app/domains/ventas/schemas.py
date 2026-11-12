"""
Una venta no tiene PATCH ni DELETE. Mientras está PENDIENTE se corrige con
PUT /ventas/{id}/items, que reemplaza sus ítems y los datos no sensibles; se
cobra con POST /ventas/{id}/confirmar y se anula con POST /ventas/{id}/cancelar.
Una venta no se borra: se cancela.

Se cobra con pagos (venta_pagos), que pueden ser mixtos. Sin anticipos ni
fiado: una venta PENDIENTE no tiene pagos, y todos sus pagos se envían juntos
al cobrarla (al crearla o al confirmarla) y cubren exactamente su total.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.domains.venta_items.schemas import VentaItemCreate, VentaItemResponse
from app.domains.venta_pagos.schemas import MAX_PAGOS_POR_VENTA, VentaPagoDetail, VentaPagoDetailCreate
from app.shared.enums import CanalVenta, EstadoVenta
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.services.validators import (
    validator_boolean,
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


def _validate_pagos_not_null(value: object) -> object:
    if value is None:
        raise ValueError("Los pagos no pueden ser null; usa [] si no hay pagos.")
    return value


def _validate_descuento(value: object) -> Decimal:
    if value is None:
        raise ValueError("El descuento no puede ser null; usa 0 si no hay descuento.")
    return validator_non_negative_money(value)


class VentaCreate(BaseModel):
    """
    Entrada de POST /ventas/. Crea la venta con todos sus ítems. canal es
    PAGINA_WEB por defecto, como un pedido del catálogo público; las demás
    ventas deben enviar su canal. Subtotal y total los calcula el service.

    El estado no se envía: lo deciden los pagos. Sin pagos la venta queda
    PENDIENTE, como un pedido que aún no se cobra; con pagos, que pueden ser
    mixtos, queda CONFIRMADA (venta de mostrador) y deben sumar exactamente su
    total. No se admiten pagos parciales.
    """

    canal: CanalVenta = Field(default=CanalVenta.PAGINA_WEB)
    referencia: str | None = Field(default=None, min_length=1, max_length=150)
    cliente_telefono: str | None = Field(default=None, min_length=6, max_length=20)
    descuento: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    nota: str | None = Field(default=None, min_length=1)
    items: list[VentaItemCreate] = Field(..., min_length=1, max_length=MAX_ITEMS_POR_VENTA)
    pagos: list[VentaPagoDetailCreate] = Field(default_factory=list, max_length=MAX_PAGOS_POR_VENTA)

    @field_validator("canal")
    @classmethod
    def validate_canal(cls, value: CanalVenta | None) -> CanalVenta:
        if value is None:
            raise ValueError("El canal no puede ser null.")
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

    @field_validator("pagos", mode="before")
    @classmethod
    def validate_pagos_not_null(cls, value: object) -> object:
        return _validate_pagos_not_null(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "canal": "WHATSAPP",
                "referencia": "María López",
                "cliente_telefono": "+59171234567",
                "descuento": 4.8,
                "nota": "Recoge en tienda el sábado.",
                "items": [VentaItemCreate.model_config["json_schema_extra"]["example"]],
                "pagos": [],
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

    recalcular_precios, igual que al confirmar: por defecto (false) los ítems que
    ya estaban conservan el precio y los nombres con que se ofrecieron y solo
    cambian su cantidad y su descuento; los nuevos entran con el precio del día.
    true actualiza todos los ítems con los precios y nombres del día.
    """

    canal: CanalVenta | None = Field(default=None)
    referencia: str | None = Field(default=None, min_length=1, max_length=150)
    cliente_telefono: str | None = Field(default=None, min_length=6, max_length=20)
    descuento: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    nota: str | None = Field(default=None, min_length=1)
    items: list[VentaItemCreate] = Field(..., min_length=1, max_length=MAX_ITEMS_POR_VENTA)
    recalcular_precios: bool = Field(default=False)

    @field_validator("canal")
    @classmethod
    def validate_canal(cls, value: CanalVenta | None) -> CanalVenta:
        if value is None:
            raise ValueError("El canal no puede ser null.")
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

    @field_validator("recalcular_precios", mode="before")
    @classmethod
    def validate_recalcular_precios(cls, value: object) -> bool:
        if value is None:
            raise ValueError("recalcular_precios no puede ser null.")
        return validator_boolean(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "canal": "WHATSAPP",
                "referencia": "María López",
                "cliente_telefono": "+59171234567",
                "descuento": 0,
                "nota": "Cambió la talla a M.",
                "items": [VentaItemCreate.model_config["json_schema_extra"]["example"]],
                "recalcular_precios": False,
            }
        },
    )


class VentaConfirmar(BaseModel):
    """
    Entrada de POST /ventas/{id}/confirmar: cobra una venta PENDIENTE y fija
    confirmada_at.

    pagos, que pueden ser mixtos, deben sumar exactamente el total de la venta
    (ya recalculado si se pide): sin anticipos ni fiado. Solo una venta de
    total 0 se confirma sin pagos.

    recalcular_precios: por defecto (false) la venta se cobra como una
    proforma, tal como se ofreció, con sus precios, descuentos y total. true la
    actualiza antes de cobrar con los precios y nombres del día, igual que
    recalcular_precios en PUT /items.
    """

    pagos: list[VentaPagoDetailCreate] = Field(default_factory=list, max_length=MAX_PAGOS_POR_VENTA)
    recalcular_precios: bool = Field(default=False)

    @field_validator("pagos", mode="before")
    @classmethod
    def validate_pagos_not_null(cls, value: object) -> object:
        return _validate_pagos_not_null(value)

    @field_validator("recalcular_precios", mode="before")
    @classmethod
    def validate_recalcular_precios(cls, value: object) -> bool:
        if value is None:
            raise ValueError("recalcular_precios no puede ser null.")
        return validator_boolean(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "pagos": [
                    {"metodo": "EFECTIVO", "monto": 40},
                    {"metodo": "QR", "monto": 20, "referencia": "0048219"},
                ],
                "recalcular_precios": True,
            }
        },
    )


class VentaResponse(BaseModel):
    """
    created_by es quien registró la venta: es un dato de negocio, no solo de
    auditoría. total_pagado es la suma de sus pagos; el saldo por cobrar es
    total - total_pagado. En una venta cancelada es lo que se devolvió.
    """

    id: UUID
    numero: int
    estado: EstadoVenta
    canal: CanalVenta
    referencia: str | None
    cliente_telefono: str | None
    subtotal: Decimal
    descuento: Decimal
    total: Decimal
    total_pagado: Decimal
    nota: str | None
    confirmada_at: datetime | None
    cancelada_at: datetime | None
    created_at: datetime
    created_by: UUID | None
    updated_at: datetime

    @field_serializer("subtotal", "descuento", "total", "total_pagado", when_used="json")
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
                "referencia": "María López",
                "cliente_telefono": "+59171234567",
                "subtotal": 84.8,
                "descuento": 4.8,
                "total": 80,
                "total_pagado": 80,
                "nota": "Recoge en tienda el sábado.",
                "confirmada_at": "2026-11-07T15:00:00Z",
                "cancelada_at": "2026-11-08T10:00:00Z",
                "created_at": "2026-11-07T14:30:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-11-08T10:00:00Z",
            }
        },
    )


class VentaResumenConfirmada(BaseModel):
    """
    Ventas confirmadas: lo cobrado con cada método, sumando sus pagos (una venta
    con pagos mixtos aporta a varios), y total, la suma de todos los métodos.
    Hay un campo por cada MetodoPago: un método nuevo exige agregar su campo.
    """

    efectivo: Decimal
    tarjeta: Decimal
    cheque: Decimal
    vales: Decimal
    otros: Decimal
    qr: Decimal
    transferencia: Decimal
    total: Decimal

    @field_serializer(
        "efectivo", "tarjeta", "cheque", "vales", "otros", "qr", "transferencia", "total", when_used="json"
    )
    def serialize_money(self, value: Decimal) -> float:
        return float(value)


class VentaResumen(BaseModel):
    """
    Suma de total de todas las ventas filtradas, no solo de la página. Ignora
    los filtros estado y metodo_pago para mostrar siempre el desglose completo.
    Las pendientes no tienen pagos: pendiente es lo que falta cobrar.
    """

    confirmada: VentaResumenConfirmada
    pendiente: Decimal
    cancelada: Decimal

    @field_serializer("pendiente", "cancelada", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        return float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "confirmada": {
                    "efectivo": 800,
                    "tarjeta": 120,
                    "cheque": 0,
                    "vales": 0,
                    "otros": 0,
                    "qr": 340,
                    "transferencia": 0,
                    "total": 1260,
                },
                "pendiente": 160,
                "cancelada": 90,
            }
        },
    )


class VentaPaginatedResponse(PaginatedResponse[VentaResponse]):
    """Listado paginado de ventas con el resumen de importes de todo el resultado filtrado."""

    resumen: VentaResumen


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
    """
    Respuesta de GET /ventas/{id}, POST, PUT /items, POST /confirmar y POST
    /cancelar: la venta con sus ítems y sus pagos.
    """

    items: list[VentaItemResponse]
    pagos: list[VentaPagoDetail]

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
                "pagos": [
                    {
                        **VentaPagoDetail.model_config["json_schema_extra"]["example"],
                        "monto": 50,
                    },
                    {
                        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                        "venta_id": "66666666-6666-4666-8666-666666666666",
                        "metodo": "EFECTIVO",
                        "monto": 30,
                        "referencia": "Recibo 0012",
                        "comprobante_url": "https://res.cloudinary.com/demo/image/upload/v1/pinodo/comprobantes/def456.jpg",
                        "created_at": "2026-11-07T15:00:00Z",
                        "created_by": "22222222-2222-4222-8222-222222222222",
                        "updated_at": "2026-11-07T15:00:00Z",
                    },
                ],
            }
        },
    )
