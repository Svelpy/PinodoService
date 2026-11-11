from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.base_model import utc_now
from app.core.config import get_settings
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.movimientos_inventario.repositories import MovimientoInventarioRepository
from app.domains.movimientos_inventario.schemas import MovimientoInventarioCreate
from app.domains.movimientos_inventario.services import MovimientoInventarioService
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.shared.enums import TipoMovimiento
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _sku(cantidad: int = 10, costo: str = "10") -> Sku:
    return Sku(
        producto_color_id=uuid4(),
        talla_id=uuid4(),
        precio={"normal": 29.95, "rebajado": None, "rebaja_hasta": None},
        stock={"cantidad": cantidad, "minimo": 2, "actualizado": None},
        costo=Decimal(costo),
    )


@contextmanager
def _repos(sku: Sku | None) -> Iterator[dict[str, MagicMock]]:
    with (
        patch.object(SkuRepository, "get_by_id", new=AsyncMock(return_value=sku)) as get_sku,
        patch.object(MovimientoInventarioRepository, "add") as add,
        patch.object(
            MovimientoInventarioService,
            "get",
            new=AsyncMock(side_effect=lambda s, movimiento_id, **_: movimiento_id),
        ),
    ):
        yield {"get_sku": get_sku, "add": add}


def _registrar(sku: Sku, tipo: TipoMovimiento, cantidad: int, **kwargs: object) -> MovimientoInventario:
    with patch.object(MovimientoInventarioRepository, "add"):
        return MovimientoInventarioService.registrar(
            _session(), sku, tipo, cantidad, uuid4(), utc_now(), **kwargs
        )


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
def test_costo_promedio_ponderado(
    stock: int, costo: str, cantidad: int, costo_unitario: str, esperado: str
) -> None:
    resultado = MovimientoInventarioService.costo_promedio(
        stock, Decimal(costo), cantidad, Decimal(costo_unitario)
    )

    assert resultado == Decimal(esperado)


# ---------------------------------------------------------------- registrar


def test_ingreso_sube_stock_y_recalcula_el_promedio() -> None:
    sku = _sku(cantidad=10, costo="10")

    movimiento = _registrar(sku, TipoMovimiento.INGRESO, 10, costo_unitario=Decimal("20"), motivo="Lote")

    assert sku.stock["cantidad"] == 10 + 10
    assert sku.stock["actualizado"] is not None
    assert sku.costo == Decimal("15.00")
    assert (movimiento.cantidad, movimiento.saldo) == (10, 20)
    assert (movimiento.costo_unitario, movimiento.costo_promedio) == (Decimal("20"), Decimal("15.00"))
    assert movimiento.motivo == "Lote"
    assert movimiento.venta_id is None


@pytest.mark.parametrize("cantidad", [-3, 3])
def test_ajuste_mueve_el_stock_sin_cambiar_el_costo(cantidad: int) -> None:
    sku = _sku(cantidad=10, costo="10")

    movimiento = _registrar(sku, TipoMovimiento.AJUSTE, cantidad, motivo="Conteo")

    assert sku.stock["cantidad"] == 10 + cantidad
    assert sku.costo == Decimal("10")
    assert movimiento.costo_unitario == movimiento.costo_promedio == Decimal("10")


def test_movimiento_que_deja_stock_negativo_responde_409_sin_tocar_el_sku() -> None:
    sku = _sku(cantidad=2)

    with pytest.raises(AppException) as error:
        _registrar(sku, TipoMovimiento.AJUSTE, -3, motivo="Merma")

    assert error.value.status_code == 409
    assert error.value.details["stock_actual"] == 2
    assert "cantidad" in error.value.details
    assert sku.stock["cantidad"] == 2


def test_anulacion_sin_costo_conocido_usa_el_promedio_actual() -> None:
    # Ítems de ventas confirmadas antes del kardex: costo_unitario null.
    sku = _sku(cantidad=4, costo="9")

    movimiento = _registrar(sku, TipoMovimiento.ANULACION, 1, venta_id=uuid4())

    assert movimiento.costo_unitario == Decimal("9")
    assert sku.costo == Decimal("9")
    assert sku.stock["cantidad"] == 5


# ---------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_bloquea_el_sku_registra_y_hace_commit() -> None:
    sku = _sku(cantidad=4, costo="10")
    actor_id = uuid4()
    session = _session()
    data = MovimientoInventarioCreate.model_validate(
        {"sku_id": str(sku.id), "tipo": "INGRESO", "cantidad": 6, "costo_unitario": "15"}
    )

    with _repos(sku) as repos:
        resultado = await MovimientoInventarioService.create(session, data, actor_id)

    assert repos["get_sku"].call_args.kwargs == {"for_update": True}
    [movimiento] = [call.args[0] for call in repos["add"].call_args_list]
    assert resultado == movimiento.id
    assert movimiento.created_by == actor_id
    assert (movimiento.tipo, movimiento.saldo) == (TipoMovimiento.INGRESO, 10)
    assert sku.costo == Decimal("13.00")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_con_sku_inexistente_responde_422() -> None:
    data = MovimientoInventarioCreate.model_validate(
        {"sku_id": str(uuid4()), "tipo": "AJUSTE", "cantidad": 1, "motivo": "Conteo"}
    )
    session = _session()

    with _repos(None) as repos, pytest.raises(AppException) as error:
        await MovimientoInventarioService.create(session, data, uuid4())

    assert error.value.status_code == 422
    repos["add"].assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_ajuste_que_deja_stock_negativo_no_hace_commit() -> None:
    sku = _sku(cantidad=1)
    data = MovimientoInventarioCreate.model_validate(
        {"sku_id": str(sku.id), "tipo": "AJUSTE", "cantidad": -2, "motivo": "Merma"}
    )
    session = _session()

    with _repos(sku), pytest.raises(AppException) as error:
        await MovimientoInventarioService.create(session, data, uuid4())

    assert error.value.status_code == 409
    session.commit.assert_not_awaited()


# ---------------------------------------------------------------- lectura


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with (
        patch.object(MovimientoInventarioRepository, "get_by_id", new=AsyncMock(return_value=None)),
        pytest.raises(AppException) as error,
    ):
        await MovimientoInventarioService.get(_session(), uuid4())

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_list_convierte_fechas_de_la_tienda_y_pagina() -> None:
    with patch.object(
        MovimientoInventarioRepository, "find_many", new=AsyncMock(return_value=([], 41))
    ) as find:
        page = await MovimientoInventarioService.list(
            _session(),
            get_settings(),
            page=3,
            per_page=20,
            tipo=TipoMovimiento.AJUSTE,
            desde=date(2026, 11, 1),
            hasta=date(2026, 11, 7),
        )

    assert (page.total, page.total_pages) == (41, 3)
    kwargs = find.call_args.kwargs
    assert (kwargs["offset"], kwargs["limit"], kwargs["tipo"]) == (40, 20, TipoMovimiento.AJUSTE)
    assert kwargs["hasta"] - kwargs["desde"] == date(2026, 11, 8) - date(2026, 11, 1)
    assert kwargs["desde"].date() == date(2026, 11, 1)


@pytest.mark.asyncio
async def test_list_rechaza_rango_invertido() -> None:
    with pytest.raises(AppException) as error:
        await MovimientoInventarioService.list(
            _session(), get_settings(), desde=date(2026, 11, 7), hasta=date(2026, 11, 1)
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_list_costos_valoriza_el_stock() -> None:
    sku = _sku(cantidad=12, costo="12.50")
    producto_id = uuid4()
    row = (sku, producto_id, "Camisa Oxford", uuid4(), "Azul marino", "#1E3A8A", "M")

    with patch.object(SkuRepository, "list_inventario", new=AsyncMock(return_value=([row], 1))) as inventario:
        page = await MovimientoInventarioService.list_costos(_session(), nombre="camisa")

    [item] = page.data
    assert (item.sku_id, item.producto_id, item.talla_etiqueta) == (sku.id, producto_id, "M")
    assert (item.cantidad, item.costo, item.valor) == (12, Decimal("12.50"), Decimal("150.00"))
    assert inventario.call_args.kwargs["nombre"] == "camisa"
