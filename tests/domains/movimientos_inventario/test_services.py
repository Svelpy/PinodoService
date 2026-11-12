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
from app.domains.movimientos_inventario.schemas import AjusteInventarioCreate
from app.domains.movimientos_inventario.services import MovimientoInventarioService
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.shared.enums import MotivoAjuste, TipoMovimiento
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
def _repos(*skus: Sku) -> Iterator[dict[str, MagicMock]]:
    added: dict[object, MovimientoInventario] = {}
    with (
        patch.object(
            SkuRepository, "list_active_by_ids", new=AsyncMock(return_value=list(skus))
        ) as get_skus,
        patch.object(MovimientoInventarioRepository, "add") as add,
        patch.object(
            MovimientoInventarioRepository,
            "list_by_ids",
            new=AsyncMock(side_effect=lambda ids: [added[i] for i in ids]),
        ),
    ):
        add.side_effect = lambda movimiento: added.__setitem__(movimiento.id, movimiento)
        yield {"get_skus": get_skus, "add": add}


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


def test_recepcion_sube_stock_y_recalcula_el_promedio() -> None:
    sku = _sku(cantidad=10, costo="10")

    movimiento = _registrar(
        sku, TipoMovimiento.AJUSTE, 10, costo_unitario=Decimal("20"), motivo=MotivoAjuste.RECEPCION, nota="Lote"
    )

    assert sku.stock["cantidad"] == 10 + 10
    assert sku.stock["actualizado"] is not None
    assert sku.costo == Decimal("15.00")
    assert (movimiento.cantidad, movimiento.saldo) == (10, 20)
    assert (movimiento.costo_unitario, movimiento.costo_promedio) == (Decimal("20"), Decimal("15.00"))
    assert (movimiento.motivo, movimiento.nota) == (MotivoAjuste.RECEPCION, "Lote")
    assert movimiento.venta_id is None


def test_inicial_parte_del_costo_del_sku_nuevo() -> None:
    sku = _sku(cantidad=0, costo="22.40")

    movimiento = _registrar(sku, TipoMovimiento.INICIAL, 5, costo_unitario=Decimal("22.40"))

    assert (movimiento.saldo, movimiento.costo_promedio, sku.costo) == (5, Decimal("22.40"), Decimal("22.40"))


@pytest.mark.parametrize("cantidad", [-3, 3])
def test_ajuste_sin_costo_mueve_el_stock_sin_cambiar_el_costo(cantidad: int) -> None:
    sku = _sku(cantidad=10, costo="10")

    movimiento = _registrar(sku, TipoMovimiento.AJUSTE, cantidad, motivo=MotivoAjuste.CONTEO)

    assert sku.stock["cantidad"] == 10 + cantidad
    assert sku.costo == Decimal("10")
    assert movimiento.costo_unitario == movimiento.costo_promedio == Decimal("10")


def test_movimiento_que_deja_stock_negativo_responde_409_sin_tocar_el_sku() -> None:
    sku = _sku(cantidad=2)

    with pytest.raises(AppException) as error:
        _registrar(sku, TipoMovimiento.AJUSTE, -3, motivo=MotivoAjuste.MERMA)

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


# ---------------------------------------------------------------- ajustar


def _data(motivo: str, *items: dict[str, object], nota: str | None = None) -> AjusteInventarioCreate:
    return AjusteInventarioCreate.model_validate({"motivo": motivo, "nota": nota, "items": list(items)})


@pytest.mark.asyncio
async def test_recepcion_de_varios_skus_bloquea_registra_y_hace_commit() -> None:
    camisa, pantalon = _sku(cantidad=4, costo="10"), _sku(cantidad=0, costo="0")
    actor_id = uuid4()
    session = _session()
    data = _data(
        "RECEPCION",
        {"sku_id": str(camisa.id), "cantidad": 6, "costo_unitario": "15"},
        {"sku_id": str(pantalon.id), "cantidad": 3, "costo_unitario": "40"},
        nota="Lote",
    )

    with _repos(camisa, pantalon) as repos:
        resultado = await MovimientoInventarioService.ajustar(session, data, actor_id)

    assert repos["get_skus"].call_args.args[0] == [camisa.id, pantalon.id]
    assert repos["get_skus"].call_args.kwargs == {"for_update": True}
    assert [m.sku_id for m in resultado.movimientos] == [camisa.id, pantalon.id]
    primero = resultado.movimientos[0]
    assert (primero.tipo, primero.motivo, primero.nota) == (TipoMovimiento.AJUSTE, MotivoAjuste.RECEPCION, "Lote")
    assert primero.created_by == actor_id
    assert (camisa.costo, pantalon.costo) == (Decimal("13.00"), Decimal("40"))
    assert (camisa.stock["cantidad"], pantalon.stock["cantidad"]) == (10, 3)
    assert resultado.sin_diferencia == []
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("motivo", ["MERMA", "ROBO_PERDIDA"])
@pytest.mark.asyncio
async def test_salidas_restan_lo_enviado_sin_cambiar_el_costo(motivo: str) -> None:
    sku = _sku(cantidad=5, costo="10")

    with _repos(sku):
        resultado = await MovimientoInventarioService.ajustar(
            _session(), _data(motivo, {"sku_id": str(sku.id), "cantidad": 2}), uuid4()
        )

    [movimiento] = resultado.movimientos
    assert (movimiento.cantidad, movimiento.saldo, movimiento.costo_unitario) == (-2, 3, Decimal("10"))
    assert sku.costo == Decimal("10")


@pytest.mark.asyncio
async def test_conteo_registra_la_diferencia_y_omite_los_que_coinciden() -> None:
    sobra, falta, igual = _sku(cantidad=5), _sku(cantidad=5), _sku(cantidad=5)
    data = _data(
        "CONTEO",
        {"sku_id": str(sobra.id), "cantidad_contada": 7},
        {"sku_id": str(falta.id), "cantidad_contada": 0},
        {"sku_id": str(igual.id), "cantidad_contada": 5},
    )

    with _repos(sobra, falta, igual):
        resultado = await MovimientoInventarioService.ajustar(_session(), data, uuid4())

    assert [(m.cantidad, m.saldo) for m in resultado.movimientos] == [(2, 7), (-5, 0)]
    assert resultado.sin_diferencia == [igual.id]


@pytest.mark.asyncio
async def test_conteo_sin_diferencias_no_hace_commit() -> None:
    sku = _sku(cantidad=5)
    session = _session()

    with _repos(sku) as repos:
        resultado = await MovimientoInventarioService.ajustar(
            session, _data("CONTEO", {"sku_id": str(sku.id), "cantidad_contada": 5}), uuid4()
        )

    assert resultado.movimientos == [] and resultado.sin_diferencia == [sku.id]
    repos["add"].assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_sku_inexistente_responde_422_con_su_posicion() -> None:
    sku = _sku()
    data = _data("MERMA", {"sku_id": str(sku.id), "cantidad": 1}, {"sku_id": str(uuid4()), "cantidad": 1})
    session = _session()

    with _repos(sku) as repos, pytest.raises(AppException) as error:
        await MovimientoInventarioService.ajustar(session, data, uuid4())

    assert error.value.status_code == 422
    assert "items -> 1 -> sku_id" in error.value.details
    repos["add"].assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_stock_negativo_rechaza_todo_el_ajuste() -> None:
    alcanza, no_alcanza = _sku(cantidad=5), _sku(cantidad=1)
    data = _data(
        "MERMA",
        {"sku_id": str(alcanza.id), "cantidad": 1},
        {"sku_id": str(no_alcanza.id), "cantidad": 2},
    )
    session = _session()

    with _repos(alcanza, no_alcanza), pytest.raises(AppException) as error:
        await MovimientoInventarioService.ajustar(session, data, uuid4())

    assert error.value.status_code == 409
    assert error.value.details["stock_actual"] == 1
    assert "items -> 1" in error.value.details
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
