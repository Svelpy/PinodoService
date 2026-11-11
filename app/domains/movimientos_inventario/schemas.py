"""
Kardex. Un movimiento no se edita ni se elimina: un error se corrige con otro
movimiento (un AJUSTE). Por eso no hay Update ni DELETE.

Los movimientos VENTA y ANULACION los registra el sistema al confirmar o
anular una venta; a mano solo se registran INGRESO y AJUSTE. Los costos solo
los ven los roles con acceso al kardex.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.domains.skus.schemas import SkuResponse
from app.domains.ventas.schemas import VentaResponse
from app.shared.enums import TipoMovimiento
from app.shared.services.validators import (
    validator_integer,
    validator_non_empty_text,
    validator_non_negative_money,
)

TIPOS_MANUALES = frozenset({TipoMovimiento.INGRESO, TipoMovimiento.AJUSTE})


class MovimientoInventarioCreate(BaseModel):
    """
    Entrada de POST /movimientos-inventario/.

    - INGRESO: entra mercadería. cantidad positiva y costo_unitario
      obligatorio (lo que costó cada prenda); recalcula el costo promedio.
    - AJUSTE: corrige el stock por merma, conteo físico o regalo. cantidad
      positiva o negativa y motivo obligatorio; usa el costo promedio actual y
      no acepta costo_unitario.
    """

    sku_id: UUID = Field(...)
    tipo: TipoMovimiento = Field(...)
    cantidad: int = Field(...)
    costo_unitario: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    motivo: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("sku_id")
    @classmethod
    def validate_sku_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("El SKU no puede ser null.")
        return value

    @field_validator("tipo")
    @classmethod
    def validate_tipo(cls, value: TipoMovimiento | None) -> TipoMovimiento:
        if value is None:
            raise ValueError("El tipo no puede ser null.")
        if value not in TIPOS_MANUALES:
            raise ValueError(
                "Solo se registran a mano INGRESO y AJUSTE; VENTA y ANULACION los "
                "registra la venta al confirmarse o anularse."
            )
        return value

    @field_validator("cantidad", mode="before")
    @classmethod
    def validate_cantidad(cls, value: object) -> int:
        if value is None:
            raise ValueError("La cantidad no puede ser null.")
        cantidad = validator_integer(value)
        if cantidad == 0:
            raise ValueError("La cantidad no puede ser 0.")
        return cantidad

    @field_validator("costo_unitario", mode="before")
    @classmethod
    def validate_costo_unitario(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return validator_non_negative_money(value)

    @field_validator("motivo", mode="before")
    @classmethod
    def validate_motivo(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_non_empty_text(value)

    @model_validator(mode="after")
    def validate_por_tipo(self) -> "MovimientoInventarioCreate":
        if self.tipo == TipoMovimiento.INGRESO:
            if self.cantidad < 0:
                raise ValueError("Un INGRESO tiene cantidad positiva; para sacar stock usa un AJUSTE.")
            if self.costo_unitario is None:
                raise ValueError("Un INGRESO necesita costo_unitario.")
        else:
            if self.costo_unitario is not None:
                raise ValueError("Un AJUSTE usa el costo promedio actual; no envíes costo_unitario.")
            if self.motivo is None:
                raise ValueError("Un AJUSTE necesita un motivo (merma, conteo físico...).")
        return self

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "sku_id": "11111111-1111-4111-8111-111111111111",
                "tipo": "INGRESO",
                "cantidad": 24,
                "costo_unitario": 12.5,
                "motivo": "Lote de noviembre",
            }
        },
    )


class MovimientoInventarioResponse(BaseModel):
    """
    cantidad es positiva si entra y negativa si sale; saldo es el stock que
    quedó. costo_promedio es el costo del SKU después del movimiento: el saldo
    valorizado es saldo × costo_promedio. created_by es quien lo registró.
    """

    id: UUID
    sku_id: UUID
    tipo: TipoMovimiento
    cantidad: int
    saldo: int
    costo_unitario: Decimal
    costo_promedio: Decimal
    motivo: str | None
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
                "tipo": "VENTA",
                "cantidad": -2,
                "saldo": 10,
                "costo_unitario": 12.5,
                "costo_promedio": 12.5,
                "motivo": "Venta confirmada",
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
    el SKU fue eliminado; venta, en los INGRESO y AJUSTE.
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
