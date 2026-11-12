from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.base_model import utc_now
from app.core.config import get_settings
from app.domains.ajustes_inventario.models import AjusteInventario
from app.domains.ajustes_inventario.repositories import AjusteInventarioRepository
from app.domains.ajustes_inventario.schemas import AjusteInventarioCreate, AjusteInventarioDetail
from app.domains.ajustes_inventario.services import AjusteInventarioService, CargaInicial
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.movimientos_inventario.repositories import MovimientoInventarioRepository
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


def _data(motivo: str, *items: dict[str, object], nota: str | None = None) -> AjusteInventarioCreate:
    return AjusteInventarioCreate.model_validate({"motivo": motivo, "nota": nota, "items": list(items)})


@contextmanager
def _repos(*skus: Sku) -> Iterator[dict[str, MagicMock]]:
    with (
        patch.object(SkuRepository, "list_active_by_ids", new=AsyncMock(return_value=list(skus))) as get_skus,
        patch.object(AjusteInventarioRepository, "add") as add_ajuste,
        patch.object(MovimientoInventarioRepository, "add") as add_movimiento,
        patch.object(AjusteInventarioService, "get", new=AsyncMock(return_value=DETAIL)) as get,
    ):
        yield {"get_skus": get_skus, "add_ajuste": add_ajuste, "add_movimiento": add_movimiento, "get": get}


DETAIL = AjusteInventarioDetail.model_validate(AjusteInventarioDetail.model_config["json_schema_extra"]["example"])


def _added(mock: MagicMock) -> list[object]:
    return [call.args[0] for call in mock.call_args_list]


# ---------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_recepcion_crea_un_documento_con_una_linea_por_sku() -> None:
    camisa, pantalon = _sku(cantidad=4, costo="10"), _sku(cantidad=0, costo="0")
    actor_id = uuid4()
    session = _session()
    data = _data(
        "RECEPCION",
        {"sku_id": str(camisa.id), "cantidad": 6, "costo_unitario": "15"},
        {"sku_id": str(pantalon.id), "cantidad": 3, "costo_unitario": "40"},
        nota="Factura 4521",
    )

    with _repos(camisa, pantalon) as repos:
        resultado = await AjusteInventarioService.create(session, data, actor_id)

    assert repos["get_skus"].call_args.args[0] == [camisa.id, pantalon.id]
    assert repos["get_skus"].call_args.kwargs == {"for_update": True}
    [ajuste] = _added(repos["add_ajuste"])
    assert (ajuste.motivo, ajuste.nota, ajuste.created_by) == (MotivoAjuste.RECEPCION, "Factura 4521", actor_id)
    movimientos: list[MovimientoInventario] = _added(repos["add_movimiento"])
    assert [m.sku_id for m in movimientos] == [camisa.id, pantalon.id]
    assert all(m.tipo == TipoMovimiento.AJUSTE and m.ajuste_id == ajuste.id for m in movimientos)
    assert (camisa.costo, pantalon.costo) == (Decimal("13.00"), Decimal("40"))
    assert (camisa.stock["cantidad"], pantalon.stock["cantidad"]) == (10, 3)
    session.commit.assert_awaited_once()
    repos["get"].assert_awaited_once_with(session, ajuste.id)
    assert (resultado.ajuste, resultado.sin_diferencia) == (DETAIL, [])


@pytest.mark.parametrize("motivo", ["MERMA", "ROBO_PERDIDA"])
@pytest.mark.asyncio
async def test_salidas_restan_lo_enviado_sin_cambiar_el_costo(motivo: str) -> None:
    sku = _sku(cantidad=5, costo="10")

    with _repos(sku) as repos:
        await AjusteInventarioService.create(_session(), _data(motivo, {"sku_id": str(sku.id), "cantidad": 2}), uuid4())

    [movimiento] = _added(repos["add_movimiento"])
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

    with _repos(sobra, falta, igual) as repos:
        resultado = await AjusteInventarioService.create(_session(), data, uuid4())

    assert [(m.cantidad, m.saldo) for m in _added(repos["add_movimiento"])] == [(2, 7), (-5, 0)]
    assert resultado.sin_diferencia == [igual.id]


@pytest.mark.asyncio
async def test_conteo_sin_diferencias_no_crea_documento() -> None:
    sku = _sku(cantidad=5)
    session = _session()

    with _repos(sku) as repos:
        resultado = await AjusteInventarioService.create(
            session, _data("CONTEO", {"sku_id": str(sku.id), "cantidad_contada": 5}), uuid4()
        )

    assert (resultado.ajuste, resultado.sin_diferencia) == (None, [sku.id])
    repos["add_ajuste"].assert_not_called()
    repos["add_movimiento"].assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_sku_inexistente_responde_422_con_su_posicion() -> None:
    sku = _sku()
    data = _data("MERMA", {"sku_id": str(sku.id), "cantidad": 1}, {"sku_id": str(uuid4()), "cantidad": 1})
    session = _session()

    with _repos(sku) as repos, pytest.raises(AppException) as error:
        await AjusteInventarioService.create(session, data, uuid4())

    assert error.value.status_code == 422
    assert "items -> 1 -> sku_id" in error.value.details
    repos["add_ajuste"].assert_not_called()
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
        await AjusteInventarioService.create(session, data, uuid4())

    assert error.value.status_code == 409
    assert error.value.details["stock_actual"] == 1
    assert "items -> 1" in error.value.details
    session.commit.assert_not_awaited()


# ---------------------------------------------------------------- carga inicial


def test_carga_inicial_crea_un_solo_documento_al_primer_sku_con_stock() -> None:
    actor_id = uuid4()
    camisa, pantalon = _sku(cantidad=0, costo="0"), _sku(cantidad=0, costo="0")

    with (
        patch.object(AjusteInventarioRepository, "add") as add_ajuste,
        patch.object(MovimientoInventarioRepository, "add") as add_movimiento,
    ):
        carga = CargaInicial(MagicMock(), actor_id, utc_now())
        assert carga.ajuste is None
        carga.registrar(camisa, 4, Decimal("20"))
        carga.registrar(pantalon, 6, Decimal("25"))

    [ajuste] = _added(add_ajuste)
    assert (ajuste.motivo, ajuste.created_by) == (MotivoAjuste.INICIAL, actor_id)
    movimientos = _added(add_movimiento)
    assert [(m.cantidad, m.costo_unitario, m.ajuste_id) for m in movimientos] == [
        (4, Decimal("20"), ajuste.id),
        (6, Decimal("25"), ajuste.id),
    ]
    assert (camisa.costo, pantalon.costo) == (Decimal("20"), Decimal("25"))


# ---------------------------------------------------------------- lectura


def _row(numero: int = 12) -> tuple[object, ...]:
    ajuste = AjusteInventario(numero=numero, motivo=MotivoAjuste.RECEPCION, nota="Factura", created_at=utc_now())
    return (ajuste, 2, 36, Decimal("450.00"))


@pytest.mark.asyncio
async def test_get_responde_el_documento_con_sus_lineas() -> None:
    row = _row()

    with (
        patch.object(AjusteInventarioRepository, "get_by_id", new=AsyncMock(return_value=row)),
        patch.object(MovimientoInventarioService, "list_by_ajuste", new=AsyncMock(return_value=[])) as lineas,
    ):
        detail = await AjusteInventarioService.get(_session(), row[0].id)

    assert (detail.numero, detail.items, detail.unidades, detail.valor) == (12, 2, 36, Decimal("450.00"))
    assert detail.movimientos == []
    assert lineas.await_args.args[1] == row[0].id


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with (
        patch.object(AjusteInventarioRepository, "get_by_id", new=AsyncMock(return_value=None)),
        pytest.raises(AppException) as error,
    ):
        await AjusteInventarioService.get(_session(), uuid4())

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_list_filtra_y_convierte_fechas() -> None:
    with patch.object(AjusteInventarioRepository, "find_many", new=AsyncMock(return_value=([_row()], 21))) as find:
        page = await AjusteInventarioService.list(
            _session(),
            get_settings(),
            page=2,
            per_page=20,
            motivo=MotivoAjuste.RECEPCION,
            desde=date(2026, 11, 1),
            hasta=date(2026, 11, 1),
        )

    assert (page.total, page.total_pages, page.data[0].numero) == (21, 2, 12)
    kwargs = find.call_args.kwargs
    assert (kwargs["offset"], kwargs["motivo"]) == (20, MotivoAjuste.RECEPCION)
    assert kwargs["hasta"] - kwargs["desde"] == date(2026, 11, 2) - date(2026, 11, 1)
