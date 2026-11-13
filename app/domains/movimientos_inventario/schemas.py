"""
Kardex: libro de movimientos de stock, de solo lectura. Un movimiento no se
edita ni se elimina: un error se corrige con otro ajuste (CORRECCION).

Cada fila trae la prenda resumida (sku) y el documento que la causó
(origen), listos para mostrar, y sus valores calculados al costo. Los costos
solo los ven los roles con acceso al kardex.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.shared.enums import MotivoAjuste, Role, TipoMovimiento


class SkuResumen(BaseModel):
    """
    La prenda del movimiento, lista para mostrar ("Camisa Oxford · Azul
    marino · M"). Se resuelve aunque el SKU, su color o su producto estén
    eliminados, para no perder la historia del kardex. No incluye precio ni
    stock: el stock de hoy no es el saldo del movimiento.
    """

    id: UUID
    codigo_barras: str | None
    producto_id: UUID
    producto_nombre: str
    color_nombre: str
    talla_etiqueta: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "codigo_barras": "8412345678905",
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "producto_nombre": "Camisa Oxford",
                "color_nombre": "Azul marino",
                "talla_etiqueta": "M",
            }
        },
    )


class MovimientoOrigen(BaseModel):
    """
    Documento que causó el movimiento: "Ajuste #12" o "Venta #9". motivo es el
    del ajuste; en una venta es null. Una VENTA y su ANULACION apuntan a la
    misma venta.
    """

    tipo: Literal["AJUSTE", "VENTA"]
    id: UUID
    numero: int
    motivo: MotivoAjuste | None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tipo": "AJUSTE",
                "id": "77777777-7777-4777-8777-777777777777",
                "numero": 12,
                "motivo": "RECEPCION",
            }
        },
    )


class UsuarioResumen(BaseModel):
    """
    Usuario responsable del movimiento, listo para mostrar. Se resuelve aunque
    el usuario esté eliminado, para no perder la historia del kardex.
    """

    id: UUID
    nombre: str
    apellidos: str | None
    rol: Role

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "22222222-2222-4222-8222-222222222222",
                "nombre": "Lucía",
                "apellidos": "Pérez Gómez",
                "rol": "ADMIN",
            }
        },
    )


class MovimientoInventarioResponse(BaseModel):
    """
    Una fila del kardex. cantidad es positiva si entra y negativa si sale;
    saldo es el stock que quedó. costo_promedio es el costo del SKU después
    del movimiento.

    costo_total = cantidad × costo_unitario (negativo si sale) y
    saldo_valor = saldo × costo_promedio: las columnas de un kardex valorizado.
    created_by es auditoría; usuario es el responsable del movimiento.
    """

    id: UUID
    tipo: TipoMovimiento
    cantidad: int
    saldo: int
    costo_unitario: Decimal
    costo_total: Decimal
    costo_promedio: Decimal
    saldo_valor: Decimal
    created_at: datetime
    created_by: UUID | None
    sku: SkuResumen
    origen: MovimientoOrigen
    usuario: UsuarioResumen

    @field_serializer("costo_unitario", "costo_total", "costo_promedio", "saldo_valor", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        return float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "44444444-4444-4444-8444-444444444444",
                "tipo": "AJUSTE",
                "cantidad": 24,
                "saldo": 36,
                "costo_unitario": 13,
                "costo_total": 312,
                "costo_promedio": 12,
                "saldo_valor": 432,
                "created_at": "2026-11-07T15:00:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "sku": SkuResumen.model_config["json_schema_extra"]["example"],
                "origen": MovimientoOrigen.model_config["json_schema_extra"]["example"],
                "usuario": UsuarioResumen.model_config["json_schema_extra"]["example"],
            }
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
