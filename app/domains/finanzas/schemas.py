"""
Reportes económicos de solo lectura, calculados de las ventas confirmadas.

Cada reporte se pide en JSON o en Excel con los mismos parámetros y da los
mismos números: el Excel es la misma respuesta presentada en dos hojas
(Resumen y Detalle).

- Ventas: cuánto se vendió y cobró, por dónde, quién y cómo se pagó. Una
  línea del detalle por prenda vendida.
- Rentabilidad: ingreso − costo = margen bruto. Una línea del detalle por
  SKU con el total del período. No incluye gastos: no es la utilidad neta.

Los importes se exponen como números JSON y los porcentajes como fracción
(0.487 = 48.7 %).
"""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.shared.enums import CanalVenta, MetodoPago


def _float(value: Decimal) -> float:
    return float(value)


class ReportePeriodo(BaseModel):
    """
    desde y hasta son fechas de la tienda, ambas incluidas. Sin filtros, desde
    es el día de la primera venta confirmada y hasta, hoy.
    """

    desde: date
    hasta: date
    sin_filtros: bool
    generado_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "desde": "2026-10-01",
                "hasta": "2026-11-13",
                "sin_filtros": True,
                "generado_at": "2026-11-13T10:15:00-04:00",
            }
        },
    )


# ------------------------------------------------------------------ ventas


class ReporteVentasResumen(BaseModel):
    """
    venta_precio_normal − rebajas − descuentos_prenda − descuentos_venta =
    total_vendido. Las anuladas (confirmadas y luego canceladas) no suman en
    el resto del reporte.
    """

    ventas: int
    unidades: int
    venta_precio_normal: Decimal
    rebajas: Decimal
    descuentos_prenda: Decimal
    descuentos_venta: Decimal
    total_vendido: Decimal
    ticket_promedio: Decimal
    unidades_por_venta: Decimal
    ventas_anuladas: int
    monto_anulado: Decimal

    @field_serializer(
        "venta_precio_normal",
        "rebajas",
        "descuentos_prenda",
        "descuentos_venta",
        "total_vendido",
        "ticket_promedio",
        "unidades_por_venta",
        "monto_anulado",
        when_used="json",
    )
    def serialize_decimal(self, value: Decimal) -> float:
        return _float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ventas": 64,
                "unidades": 109,
                "venta_precio_normal": 28461,
                "rebajas": 1370,
                "descuentos_prenda": 455,
                "descuentos_venta": 340,
                "total_vendido": 26296,
                "ticket_promedio": 410.88,
                "unidades_por_venta": 1.7,
                "ventas_anuladas": 3,
                "monto_anulado": 1506,
            }
        },
    )


class ReporteVentasMetodo(BaseModel):
    """
    Lo cobrado con un método: el monto exacto de cada pago, también en las
    ventas mixtas. porcentaje es la fracción del total cobrado.
    """

    metodo: MetodoPago
    pagos: int
    monto: Decimal
    porcentaje: Decimal

    @field_serializer("monto", "porcentaje", when_used="json")
    def serialize_decimal(self, value: Decimal) -> float:
        return _float(value)

    model_config = ConfigDict(
        json_schema_extra={"example": {"metodo": "EFECTIVO", "pagos": 31, "monto": 10385.5, "porcentaje": 0.395}},
    )


class ReporteVentasLinea(BaseModel):
    """
    Una prenda vendida. Los precios son por unidad; los descuentos, de toda la
    línea. descuento_venta es la parte del descuento general de la venta que
    le toca, repartido según el subtotal de cada prenda.

    total = precio_cobrado × cantidad − descuento_prenda − descuento_venta.
    metodos_pago son los de toda la venta: una venta mixta los lista todos.
    """

    fecha: date
    hora: time
    venta_id: UUID
    numero: int
    canal: CanalVenta
    vendedor: str
    metodos_pago: list[MetodoPago]
    sku_id: UUID
    producto: str
    color: str
    talla: str
    codigo_barras: str | None
    cantidad: int
    precio_normal: Decimal
    precio_cobrado: Decimal
    descuento_prenda: Decimal
    descuento_venta: Decimal
    total: Decimal

    @field_serializer(
        "precio_normal", "precio_cobrado", "descuento_prenda", "descuento_venta", "total", when_used="json"
    )
    def serialize_decimal(self, value: Decimal) -> float:
        return _float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "fecha": "2026-10-01",
                "hora": "12:25:00",
                "venta_id": "66666666-6666-4666-8666-666666666666",
                "numero": 25,
                "canal": "TIENDA",
                "vendedor": "Lucía Pérez Gómez",
                "metodos_pago": ["EFECTIVO", "QR"],
                "sku_id": "11111111-1111-4111-8111-111111111111",
                "producto": "Jean recto tiro alto",
                "color": "Negro",
                "talla": "30",
                "codigo_barras": "7790000000018",
                "cantidad": 2,
                "precio_normal": 259,
                "precio_cobrado": 259,
                "descuento_prenda": 20,
                "descuento_venta": 13.16,
                "total": 484.84,
            }
        },
    )


class ReporteVentas(BaseModel):
    """Respuesta de GET /finanzas/ventas; GET /finanzas/ventas/excel la entrega en Excel."""

    periodo: ReportePeriodo
    resumen: ReporteVentasResumen
    cobrado_por_metodo: list[ReporteVentasMetodo]
    detalle: list[ReporteVentasLinea]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "periodo": ReportePeriodo.model_config["json_schema_extra"]["example"],
                "resumen": ReporteVentasResumen.model_config["json_schema_extra"]["example"],
                "cobrado_por_metodo": [ReporteVentasMetodo.model_config["json_schema_extra"]["example"]],
                "detalle": [ReporteVentasLinea.model_config["json_schema_extra"]["example"]],
            }
        },
    )


# ------------------------------------------------------------------ rentabilidad


class ReporteRentabilidadResumen(BaseModel):
    """
    venta_precio_normal − descuentos = ingreso_neto (el total vendido);
    ingreso_neto − costo = margen_bruto. unidades_sin_costo avisa de prendas
    vendidas con costo 0, cuyo margen no es real.
    """

    unidades: int
    venta_precio_normal: Decimal
    descuentos: Decimal
    ingreso_neto: Decimal
    costo: Decimal
    margen_bruto: Decimal
    margen_porcentaje: Decimal
    unidades_sin_costo: int

    @field_serializer(
        "venta_precio_normal",
        "descuentos",
        "ingreso_neto",
        "costo",
        "margen_bruto",
        "margen_porcentaje",
        when_used="json",
    )
    def serialize_decimal(self, value: Decimal) -> float:
        return _float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "unidades": 109,
                "venta_precio_normal": 28461,
                "descuentos": 2165,
                "ingreso_neto": 26296,
                "costo": 13498,
                "margen_bruto": 12798,
                "margen_porcentaje": 0.4867,
                "unidades_sin_costo": 0,
            }
        },
    )


class ReporteRentabilidadMes(BaseModel):
    anio: int
    mes: int
    unidades: int
    ingreso_neto: Decimal
    costo: Decimal
    margen_bruto: Decimal
    margen_porcentaje: Decimal

    @field_serializer("ingreso_neto", "costo", "margen_bruto", "margen_porcentaje", when_used="json")
    def serialize_decimal(self, value: Decimal) -> float:
        return _float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "anio": 2026,
                "mes": 10,
                "unidades": 68,
                "ingreso_neto": 17347,
                "costo": 8702,
                "margen_bruto": 8645,
                "margen_porcentaje": 0.4984,
            }
        },
    )


class ReporteRentabilidadLinea(BaseModel):
    """
    Un SKU con el total del período. descuentos = rebajas + descuentos por
    prenda + su parte del descuento general de cada venta. Producto, color y
    talla son los de su venta más reciente.
    """

    sku_id: UUID
    producto: str
    color: str
    talla: str
    codigo_barras: str | None
    cantidad: int
    venta_precio_normal: Decimal
    descuentos: Decimal
    ingreso_neto: Decimal
    costo: Decimal
    margen_bruto: Decimal
    margen_porcentaje: Decimal

    @field_serializer(
        "venta_precio_normal",
        "descuentos",
        "ingreso_neto",
        "costo",
        "margen_bruto",
        "margen_porcentaje",
        when_used="json",
    )
    def serialize_decimal(self, value: Decimal) -> float:
        return _float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sku_id": "11111111-1111-4111-8111-111111111111",
                "producto": "Vestido largo plisado",
                "color": "Rojo",
                "talla": "M",
                "codigo_barras": "7790000000011",
                "cantidad": 5,
                "venta_precio_normal": 1745,
                "descuentos": 45,
                "ingreso_neto": 1700,
                "costo": 750,
                "margen_bruto": 950,
                "margen_porcentaje": 0.5588,
            }
        },
    )


class ReporteRentabilidad(BaseModel):
    """
    Respuesta de GET /finanzas/rentabilidad; GET /finanzas/rentabilidad/excel
    la entrega en Excel. detalle va de mayor a menor margen bruto.
    """

    periodo: ReportePeriodo
    resumen: ReporteRentabilidadResumen
    por_mes: list[ReporteRentabilidadMes]
    detalle: list[ReporteRentabilidadLinea]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "periodo": ReportePeriodo.model_config["json_schema_extra"]["example"],
                "resumen": ReporteRentabilidadResumen.model_config["json_schema_extra"]["example"],
                "por_mes": [ReporteRentabilidadMes.model_config["json_schema_extra"]["example"]],
                "detalle": [ReporteRentabilidadLinea.model_config["json_schema_extra"]["example"]],
            }
        },
    )
