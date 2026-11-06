from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.domains.skus.schemas import SkuCreate, SkuResponse, SkuUpdate
from app.domains.skus.services import SkuService
from app.domains.tallas.models import Talla
from app.domains.tallas.repositories import TallaRepository
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
        patch.object(
            SkuService, "get", new=AsyncMock(side_effect=lambda *a, **k: add.call_args.args[0])
        ) as get,
    ):
        sku = await SkuService.create(session, _create_data(), actor_id)

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
async def test_update_stock_renueva_la_fecha_y_conserva_el_precio() -> None:
    sku = _sku()
    precio_original = dict(sku.precio)
    actor_id = uuid4()

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        result = await SkuService.update(
            _session(),
            sku.id,
            SkuUpdate.model_validate({"stock": {"cantidad": 0, "minimo": 2}}),
            actor_id,
        )

    assert result.stock["cantidad"] == 0
    assert result.stock["actualizado"] is not None
    assert result.precio == precio_original
    assert result.updated_by == actor_id


@pytest.mark.asyncio
async def test_update_precio_no_toca_el_stock() -> None:
    sku = _sku()
    stock_original = dict(sku.stock)

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        result = await SkuService.update(
            _session(),
            sku.id,
            SkuUpdate.model_validate({"precio": {"normal": 35, "rebajado": 25}}),
            uuid4(),
        )

    assert result.precio == {"normal": 35.0, "rebajado": 25.0, "rebaja_hasta": None}
    assert result.stock == stock_original


@pytest.mark.asyncio
async def test_update_codigo_barras_null_lo_quita_sin_validar_unicidad() -> None:
    sku = _sku()

    with (
        patch.object(SkuService, "get", new=AsyncMock(return_value=sku)),
        patch.object(SkuRepository, "get_active_by_codigo_barras", new=AsyncMock()) as by_codigo,
    ):
        result = await SkuService.update(
            _session(),
            sku.id,
            SkuUpdate(codigo_barras=None),
            uuid4(),
        )

    by_codigo.assert_not_awaited()
    assert result.codigo_barras is None


@pytest.mark.asyncio
async def test_update_talla_valida_unicidad_en_el_mismo_color() -> None:
    sku = _sku()
    nueva = Talla(etiqueta="L")

    with (
        patch.object(SkuService, "get", new=AsyncMock(return_value=sku)),
        patch.object(TallaRepository, "get_by_id", new=AsyncMock(return_value=nueva)),
        patch.object(
            SkuRepository,
            "get_active_by_color_and_talla",
            new=AsyncMock(return_value=_sku()),
        ) as unique,
    ):
        with pytest.raises(AppException) as error:
            await SkuService.update(_session(), sku.id, SkuUpdate(talla_id=nueva.id), uuid4())

    unique.assert_awaited_once_with(sku.producto_color_id, nueva.id, exclude_id=sku.id)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_update_vacio_no_hace_commit() -> None:
    sku = _sku()
    session = _session()

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        result = await SkuService.update(session, sku.id, SkuUpdate(), uuid4())

    assert result is sku
    session.commit.assert_not_awaited()


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


# --- PATCH parcial dentro de precio y stock ---------------------------------

def _sku_rebajado() -> Sku:
    return _sku(
        precio={"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
        stock={"cantidad": 5, "minimo": 3, "actualizado": None},
    )


async def _update(sku: Sku, body: dict[str, object]) -> Sku:
    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        return await SkuService.update(_session(), sku.id, SkuUpdate.model_validate(body), uuid4())


@pytest.mark.asyncio
async def test_update_solo_cantidad_conserva_el_minimo() -> None:
    result = await _update(_sku_rebajado(), {"stock": {"cantidad": 9}})

    assert (result.stock["cantidad"], result.stock["minimo"]) == (9, 3)
    assert result.stock["actualizado"] is not None


@pytest.mark.asyncio
async def test_update_solo_normal_conserva_la_rebaja() -> None:
    result = await _update(_sku_rebajado(), {"precio": {"normal": 35}})

    assert result.precio == {"normal": 35.0, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"}


@pytest.mark.asyncio
async def test_update_rebajado_null_quita_la_rebaja_y_su_fecha() -> None:
    result = await _update(_sku_rebajado(), {"precio": {"rebajado": None}})

    assert result.precio == {"normal": 29.95, "rebajado": None, "rebaja_hasta": None}


@pytest.mark.asyncio
async def test_update_valida_el_precio_resultante() -> None:
    session = _session()
    sku = _sku_rebajado()

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        with pytest.raises(AppException) as error:
            # 15 deja al normal por debajo del rebajado guardado (19.95).
            await SkuService.update(
                session, sku.id, SkuUpdate.model_validate({"precio": {"normal": 15}}), uuid4()
            )

    assert error.value.status_code == 422
    assert error.value.details == {
        "precio": "El precio rebajado debe ser menor que el precio normal."
    }
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_rechaza_rebaja_hasta_sin_rebaja() -> None:
    with pytest.raises(AppException) as error:
        await _update(_sku(), {"precio": {"rebaja_hasta": "2026-12-31"}})

    assert "precio" in error.value.details


def _con_rebaja_vencida() -> Sku:
    from datetime import timedelta

    from app.core.config import get_settings

    ayer = SkuService.local_today(get_settings()) - timedelta(days=1)
    return _sku(precio={"normal": 100.0, "rebajado": 80.0, "rebaja_hasta": ayer.isoformat()})


@pytest.mark.asyncio
async def test_update_nueva_rebaja_no_hereda_una_fecha_vencida() -> None:
    session = _session()
    sku = _con_rebaja_vencida()

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        with pytest.raises(AppException) as error:
            await SkuService.update(
                session, sku.id, SkuUpdate.model_validate({"precio": {"rebajado": 70}}), uuid4()
            )

    assert error.value.status_code == 422
    assert "ya pasó" in error.value.details["precio"]
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_nueva_rebaja_con_fecha_nueva_o_sin_fecha() -> None:
    con_fecha = await _update(
        _con_rebaja_vencida(),
        {"precio": {"rebajado": 70, "rebaja_hasta": "2099-01-31"}},
    )
    sin_fecha = await _update(
        _con_rebaja_vencida(),
        {"precio": {"rebajado": 70, "rebaja_hasta": None}},
    )

    assert con_fecha.precio["rebaja_hasta"] == "2099-01-31"
    assert sin_fecha.precio == {"normal": 100.0, "rebajado": 70.0, "rebaja_hasta": None}


@pytest.mark.asyncio
async def test_update_sin_tocar_la_rebaja_no_exige_su_fecha() -> None:
    # Cambiar solo el precio normal de un SKU con una rebaja vieja sigue funcionando.
    result = await _update(_con_rebaja_vencida(), {"precio": {"normal": 120}})

    assert result.precio["normal"] == 120.0


@pytest.mark.asyncio
async def test_update_sin_cambios_reales_no_renueva_la_fecha_del_stock() -> None:
    session = _session()
    sku = _sku_rebajado()

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        body = {"stock": {}, "precio": {"normal": 29.95}}
        result = await SkuService.update(session, sku.id, SkuUpdate.model_validate(body), uuid4())

    assert result.stock["actualizado"] is None
    session.commit.assert_not_awaited()


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
