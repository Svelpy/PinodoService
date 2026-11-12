"""
Kardex. Un movimiento no se edita ni se elimina: un error se corrige con otro
ajuste (CORRECCION). Por eso no hay Update ni DELETE.

Ninguna ruta crea un movimiento suelto: INICIAL lo registra el SKU al nacer,
VENTA y ANULACION la venta al confirmarse o anularse, y AJUSTE el endpoint de
ajustes (AjusteInventarioCreate). Los costos solo los ven los roles con acceso
al kardex.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.domains.skus.schemas import SkuResponse
from app.domains.ventas.schemas import VentaResponse
from app.shared.enums import MotivoAjuste, TipoMovimiento
from app.shared.services.validators import (
    validator_integer,
    validator_non_empty_text,
    validator_non_negative_integer,
    validator_non_negative_money,
)

MAX_ITEMS_POR_AJUSTE = 200


class AjusteInventarioItem(BaseModel):
    """
    Un SKU del ajuste. Qué campos lleva depende del motivo del ajuste:

    - RECEPCION: cantidad (> 0, unidades que entran) y costo_unitario.
    - CONTEO: cantidad_contada (>= 0, lo que hay en el estante).
    - MERMA y ROBO_PERDIDA: cantidad (> 0, unidades que salen).
    - CORRECCION: cantidad positiva (entra) o negativa (sale), distinta de 0.
    """

    sku_id: UUID = Field(...)
    cantidad: int | None = Field(default=None)
    cantidad_contada: int | None = Field(default=None)
    costo_unitario: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)

    @field_validator("sku_id")
    @classmethod
    def validate_sku_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("El SKU no puede ser null.")
        return value

    @field_validator("cantidad", mode="before")
    @classmethod
    def validate_cantidad(cls, value: object) -> int | None:
        if value is None:
            return None
        cantidad = validator_integer(value)
        if cantidad == 0:
            raise ValueError("La cantidad no puede ser 0.")
        return cantidad

    @field_validator("cantidad_contada", mode="before")
    @classmethod
    def validate_cantidad_contada(cls, value: object) -> int | None:
        if value is None:
            return None
        return validator_non_negative_integer(value)

    @field_validator("costo_unitario", mode="before")
    @classmethod
    def validate_costo_unitario(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return validator_non_negative_money(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "sku_id": "11111111-1111-4111-8111-111111111111",
                "cantidad": 24,
                "cantidad_contada": 24,
                "costo_unitario": 12.5,
            }
        },
    )


class AjusteInventarioCreate(BaseModel):
    """
    Entrada de POST /movimientos-inventario/ajustes: un ajuste manual de uno o
    varios SKUs con el mismo motivo, en una sola transacción. Cada SKU que
    cambia deja un movimiento AJUSTE con ese motivo y la nota.

    nota es opcional, salvo en CORRECCION, donde explica qué se corrige.
    """

    motivo: MotivoAjuste = Field(...)
    nota: str | None = Field(default=None, min_length=1, max_length=200)
    items: list[AjusteInventarioItem] = Field(..., min_length=1, max_length=MAX_ITEMS_POR_AJUSTE)

    @field_validator("motivo")
    @classmethod
    def validate_motivo(cls, value: MotivoAjuste | None) -> MotivoAjuste:
        if value is None:
            raise ValueError("El motivo no puede ser null.")
        return value

    @field_validator("nota", mode="before")
    @classmethod
    def validate_nota(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_non_empty_text(value)

    @field_validator("items", mode="before")
    @classmethod
    def validate_items(cls, value: object) -> object:
        if value is None:
            raise ValueError("Los ítems no pueden ser null.")
        return value

    @model_validator(mode="after")
    def validate_por_motivo(self) -> "AjusteInventarioCreate":
        if self.motivo == MotivoAjuste.CORRECCION and self.nota is None:
            raise ValueError("Una CORRECCION necesita una nota que explique qué se corrige.")

        vistos: set[UUID] = set()
        for index, item in enumerate(self.items):
            path = f"items -> {index}"
            if item.sku_id in vistos:
                raise ValueError(f"{path}: el SKU está repetido en el ajuste.")
            vistos.add(item.sku_id)

            if self.motivo == MotivoAjuste.CONTEO:
                if item.cantidad_contada is None:
                    raise ValueError(f"{path}: un CONTEO envía cantidad_contada, lo que hay en el estante.")
                if item.cantidad is not None:
                    raise ValueError(f"{path}: un CONTEO envía cantidad_contada, no cantidad.")
            else:
                if item.cantidad_contada is not None:
                    raise ValueError(f"{path}: cantidad_contada solo se envía en un CONTEO.")
                if item.cantidad is None:
                    raise ValueError(f"{path}: falta la cantidad.")
                if self.motivo != MotivoAjuste.CORRECCION and item.cantidad < 0:
                    raise ValueError(
                        f"{path}: la cantidad de un {self.motivo.value} es positiva "
                        "(las unidades que entran o salen)."
                    )

            if self.motivo == MotivoAjuste.RECEPCION:
                if item.costo_unitario is None:
                    raise ValueError(f"{path}: una RECEPCION necesita costo_unitario.")
            elif item.costo_unitario is not None:
                raise ValueError(
                    f"{path}: solo una RECEPCION envía costo_unitario; los demás ajustes "
                    "usan el costo promedio actual."
                )
        return self

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "motivo": "RECEPCION",
                "nota": "Lote de noviembre",
                "items": [
                    {
                        "sku_id": "11111111-1111-4111-8111-111111111111",
                        "cantidad": 24,
                        "costo_unitario": 12.5,
                    },
                    {
                        "sku_id": "33333333-3333-4333-8333-333333333333",
                        "cantidad": 12,
                        "costo_unitario": 12.5,
                    },
                ],
            }
        },
    )


class MovimientoInventarioResponse(BaseModel):
    """
    cantidad es positiva si entra y negativa si sale; saldo es el stock que
    quedó. motivo y nota solo los tiene un AJUSTE; venta_id, una VENTA o
    una ANULACION. costo_promedio es el costo del SKU después del movimiento: el saldo
    valorizado es saldo × costo_promedio. created_by es quien lo registró.
    """

    id: UUID
    sku_id: UUID
    tipo: TipoMovimiento
    motivo: MotivoAjuste | None
    cantidad: int
    saldo: int
    costo_unitario: Decimal
    costo_promedio: Decimal
    nota: str | None
    venta_id: UUID | None
    created_at: datetime
    created_by: UUID | None

    @field_serializer("costo_unitario", "costo_promedio", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        return float(value)

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "44444444-4444-4444-8444-444444444444",
                "sku_id": "11111111-1111-4111-8111-111111111111",
                "tipo": "AJUSTE",
                "motivo": "RECEPCION",
                "cantidad": 24,
                "saldo": 36,
                "costo_unitario": 12.5,
                "costo_promedio": 12.1,
                "nota": "Lote de noviembre",
                "venta_id": "66666666-6666-4666-8666-666666666666",
                "created_at": "2026-11-07T15:00:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )


class MovimientoInventarioResponseAudit(MovimientoInventarioResponse):
    """Un movimiento no se edita ni se elimina: solo añade su última actualización."""

    updated_at: datetime
    updated_by: UUID | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **MovimientoInventarioResponse.model_config["json_schema_extra"]["example"],
                "updated_at": "2026-11-07T15:00:00Z",
                "updated_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )


class MovimientoInventarioListItem(MovimientoInventarioResponse):
    """
    sku y venta son referencias y se embeben con su Response. sku es null si
    el SKU fue eliminado; venta, en los INICIAL y AJUSTE.
    """

    sku: SkuResponse | None
    venta: VentaResponse | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **MovimientoInventarioResponse.model_config["json_schema_extra"]["example"],
                "sku": SkuResponse.model_config["json_schema_extra"]["example"],
                "venta": VentaResponse.model_config["json_schema_extra"]["example"],
            }
        },
    )


class MovimientoInventarioDetail(MovimientoInventarioListItem):
    """Un movimiento no tiene hijos: su Detail es su ListItem."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": MovimientoInventarioListItem.model_config["json_schema_extra"]["example"],
        },
    )


class SkuCosto(BaseModel):
    """
    Respuesta de GET /movimientos-inventario/costos: stock y costo de un SKU
    con su producto, color y talla. valor = cantidad × costo.
    """

    sku_id: UUID
    producto_id: UUID
    producto_nombre: str
    color_nombre: str
    talla_etiqueta: str
    codigo_barras: str | None
    cantidad: int
    costo: Decimal
    valor: Decimal

    @field_serializer("costo", "valor", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        return float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sku_id": "11111111-1111-4111-8111-111111111111",
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "producto_nombre": "Camisa Oxford",
                "color_nombre": "Azul marino",
                "talla_etiqueta": "M",
                "codigo_barras": "8412345678905",
                "cantidad": 12,
                "costo": 12.5,
                "valor": 150,
            }
        },
    )


class AjusteInventarioResultado(BaseModel):
    """
    Respuesta de POST /movimientos-inventario/ajustes. movimientos son los
    creados, en el orden de los ítems; sin_diferencia, los SKUs de un CONTEO
    cuyo stock ya coincidía con lo contado (no dejan movimiento).
    """

    motivo: MotivoAjuste
    movimientos: list[MovimientoInventarioListItem]
    sin_diferencia: list[UUID]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "motivo": "RECEPCION",
                "movimientos": [MovimientoInventarioListItem.model_config["json_schema_extra"]["example"]],
                "sin_diferencia": ["33333333-3333-4333-8333-333333333333"],
            }
        },
    )
