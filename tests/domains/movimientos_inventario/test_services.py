from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.base_model import utc_now
from app.core.config import get_settings
from app.domains.ajustes_inventario.models import AjusteInventario
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.movimientos_inventario.repositories import MovimientoInventarioRepository
from app.domains.movimientos_inventario.services import MovimientoInventarioService
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.domains.ventas.models import Venta
from app.shared.enums import MotivoAjuste, Role, TipoMovimiento
from app.shared.errors.exceptions import AppException


def _sku(cantidad: int = 10, costo: str = "10") -> Sku:
    return Sku(
        producto_color_id=uuid4(),
        talla_id=uuid4(),
        precio={"normal": 29.95, "rebajado": None, "rebaja_hasta": None},
        stock={"cantidad": cantidad, "minimo": 2, "actualizado": None},
        costo=Decimal(costo),
    )


def _registrar(sku: Sku, tipo: TipoMovimiento, cantidad: int, **kwargs: object) -> MovimientoInventario:
    with patch.object(MovimientoInventarioRepository, "add"):
        return MovimientoInventarioService.registrar(MagicMock(), sku, tipo, cantidad, uuid4(), utc_now(), **kwargs)


# ---------------------------------------------------------------- costo promedio


@pytest.mark.parametrize(
    ("stock", "costo", "cantidad", "costo_unitario", "esperado"),
    [
        (10, "10", 10, "20", "15.00"),
        (0, "10", 5, "18", "18"),  # sin stock previo, el promedio es el costo que entra
        (3, "10", 1, "11", "10.25"),
        (2, "0", 2, "10", "5.00"),  # saldo inicial a costo 0 de la migración
        (1, "1", 2, "0.01", "0.34"),  # redondea al centavo
    ],
)
def test_costo_promedio_ponderado(stock: int, costo: str, cantidad: int, costo_unitario: str, esperado: str) -> None:
    resultado = MovimientoInventarioService.costo_promedio(stock, Decimal(costo), cantidad, Decimal(costo_unitario))

    assert resultado == Decimal(esperado)


# ---------------------------------------------------------------- registrar


def test_entrada_con_costo_sube_stock_y_recalcula_el_promedio() -> None:
    sku = _sku(cantidad=10, costo="10")
    ajuste_id = uuid4()

    movimiento = _registrar(sku, TipoMovimiento.AJUSTE, 10, costo_unitario=Decimal("20"), ajuste_id=ajuste_id)

    assert sku.stock["cantidad"] == 20
    assert sku.stock["actualizado"] is not None
    assert sku.costo == Decimal("15.00")
    assert (movimiento.cantidad, movimiento.saldo) == (10, 20)
    assert (movimiento.costo_unitario, movimiento.costo_promedio) == (Decimal("20"), Decimal("15.00"))
    assert (movimiento.ajuste_id, movimiento.venta_id) == (ajuste_id, None)
    # El responsable es quien registra el movimiento.
    assert movimiento.user_id is not None
    assert movimiento.user_id == movimiento.created_by


@pytest.mark.parametrize("cantidad", [-3, 3])
def test_movimiento_sin_costo_no_cambia_el_costo(cantidad: int) -> None:
    sku = _sku(cantidad=10, costo="10")

    movimiento = _registrar(sku, TipoMovimiento.AJUSTE, cantidad, ajuste_id=uuid4())

    assert sku.stock["cantidad"] == 10 + cantidad
    assert sku.costo == Decimal("10")
    assert movimiento.costo_unitario == movimiento.costo_promedio == Decimal("10")


def test_salida_con_costo_no_recalcula_el_promedio() -> None:
    sku = _sku(cantidad=10, costo="10")

    _registrar(sku, TipoMovimiento.VENTA, -2, costo_unitario=Decimal("99"), venta_id=uuid4())

    assert sku.costo == Decimal("10")


def test_movimiento_que_deja_stock_negativo_responde_409_sin_tocar_el_sku() -> None:
    sku = _sku(cantidad=2)

    with pytest.raises(AppException) as error:
        _registrar(sku, TipoMovimiento.AJUSTE, -3, ajuste_id=uuid4(), field_name="items -> 0")

    assert error.value.status_code == 409
    assert error.value.details["stock_actual"] == 2
    assert "items -> 0" in error.value.details
    assert sku.stock["cantidad"] == 2


def test_anulacion_sin_costo_conocido_usa_el_promedio_actual() -> None:
    # Ítems de ventas confirmadas antes del kardex: costo_unitario null.
    sku = _sku(cantidad=4, costo="9")

    movimiento = _registrar(sku, TipoMovimiento.ANULACION, 1, venta_id=uuid4())

    assert movimiento.costo_unitario == Decimal("9")
    assert sku.costo == Decimal("9")
    assert sku.stock["cantidad"] == 5


# ---------------------------------------------------------------- item


def _row(movimiento: MovimientoInventario) -> tuple[object, ...]:
    return (movimiento, "841", uuid4(), "Camisa Oxford", "Azul marino", "M", "Lucía", None, Role.ADMIN)


def test_item_de_un_ajuste_resume_la_prenda_y_su_documento() -> None:
    ajuste = AjusteInventario(numero=12, motivo=MotivoAjuste.RECEPCION)
    movimiento = MovimientoInventario(
        sku_id=uuid4(),
        tipo=TipoMovimiento.AJUSTE,
        cantidad=24,
        saldo=36,
        costo_unitario=Decimal("13"),
        costo_promedio=Decimal("12"),
        ajuste_id=ajuste.id,
        user_id=uuid4(),
    )
    movimiento.ajuste = ajuste
    movimiento.venta = None

    item = MovimientoInventarioService.item(_row(movimiento))

    assert (item.sku.id, item.sku.producto_nombre, item.sku.talla_etiqueta) == (movimiento.sku_id, "Camisa Oxford", "M")
    assert item.origen.model_dump() == {"tipo": "AJUSTE", "id": ajuste.id, "numero": 12, "motivo": MotivoAjuste.RECEPCION}
    assert (item.costo_total, item.saldo_valor) == (Decimal("312"), Decimal("432"))
    assert item.usuario.model_dump() == {
        "id": movimiento.user_id,
        "nombre": "Lucía",
        "apellidos": None,
        "rol": Role.ADMIN,
    }


def test_item_de_una_venta_apunta_a_la_venta() -> None:
    venta = Venta(numero=9)
    movimiento = MovimientoInventario(
        sku_id=uuid4(),
        tipo=TipoMovimiento.VENTA,
        cantidad=-2,
        saldo=10,
        costo_unitario=Decimal("12.5"),
        costo_promedio=Decimal("12.5"),
        venta_id=venta.id,
        user_id=uuid4(),
    )
    movimiento.ajuste = None
    movimiento.venta = venta

    item = MovimientoInventarioService.item(_row(movimiento))

    assert item.origen.model_dump() == {"tipo": "VENTA", "id": venta.id, "numero": 9, "motivo": None}
    assert item.costo_total == Decimal("-25.0")


# ---------------------------------------------------------------- lectura


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with (
        patch.object(MovimientoInventarioRepository, "get_by_id", new=AsyncMock(return_value=None)),
        pytest.raises(AppException) as error,
    ):
        await MovimientoInventarioService.get(MagicMock(), uuid4())

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_list_convierte_fechas_de_la_tienda_y_pagina() -> None:
    with patch.object(MovimientoInventarioRepository, "find_many", new=AsyncMock(return_value=([], 41))) as find:
        page = await MovimientoInventarioService.list(
            MagicMock(),
            get_settings(),
            page=3,
            per_page=20,
            motivo=MotivoAjuste.MERMA,
            desde=date(2026, 11, 1),
            hasta=date(2026, 11, 7),
        )

    assert (page.total, page.total_pages) == (41, 3)
    kwargs = find.call_args.kwargs
    assert (kwargs["offset"], kwargs["limit"], kwargs["motivo"]) == (40, 20, MotivoAjuste.MERMA)
    assert kwargs["hasta"] - kwargs["desde"] == date(2026, 11, 8) - date(2026, 11, 1)
    assert kwargs["desde"].date() == date(2026, 11, 1)


@pytest.mark.asyncio
async def test_list_rechaza_rango_invertido() -> None:
    with pytest.raises(AppException) as error:
        await MovimientoInventarioService.list(MagicMock(), get_settings(), desde=date(2026, 11, 7), hasta=date(2026, 11, 1))

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_list_costos_valoriza_el_stock() -> None:
    sku = _sku(cantidad=12, costo="12.50")
    producto_id = uuid4()
    row = (sku, producto_id, "Camisa Oxford", uuid4(), "Azul marino", "#1E3A8A", "M")

    with patch.object(SkuRepository, "list_inventario", new=AsyncMock(return_value=([row], 1))) as inventario:
        page = await MovimientoInventarioService.list_costos(MagicMock(), nombre="camisa")

    [item] = page.data
    assert (item.sku_id, item.producto_id, item.talla_etiqueta) == (sku.id, producto_id, "M")
    assert (item.cantidad, item.costo, item.valor) == (12, Decimal("12.50"), Decimal("150.00"))
    assert inventario.call_args.kwargs["nombre"] == "camisa"
