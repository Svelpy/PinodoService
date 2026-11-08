from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.skus.models import Sku
from app.domains.skus.schemas import (
    SkuCreate,
    SkuDetail,
    SkuListItem,
    SkuPrecio,
    SkuResponse,
)
from app.domains.tallas.models import Talla


def _create_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "producto_color_id": str(uuid4()),
        "talla_id": str(uuid4()),
        "precio": {"normal": "29.95"},
    }
    data.update(overrides)
    return data


def test_sku_create_valores_por_defecto() -> None:
    data = SkuCreate.model_validate(_create_data())

    assert data.precio.normal == Decimal("29.95")
    assert data.stock.cantidad == 0
    assert data.stock.minimo == 0
    assert data.codigo_barras is None
    assert data.is_visible is True


def test_sku_precio_se_serializa_como_numero_json() -> None:
    precio = SkuPrecio(normal="29.95", rebajado=19.95, rebaja_hasta="2026-12-31")

    assert precio.model_dump(mode="json") == {
        "normal": 29.95,
        "rebajado": 19.95,
        "rebaja_hasta": "2026-12-31",
    }


@pytest.mark.parametrize(
    "precio",
    [
        {"normal": 0},
        {"normal": "29.999"},
        {"normal": 29.95, "rebajado": 29.95},
        {"normal": 29.95, "rebajado": 35},
        {"normal": 29.95, "rebaja_hasta": "2026-12-31"},
        {"normal": True},
        {"normal": 29.95, "moneda": "BOB"},
    ],
)
def test_sku_precio_rechaza_invalidos(precio: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SkuPrecio.model_validate(precio)


@pytest.mark.parametrize(
    "stock",
    [{"cantidad": -1}, {"minimo": "3"}, {"cantidad": True}, {"actualizado": "2026-10-29"}],
)
def test_sku_stock_rechaza_invalidos(stock: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SkuCreate.model_validate(_create_data(stock=stock))


def test_sku_response_desde_modelo() -> None:
    sku = Sku(
        producto_color_id=uuid4(),
        talla_id=uuid4(),
        precio={"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
        stock={"cantidad": 12, "minimo": 3, "actualizado": "2026-10-29T15:00:00+00:00"},
    )

    response = SkuResponse.model_validate(sku)

    assert response.precio.rebajado == Decimal("19.95")
    assert response.precio.rebaja_hasta == date(2026, 12, 31)
    assert response.stock.cantidad == 12
    assert response.model_dump(mode="json")["precio"]["normal"] == 29.95


def test_sku_list_item_embebe_talla_y_deja_dueno_como_id() -> None:
    talla = Talla(etiqueta="M")
    sku = Sku(producto_color_id=uuid4(), talla_id=talla.id, precio={"normal": 29.95})
    orm = SimpleNamespace(**sku.model_dump(), talla=talla)

    data = SkuListItem.model_validate(orm).model_dump()

    assert data["talla"]["etiqueta"] == "M"
    assert data["producto_color_id"] == sku.producto_color_id
    assert "producto_color" not in data


def test_sku_detail_solo_anade_precio_vigente() -> None:
    assert SkuDetail.model_fields.keys() - SkuListItem.model_fields.keys() == {"precio_vigente"}


def _sku_orm(precio: dict[str, object]) -> Sku:
    talla = Talla(etiqueta="M")
    sku = Sku(producto_color_id=uuid4(), talla_id=talla.id, precio=precio)
    sku.talla = talla
    return sku


@pytest.mark.parametrize(
    ("precio", "esperado"),
    [
        ({"normal": 100.0}, 100.0),
        ({"normal": 100.0, "rebajado": 80.0}, 80.0),
        ({"normal": 100.0, "rebajado": 80.0, "rebaja_hasta": "2026-11-06"}, 80.0),
        ({"normal": 100.0, "rebajado": 80.0, "rebaja_hasta": "2026-11-05"}, 100.0),
    ],
    ids=["sin-rebaja", "rebaja-sin-fecha", "vence-hoy", "vencida-ayer"],
)
def test_sku_detail_calcula_precio_vigente_con_la_fecha_del_contexto(
    precio: dict[str, object],
    esperado: float,
) -> None:
    data = SkuDetail.model_validate(
        _sku_orm(precio), context={"today": date(2026, 11, 6)}
    ).model_dump(mode="json")

    assert data["precio_vigente"] == esperado
    assert data["precio"]["normal"] == 100.0


def test_sku_detail_sin_fecha_en_el_contexto_falla() -> None:
    with pytest.raises(ValidationError):
        SkuDetail.model_validate(_sku_orm({"normal": 100.0}))


def test_sku_detail_conserva_precio_vigente_ya_calculado() -> None:
    # FastAPI vuelve a validar la respuesta como dict, sin contexto.
    calculado = SkuDetail.model_validate(
        _sku_orm({"normal": 100.0, "rebajado": 80.0}), context={"today": date(2026, 11, 6)}
    )

    again = SkuDetail.model_validate(calculado.model_dump())

    assert again.precio_vigente == Decimal("80.0")


# --- PATCH /skus/{id}/stock ---------------------------------------------------

from app.domains.skus.schemas import SkuStockUpdate  # noqa: E402


def test_stock_update_ejemplo_valida() -> None:
    SkuStockUpdate.model_validate(SkuStockUpdate.model_config["json_schema_extra"]["example"])


@pytest.mark.parametrize(
    "body",
    [{"ajuste": 5}, {"ajuste": -2}, {"ajuste": -1, "minimo": 1}, {"minimo": 3}, {"minimo": 0}],
)
def test_stock_update_acepta_ajuste_minimo_o_ambos(body: dict[str, object]) -> None:
    SkuStockUpdate.model_validate(body)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"ajuste": 0},
        {"ajuste": True},
        {"ajuste": "5"},
        {"ajuste": 1.5},
        {"ajuste": None},
        {"minimo": -1},
        {"minimo": None},
        {"cantidad": 9},
        {"cantidad_anterior": 4, "cantidad": 9},
    ],
)
def test_stock_update_rechaza_valores_invalidos(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SkuStockUpdate.model_validate(body)
