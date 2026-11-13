from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from openpyxl import load_workbook

from app.core.config import get_settings
from app.domains.auth.schemas import CurrentUser
from app.domains.config.repositories import ConfigRepository
from app.domains.finanzas.repositories import FinanzasRepository
from app.domains.finanzas.services import FinanzasService
from app.domains.usuarios.repositories import UsuarioRepository
from app.shared.enums import CanalVenta, MetodoPago, Role
from app.shared.errors.exceptions import AppException

TZ = timezone(timedelta(hours=get_settings().TIMEZONE_OFFSET_HOURS))
SKU_CAMISA, SKU_JEAN = uuid4(), uuid4()


def _row(
    venta_id: UUID,
    numero: int,
    confirmada: datetime,
    *,
    sku_id: UUID,
    cantidad: int,
    precio_normal: str,
    precio_unitario: str,
    descuento_unitario: str = "0",
    costo: str | None,
    venta_descuento: str = "0",
    venta_items: list[tuple[str, int, str]] | None = None,
    producto: str = "Camisa Oxford",
) -> SimpleNamespace:
    subtotal = (Decimal(precio_unitario) - Decimal(descuento_unitario)) * cantidad
    venta_subtotal = sum(
        ((Decimal(p) - Decimal(d)) * c for p, c, d in venta_items), Decimal("0")
    ) if venta_items else subtotal
    return SimpleNamespace(
        venta_id=venta_id,
        numero=numero,
        confirmada_at=confirmada,
        canal=CanalVenta.TIENDA,
        venta_subtotal=venta_subtotal,
        venta_descuento=Decimal(venta_descuento),
        venta_total=venta_subtotal - Decimal(venta_descuento),
        vendedor_nombre="Lucía",
        vendedor_apellidos="Pérez",
        sku_id=sku_id,
        cantidad=cantidad,
        precio_normal=Decimal(precio_normal),
        precio_unitario=Decimal(precio_unitario),
        descuento_unitario=Decimal(descuento_unitario),
        subtotal=subtotal,
        costo_unitario=None if costo is None else Decimal(costo),
        producto_nombre=producto,
        color_nombre="Azul",
        talla_etiqueta="M",
        codigo_barras="779",
    )


def _datos() -> tuple[list[SimpleNamespace], list[tuple[UUID, MetodoPago, Decimal]]]:
    """
    Venta 1 (octubre): 2 jeans a 259 con 10 de descuento por unidad + 1 camisa
    rebajada de 189 a 159, y 20 de descuento general. Pagada EFECTIVO + QR.
    Venta 2 (noviembre): 1 camisa a 189 sin costo cargado, pagada con QR.
    """
    v1, v2 = uuid4(), uuid4()
    oct_ = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
    nov = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
    items_v1 = [("259", 2, "10"), ("159", 1, "0")]
    rows = [
        _row(v1, 1, oct_, sku_id=SKU_JEAN, cantidad=2, precio_normal="259", precio_unitario="259",
             descuento_unitario="10", costo="120", venta_descuento="20", venta_items=items_v1, producto="Jean recto"),
        _row(v1, 1, oct_, sku_id=SKU_CAMISA, cantidad=1, precio_normal="189", precio_unitario="159",
             costo="88", venta_descuento="20", venta_items=items_v1),
        _row(v2, 2, nov, sku_id=SKU_CAMISA, cantidad=1, precio_normal="189", precio_unitario="189", costo=None),
    ]
    # Venta 1: subtotal 498 + 159 = 657; total 637.
    pagos = [
        (v1, MetodoPago.EFECTIVO, Decimal("400")),
        (v1, MetodoPago.QR, Decimal("237")),
        (v2, MetodoPago.QR, Decimal("189")),
    ]
    return rows, pagos


def _repo(rows, pagos, *, anuladas=(1, Decimal("99")), primera=None):
    return (
        patch.object(FinanzasRepository, "lineas", new=AsyncMock(return_value=rows)),
        patch.object(FinanzasRepository, "pagos", new=AsyncMock(return_value=pagos)),
        patch.object(FinanzasRepository, "anuladas", new=AsyncMock(return_value=anuladas)),
        patch.object(FinanzasRepository, "primera_confirmacion", new=AsyncMock(return_value=primera)),
    )


async def _ventas(**kwargs):
    rows, pagos = _datos()
    a, b, c, d = _repo(rows, pagos, primera=rows[0].confirmada_at)
    with a, b, c, d:
        return await FinanzasService.ventas(MagicMock(), get_settings(), **kwargs)


async def _rentabilidad(**kwargs):
    rows, pagos = _datos()
    a, b, c, d = _repo(rows, pagos, primera=rows[0].confirmada_at)
    with a, b, c, d:
        return await FinanzasService.rentabilidad(MagicMock(), get_settings(), **kwargs)


# ---------------------------------------------------------------- período


@pytest.mark.asyncio
async def test_rango_invertido_responde_422() -> None:
    with pytest.raises(AppException) as error:
        await FinanzasService.ventas(MagicMock(), get_settings(), desde=date(2026, 11, 7), hasta=date(2026, 11, 1))

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_sin_filtros_va_desde_la_primera_venta_hasta_hoy_sin_limitar_la_consulta() -> None:
    rows, pagos = _datos()
    a, b, c, d = _repo(rows, pagos, primera=rows[0].confirmada_at)
    with a as lineas, b, c, d:
        reporte = await FinanzasService.ventas(MagicMock(), get_settings())

    assert reporte.periodo.sin_filtros is True
    assert reporte.periodo.desde == rows[0].confirmada_at.astimezone(TZ).date()
    assert reporte.periodo.hasta == reporte.periodo.generado_at.date()
    lineas.assert_awaited_once()
    assert lineas.await_args.args == (None, None)


@pytest.mark.asyncio
async def test_con_fechas_consulta_dias_completos_de_la_tienda() -> None:
    rows, pagos = _datos()
    a, b, c, d = _repo(rows, pagos)
    with a as lineas, b, c, d:
        reporte = await FinanzasService.ventas(
            MagicMock(), get_settings(), desde=date(2026, 10, 1), hasta=date(2026, 10, 31)
        )

    desde_at, hasta_at = lineas.await_args.args
    assert (desde_at.date(), hasta_at.date()) == (date(2026, 10, 1), date(2026, 11, 1))
    assert desde_at.utcoffset() == timedelta(hours=get_settings().TIMEZONE_OFFSET_HOURS)
    assert reporte.periodo.sin_filtros is False


# ---------------------------------------------------------------- ventas


@pytest.mark.asyncio
async def test_ventas_reparte_el_descuento_general_y_cuadra_con_el_total() -> None:
    reporte = await _ventas()
    jean, camisa, otra = reporte.detalle

    # 20 de descuento sobre 657: 498/657 al jean y el resto a la camisa.
    assert jean.descuento_venta == Decimal("15.16")
    assert camisa.descuento_venta == Decimal("4.84")
    assert jean.descuento_prenda == Decimal("20")
    assert jean.total == Decimal("482.84")
    assert jean.total + camisa.total == Decimal("637")
    assert sum((linea.total for linea in reporte.detalle), Decimal("0")) == reporte.resumen.total_vendido
    assert jean.metodos_pago == [MetodoPago.EFECTIVO, MetodoPago.QR]
    assert otra.metodos_pago == [MetodoPago.QR]
    assert jean.vendedor == "Lucía Pérez"


@pytest.mark.asyncio
async def test_resumen_de_ventas_y_cobrado_por_metodo() -> None:
    r = (await _ventas()).resumen
    reporte = await _ventas()

    assert (r.ventas, r.unidades) == (2, 4)
    assert r.venta_precio_normal == Decimal("896")  # 259×2 + 189 + 189
    assert r.rebajas == Decimal("30")
    assert (r.descuentos_prenda, r.descuentos_venta) == (Decimal("20"), Decimal("20"))
    assert r.venta_precio_normal - r.rebajas - r.descuentos_prenda - r.descuentos_venta == r.total_vendido
    assert r.total_vendido == Decimal("826")
    assert r.ticket_promedio == Decimal("413.00")
    assert (r.ventas_anuladas, r.monto_anulado) == (1, Decimal("99"))
    # QR suma en las dos ventas; ordenado de mayor a menor monto.
    assert [(m.metodo, m.pagos, m.monto) for m in reporte.cobrado_por_metodo] == [
        (MetodoPago.QR, 2, Decimal("426")),
        (MetodoPago.EFECTIVO, 1, Decimal("400")),
    ]
    assert sum((m.monto for m in reporte.cobrado_por_metodo), Decimal("0")) == r.total_vendido


@pytest.mark.asyncio
async def test_ventas_sin_datos_no_divide_por_cero() -> None:
    a, b, c, d = _repo([], [], anuladas=(0, Decimal("0")))
    with a, b, c, d:
        reporte = await FinanzasService.ventas(MagicMock(), get_settings())

    assert reporte.detalle == []
    assert (reporte.resumen.ventas, reporte.resumen.ticket_promedio) == (0, Decimal("0"))
    assert reporte.periodo.desde == reporte.periodo.hasta


# ---------------------------------------------------------------- rentabilidad


@pytest.mark.asyncio
async def test_rentabilidad_una_linea_por_sku_de_mayor_a_menor_margen() -> None:
    reporte = await _rentabilidad()
    camisa, jean = reporte.detalle

    # La camisa deja 255.16 y el jean 242.84.
    assert (camisa.sku_id, jean.sku_id) == (SKU_CAMISA, SKU_JEAN)
    assert camisa.margen_bruto > jean.margen_bruto
    assert jean.ingreso_neto == Decimal("482.84")
    assert jean.costo == Decimal("240")
    assert jean.margen_bruto == Decimal("242.84")
    # La camisa junta sus dos ventas; la de noviembre no tiene costo.
    assert camisa.cantidad == 2
    assert camisa.venta_precio_normal == Decimal("378")
    assert camisa.ingreso_neto == Decimal("343.16")
    assert camisa.descuentos == camisa.venta_precio_normal - camisa.ingreso_neto
    assert camisa.costo == Decimal("88")
    assert camisa.margen_porcentaje == Decimal("0.7436")


@pytest.mark.asyncio
async def test_resumen_y_meses_de_rentabilidad_cuadran_con_el_detalle() -> None:
    reporte = await _rentabilidad()
    r = reporte.resumen

    assert r.ingreso_neto == sum((linea.ingreso_neto for linea in reporte.detalle), Decimal("0"))
    assert r.ingreso_neto == Decimal("826")
    assert r.costo == Decimal("328")
    assert r.margen_bruto == Decimal("498")
    assert r.venta_precio_normal - r.descuentos == r.ingreso_neto
    assert r.unidades_sin_costo == 1
    assert [(m.anio, m.mes, m.unidades) for m in reporte.por_mes] == [(2026, 10, 3), (2026, 11, 1)]
    assert sum((m.margen_bruto for m in reporte.por_mes), Decimal("0")) == r.margen_bruto


# ---------------------------------------------------------------- excel


def _actor() -> CurrentUser:
    return CurrentUser(id=uuid4(), rol=Role.OWNER)


def _contexto_patches():
    return (
        patch.object(ConfigRepository, "get", new=AsyncMock(return_value=SimpleNamespace(nombre_tienda="Pinodo"))),
        patch.object(
            UsuarioRepository,
            "get_by_id",
            new=AsyncMock(return_value=SimpleNamespace(nombre="Adan", apellidos="Rivera")),
        ),
    )


@pytest.mark.asyncio
async def test_excel_de_ventas_tiene_resumen_y_detalle_filtrable() -> None:
    rows, pagos = _datos()
    a, b, c, d = _repo(rows, pagos, primera=rows[0].confirmada_at)
    e, f = _contexto_patches()
    with a, b, c, d, e, f:
        nombre, contenido = await FinanzasService.ventas_excel(MagicMock(), get_settings(), _actor())

    libro = load_workbook(BytesIO(contenido))
    assert nombre.startswith("ventas_") and nombre.endswith(".xlsx")
    assert libro.sheetnames == ["Resumen", "Detalle"]
    resumen = {fila[0]: fila[1] for fila in libro["Resumen"].iter_rows(values_only=True) if fila[0]}
    assert resumen["Pinodo — Reporte de ventas"] is None
    assert resumen["Total vendido"] == 826
    detalle = libro["Detalle"]
    assert detalle.auto_filter.ref is not None
    filas = list(detalle.iter_rows(values_only=True))
    total = next(fila for fila in filas if fila[0] == "Total filtrado")
    assert total[15].startswith("=SUBTOTAL(109,P")
    titulos = next(fila for fila in filas if fila[0] == "Fecha")
    datos = filas[filas.index(titulos) + 1:]
    assert len(datos) == 3
    assert datos[0][5] == "EFECTIVO + QR"
    assert sum(fila[15] for fila in datos) == pytest.approx(826)


@pytest.mark.asyncio
async def test_excel_de_rentabilidad_tiene_margen_por_mes_y_un_sku_por_fila() -> None:
    rows, pagos = _datos()
    a, b, c, d = _repo(rows, pagos, primera=rows[0].confirmada_at)
    e, f = _contexto_patches()
    with a, b, c, d, e, f:
        nombre, contenido = await FinanzasService.rentabilidad_excel(MagicMock(), get_settings(), _actor())

    libro = load_workbook(BytesIO(contenido))
    assert nombre.startswith("rentabilidad_")
    assert libro.sheetnames == ["Resumen", "Detalle"]
    resumen = [fila for fila in libro["Resumen"].iter_rows(values_only=True) if fila[0]]
    assert ("Octubre 2026", 3) == resumen[[f[0] for f in resumen].index("Octubre 2026")][:2]
    filas = list(libro["Detalle"].iter_rows(values_only=True))
    titulos = next(fila for fila in filas if fila[0] == "Producto")
    datos = filas[filas.index(titulos) + 1:]
    assert [fila[0] for fila in datos] == ["Camisa Oxford", "Jean recto"]
    total = next(fila for fila in filas if fila[0] == "Total filtrado")
    assert total[10].startswith("=IFERROR(J")
