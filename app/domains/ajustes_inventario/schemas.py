"""
Ajustes de inventario: documentos que agrupan movimientos AJUSTE del kardex.
No se editan ni se eliminan; un error se corrige con otro ajuste (CORRECCION).
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.domains.movimientos_inventario.schemas import MovimientoInventarioResponse
from app.shared.enums import MotivoAjuste
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
    Entrada de POST /ajustes-inventario/: un ajuste manual de uno o varios SKUs
    con el mismo motivo, en una sola transacción. INICIAL no se acepta: lo
    genera el sistema al crear SKUs con stock.

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
        if value == MotivoAjuste.INICIAL:
            raise ValueError("El stock INICIAL lo registra el sistema al crear el SKU.")
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
                "nota": "Factura 4521",
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


class AjusteInventarioResponse(BaseModel):
    """
    Un documento de ajuste. items es cuántos SKUs movió; unidades, la suma de
    sus cantidades (negativa si salió más de lo que entró); valor, la suma de
    cantidad × costo_unitario. created_by es quien lo registró; en la carga
    inicial de la migración es null.
    """

    id: UUID
    numero: int
    motivo: MotivoAjuste
    nota: str | None
    items: int
    unidades: int
    valor: Decimal
    created_at: datetime
    created_by: UUID | None

    @field_serializer("valor", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        return float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "77777777-7777-4777-8777-777777777777",
                "numero": 12,
                "motivo": "RECEPCION",
                "nota": "Factura 4521",
                "items": 2,
                "unidades": 36,
                "valor": 450,
                "created_at": "2026-11-10T15:02:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )


class AjusteInventarioDetail(AjusteInventarioResponse):
    """El documento con sus líneas: los movimientos del kardex que registró."""

    movimientos: list[MovimientoInventarioResponse]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                **AjusteInventarioResponse.model_config["json_schema_extra"]["example"],
                "movimientos": [MovimientoInventarioResponse.model_config["json_schema_extra"]["example"]],
            }
        },
    )


class AjusteInventarioResultado(BaseModel):
    """
    Respuesta de POST /ajustes-inventario/. ajuste es el documento creado, con
    sus líneas. sin_diferencia son los SKUs de un CONTEO cuyo stock ya
    coincidía con lo contado: no dejan línea, y si ninguno cambió no se crea
    documento (ajuste es null).
    """

    ajuste: AjusteInventarioDetail | None
    sin_diferencia: list[UUID]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ajuste": AjusteInventarioDetail.model_config["json_schema_extra"]["example"],
                "sin_diferencia": ["33333333-3333-4333-8333-333333333333"],
            }
        },
    )
