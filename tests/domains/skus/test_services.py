from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.ajustes_inventario.repositories import AjusteInventarioRepository
from app.domains.movimientos_inventario.repositories import MovimientoInventarioRepository
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.domains.skus.schemas import SkuCreate, SkuResponse
from app.domains.skus.services import SkuService
from app.domains.tallas.models import Talla
from app.domains.tallas.repositories import TallaRepository
from app.shared.enums import MotivoAjuste, TipoMovimiento
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _sku(**overrides: object) -> Sku:
    values: dict[str, object] = {
        "producto_color_id": uuid4(),
        "talla_id": uuid4(),
        "codigo_barras": "8412345678905",
        "precio": {"normal": 29.95, "rebajado": None, "rebaja_hasta": None},
        "stock": {"cantidad": 5, "minimo": 2, "actualizado": None},
    }
    values.update(overrides)
    return Sku(**values)


def _create_data(**overrides: object) -> SkuCreate:
    values: dict[str, object] = {
        "producto_color_id": uuid4(),
        "talla_id": uuid4(),
        "precio": {"normal": "29.95", "rebajado": "19.90", "rebaja_hasta": "2026-12-31"},
        "costo": "12.50",
        "stock": {"cantidad": 12, "minimo": 3},
    }
    values.update(overrides)
    return SkuCreate.model_validate(values)


def _referencias_validas():
    return (
        patch.object(
            ProductoColorRepository,
            "get_by_id",
            new=AsyncMock(return_value=ProductoColor(producto_id=uuid4(), color_id=uuid4())),
        ),
        patch.object(TallaRepository, "get_by_id", new=AsyncMock(return_value=Talla(etiqueta="M"))),
    )


@pytest.mark.asyncio
async def test_create_guarda_precio_y_stock_como_json() -> None:
    session = _session()
    actor_id = uuid4()
    p1, p2 = _referencias_validas()

    with (
        p1,
        p2,
        patch.object(SkuRepository, "get_active_by_color_and_talla", new=AsyncMock(return_value=None)),
        patch.object(SkuRepository, "get_active_by_codigo_barras", new=AsyncMock()) as by_codigo,
        patch.object(SkuRepository, "add") as add,
        patch.object(MovimientoInventarioRepository, "add") as add_movimiento,
        patch.object(AjusteInventarioRepository, "add") as add_ajuste,
        patch.object(
            SkuService, "get", new=AsyncMock(side_effect=lambda *a, **k: add.call_args.args[0])
        ) as get,
    ):
        sku = await SkuService.create(session, _create_data(), actor_id)

    # El stock inicial entra al kardex por un documento INICIAL, a su costo.
    [ajuste] = [call.args[0] for call in add_ajuste.call_args_list]
    assert (ajuste.motivo, ajuste.created_by) == (MotivoAjuste.INICIAL, actor_id)
    [movimiento] = [call.args[0] for call in add_movimiento.call_args_list]
    assert (movimiento.sku_id, movimiento.tipo, movimiento.cantidad, movimiento.saldo, movimiento.ajuste_id) == (
        sku.id,
        TipoMovimiento.AJUSTE,
        12,
        12,
        ajuste.id,
    )
    assert movimiento.costo_unitario == movimiento.costo_promedio == Decimal("12.50")
    assert sku.costo == Decimal("12.50")
    assert "costo" not in SkuResponse.model_validate(sku).model_dump()

    get.assert_awaited_once_with(session, sku.id, load_detail=True)

    by_codigo.assert_not_awaited()
    assert sku.precio == {"normal": 29.95, "rebajado": 19.9, "rebaja_hasta": "2026-12-31"}
    assert sku.stock["cantidad"] == 12
    assert sku.stock["minimo"] == 3
    assert sku.stock["actualizado"] is not None
    assert sku.created_by == actor_id
    add.assert_called_once_with(sku)
    session.commit.assert_awaited_once()

    response = SkuResponse.model_validate(sku)
    assert str(response.precio.normal) == "29.95"
    assert response.stock.actualizado is not None


@pytest.mark.parametrize(
    ("color_existe", "talla_existe", "campo"),
    [(False, True, "producto_color_id"), (True, False, "talla_id")],
)
@pytest.mark.asyncio
async def test_create_rechaza_referencias_inexistentes(
    color_existe: bool,
    talla_existe: bool,
    campo: str,
) -> None:
    with (
        patch.object(
            ProductoColorRepository,
            "get_by_id",
            new=AsyncMock(
                return_value=ProductoColor(producto_id=uuid4(), color_id=uuid4()) if color_existe else None
            ),
        ),
        patch.object(
            TallaRepository,
            "get_by_id",
            new=AsyncMock(return_value=Talla(etiqueta="M") if talla_existe else None),
        ),
    ):
        with pytest.raises(AppException) as error:
            await SkuService.create(_session(), _create_data(), uuid4())

    assert error.value.status_code == 422
    assert campo in error.value.details


@pytest.mark.asyncio
async def test_create_rechaza_talla_repetida_en_el_color() -> None:
    p1, p2 = _referencias_validas()

    with (
        p1,
        p2,
        patch.object(
            SkuRepository,
            "get_active_by_color_and_talla",
            new=AsyncMock(return_value=_sku()),
        ),
    ):
        with pytest.raises(AppException) as error:
            await SkuService.create(_session(), _create_data(), uuid4())

    assert error.value.status_code == 409
    assert "talla_id" in error.value.details


@pytest.mark.asyncio
async def test_create_rechaza_codigo_de_barras_repetido() -> None:
    p1, p2 = _referencias_validas()

    with (
        p1,
        p2,
        patch.object(SkuRepository, "get_active_by_color_and_talla", new=AsyncMock(return_value=None)),
        patch.object(
            SkuRepository,
            "get_active_by_codigo_barras",
            new=AsyncMock(return_value=_sku()),
        ),
    ):
        with pytest.raises(AppException) as error:
            await SkuService.create(
                _session(),
                _create_data(codigo_barras="8412345678905"),
                uuid4(),
            )

    assert error.value.status_code == 409
    assert "codigo_barras" in error.value.details


@pytest.mark.asyncio
async def test_delete_es_logico() -> None:
    sku = _sku()
    actor_id = uuid4()
    session = _session()

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        await SkuService.delete(session, sku.id, actor_id)

    assert sku.is_deleted is True
    assert sku.deleted_by == actor_id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(SkuRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await SkuService.get(_session(), uuid4())

    assert error.value.status_code == 404


# --- Precio completo del PATCH del color: regla de rebaja vencida -----------

def _ayer() -> str:
    from datetime import timedelta

    from app.core.config import get_settings

    return (SkuService.local_today(get_settings()) - timedelta(days=1)).isoformat()


def test_replace_precio_rechaza_una_rebaja_nueva_con_fecha_vencida() -> None:
    from app.domains.skus.schemas import SkuPrecio

    actual = {"normal": 100.0, "rebajado": None, "rebaja_hasta": None}
    with pytest.raises(AppException) as error:
        SkuService.replace_precio(actual, SkuPrecio(normal=100, rebajado=70, rebaja_hasta=_ayer()))

    assert error.value.status_code == 422
    assert "ya pasó" in error.value.details["precio"]


def test_replace_precio_sin_tocar_la_rebaja_no_exige_su_fecha() -> None:
    from app.domains.skus.schemas import SkuPrecio

    # Cambiar solo el normal de un SKU con una rebaja vieja sigue funcionando.
    actual = {"normal": 100.0, "rebajado": 80.0, "rebaja_hasta": _ayer()}
    nuevo = SkuService.replace_precio(actual, SkuPrecio(normal=120, rebajado=80, rebaja_hasta=_ayer()))

    assert nuevo == {"normal": 120.0, "rebajado": 80.0, "rebaja_hasta": _ayer()}


def test_replace_precio_reemplaza_completo() -> None:
    from app.domains.skus.schemas import SkuPrecio

    actual = {"normal": 100.0, "rebajado": 80.0, "rebaja_hasta": "2099-01-31"}
    assert SkuService.replace_precio(actual, SkuPrecio(normal=90)) == {
        "normal": 90.0,
        "rebajado": None,
        "rebaja_hasta": None,
    }


# --- Inventario ---------------------------------------------------------------

from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402

from app.domains.skus.schemas import SkuPrecio  # noqa: E402


@pytest.mark.parametrize(
    ("precio", "esperado"),
    [
        ({"normal": 30}, Decimal("30")),
        ({"normal": 30, "rebajado": 20}, Decimal("20")),
        ({"normal": 30, "rebajado": 20, "rebaja_hasta": "2026-11-04"}, Decimal("20")),  # vence hoy
        ({"normal": 30, "rebajado": 20, "rebaja_hasta": "2026-11-03"}, Decimal("30")),  # venció ayer
    ],
)
def test_precio_vigente(precio: dict[str, object], esperado: Decimal) -> None:
    assert SkuService.precio_vigente(SkuPrecio.model_validate(precio), date(2026, 11, 4)) == esperado


def test_local_today_aplica_el_desfase_de_la_tienda() -> None:
    from datetime import datetime, timezone

    settings = MagicMock(TIMEZONE_OFFSET_HOURS=-4)
    # 02:00 UTC del 5 de noviembre son las 22:00 del 4 en la tienda.
    with patch(
        "app.domains.skus.services.utc_now",
        return_value=datetime(2026, 11, 5, 2, 0, tzinfo=timezone.utc),
    ):
        assert SkuService.local_today(settings) == date(2026, 11, 4)


@pytest.mark.asyncio
async def test_inventario_normaliza_el_codigo_y_rechaza_uno_invalido() -> None:
    settings = MagicMock(TIMEZONE_OFFSET_HOURS=-4)
    repo = AsyncMock(return_value=([], 0))

    with patch.object(SkuRepository, "list_inventario", new=repo):
        await SkuService.list_inventario(_session(), settings, codigo_barras="  841-23  ")
        with pytest.raises(AppException) as error:
            await SkuService.list_inventario(_session(), settings, codigo_barras="84 1")

    assert repo.await_args_list[0].kwargs["codigo_barras"] == "841-23"
    assert error.value.status_code == 422
    assert "codigo_barras" in error.value.details


# --- Código de barras sugerido ----------------------------------------------


@pytest.mark.parametrize(
    ("doce_digitos", "control"),
    [("400638133393", "1"), ("590123412345", "7"), ("200123456789", "3")],
)
def test_ean13_digito_control(doce_digitos: str, control: str) -> None:
    assert SkuService.ean13_digito_control(doce_digitos) == control


@pytest.mark.asyncio
async def test_sugerir_codigo_barras_devuelve_ean13_de_uso_interno() -> None:
    with patch.object(SkuRepository, "codigo_barras_usado", new=AsyncMock(return_value=False)):
        codigo = await SkuService.sugerir_codigo_barras(_session())

    assert len(codigo) == 13 and codigo.isdigit()
    assert codigo.startswith("20")
    assert codigo[-1] == SkuService.ean13_digito_control(codigo[:12])


@pytest.mark.asyncio
async def test_sugerir_codigo_barras_reintenta_si_ya_existe() -> None:
    with patch.object(
        SkuRepository, "codigo_barras_usado", new=AsyncMock(side_effect=[True, True, False])
    ) as usado:
        codigo = await SkuService.sugerir_codigo_barras(_session())

    assert usado.await_count == 3
    assert usado.await_args.args[0] == codigo


@pytest.mark.asyncio
async def test_sugerir_codigo_barras_falla_si_no_encuentra_uno_libre() -> None:
    with (
        patch.object(SkuRepository, "codigo_barras_usado", new=AsyncMock(return_value=True)),
        pytest.raises(AppException) as error,
    ):
        await SkuService.sugerir_codigo_barras(_session())

    assert error.value.status_code == 500


@pytest.mark.asyncio
async def test_create_sin_stock_no_registra_movimiento() -> None:
    p1, p2 = _referencias_validas()

    with (
        p1,
        p2,
        patch.object(SkuRepository, "get_active_by_color_and_talla", new=AsyncMock(return_value=None)),
        patch.object(SkuRepository, "get_active_by_codigo_barras", new=AsyncMock()),
        patch.object(SkuRepository, "add") as add,
        patch.object(MovimientoInventarioRepository, "add") as add_movimiento,
        patch.object(SkuService, "get", new=AsyncMock(side_effect=lambda *a, **k: add.call_args.args[0])),
    ):
        sku = await SkuService.create(_session(), _create_data(stock={"cantidad": 0, "minimo": 1}), uuid4())

    add_movimiento.assert_not_called()
    assert (sku.stock["cantidad"], sku.stock["minimo"], sku.costo) == (0, 1, Decimal("12.50"))


