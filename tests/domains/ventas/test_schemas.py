from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.ventas.schemas import (
    MAX_ITEMS_POR_VENTA,
    VentaCreate,
    VentaDetail,
    VentaEstadoUpdate,
    VentaItemsUpdate,
    VentaResponse,
    VentaResponseAudit,
)
from app.shared.enums import CanalVenta, EstadoVenta, MetodoPago


def _item(**overrides: object) -> dict[str, object]:
    return {"sku_id": str(uuid4()), "cantidad": 1, **overrides}


def test_venta_create_valores_por_defecto() -> None:
    venta = VentaCreate.model_validate({"items": [_item()]})

    assert venta.estado == EstadoVenta.PENDIENTE
    assert venta.canal == CanalVenta.WHATSAPP
    assert venta.metodo_pago == MetodoPago.EFECTIVO
    assert venta.descuento == Decimal("0")
    assert venta.referencia is None
    assert venta.cliente_telefono is None
    assert venta.nota is None


def test_venta_create_acepta_confirmada_para_mostrador() -> None:
    venta = VentaCreate.model_validate(
        {"estado": "CONFIRMADA", "canal": "TIENDA", "items": [_item()]}
    )

    assert venta.estado == EstadoVenta.CONFIRMADA


def test_venta_create_normaliza_textos() -> None:
    venta = VentaCreate.model_validate(
        {
            "referencia": "  María López ",
            "cliente_telefono": " +59171234567 ",
            "nota": " Recoge el sábado. ",
            "items": [_item()],
        }
    )

    assert venta.referencia == "María López"
    assert venta.cliente_telefono == "+59171234567"
    assert venta.nota == "Recoge el sábado."


@pytest.mark.parametrize(
    "overrides",
    [
        {"estado": "CANCELADA"},
        {"estado": None},
        {"canal": None},
        {"canal": "INSTAGRAM"},
        {"metodo_pago": None},
        {"metodo_pago": "TARJETA"},
        {"descuento": -1},
        {"descuento": None},
        {"referencia": "   "},
        {"referencia": "x" * 151},
        {"cliente_telefono": "abc"},
        {"nota": ""},
        {"items": []},
        {"items": None},
        {"subtotal": 10},
        {"total": 10},
        {"numero": 1},
    ],
)
def test_venta_create_rechaza_invalidos(overrides: dict[str, object]) -> None:
    data: dict[str, object] = {"items": [_item()], **overrides}

    with pytest.raises(ValidationError):
        VentaCreate.model_validate(data)


@pytest.mark.parametrize("schema", [VentaCreate, VentaItemsUpdate])
def test_items_rechaza_sku_repetido(schema: type) -> None:
    sku_id = str(uuid4())

    with pytest.raises(ValidationError, match="no puede repetirse"):
        schema.model_validate({"items": [_item(sku_id=sku_id), _item(sku_id=sku_id, cantidad=2)]})


@pytest.mark.parametrize("schema", [VentaCreate, VentaItemsUpdate])
def test_items_rechaza_mas_del_maximo(schema: type) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({"items": [_item() for _ in range(MAX_ITEMS_POR_VENTA + 1)]})


def test_venta_items_update_solo_marca_lo_enviado() -> None:
    data = VentaItemsUpdate.model_validate({"items": [_item()], "nota": None})

    assert data.model_dump(exclude_unset=True).keys() == {"items", "nota"}
    assert data.nota is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"items": None},
        {"items": []},
        {"canal": None},
        {"metodo_pago": None},
        {"descuento": None},
        {"estado": "CONFIRMADA"},
        {"recalcular_precios": None},
        {"recalcular_precios": "quizas"},
    ],
)
def test_venta_items_update_rechaza_invalidos(overrides: dict[str, object]) -> None:
    data: dict[str, object] = {"items": [_item()], **overrides}

    with pytest.raises(ValidationError):
        VentaItemsUpdate.model_validate(data)


def test_venta_items_update_por_defecto_no_recalcula_precios() -> None:
    data = VentaItemsUpdate.model_validate({"items": [_item()]})

    assert data.recalcular_precios is False
    assert VentaItemsUpdate.model_validate({"items": [_item()], "recalcular_precios": True}).recalcular_precios


def test_venta_items_update_exige_items() -> None:
    with pytest.raises(ValidationError):
        VentaItemsUpdate.model_validate({"nota": "Sin ítems"})


@pytest.mark.parametrize("estado", ["CONFIRMADA", "CANCELADA"])
def test_venta_estado_update_acepta_confirmar_y_cancelar(estado: str) -> None:
    assert VentaEstadoUpdate.model_validate({"estado": estado}).estado == EstadoVenta(estado)


@pytest.mark.parametrize("data", [{"estado": "PENDIENTE"}, {"estado": None}, {}, {"estado": "CONFIRMADA", "metodo_pago": "QR"}])
def test_venta_estado_update_rechaza_invalidos(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VentaEstadoUpdate.model_validate(data)


@pytest.mark.parametrize(
    "schema",
    [VentaCreate, VentaItemsUpdate, VentaEstadoUpdate, VentaResponse, VentaResponseAudit, VentaDetail],
)
def test_ejemplos_validan_su_schema(schema: type) -> None:
    example = schema.model_config["json_schema_extra"]["example"]

    assert None not in example.values()
    assert list(schema.model_validate(example).model_dump()) == list(example)


def test_ejemplo_de_detail_es_coherente() -> None:
    detail = VentaDetail.model_validate(VentaDetail.model_config["json_schema_extra"]["example"])

    for item in detail.items:
        assert item.subtotal == (item.precio_unitario - item.descuento_unitario) * item.cantidad
    assert detail.subtotal == sum(item.subtotal for item in detail.items)
    assert detail.total == detail.subtotal - detail.descuento
    assert detail.estado == EstadoVenta.CANCELADA
    assert detail.confirmada_at is not None and detail.cancelada_at is not None


# ---------------------------------------------------------------- estado


def test_estado_update_por_defecto_no_recalcula_precios() -> None:
    from app.domains.ventas.schemas import VentaEstadoUpdate

    assert VentaEstadoUpdate.model_validate({"estado": "CONFIRMADA"}).recalcular_precios is False


@pytest.mark.parametrize(
    "body",
    [
        {"estado": "CANCELADA", "recalcular_precios": True},
        {"estado": "CANCELADA", "recalcular_precios": False},
        {"estado": "CONFIRMADA", "recalcular_precios": None},
        {"estado": "CONFIRMADA", "recalcular_precios": "true"},
    ],
)
def test_estado_update_recalcular_solo_al_confirmar_y_booleano(body: dict[str, object]) -> None:
    from pydantic import ValidationError

    from app.domains.ventas.schemas import VentaEstadoUpdate

    with pytest.raises(ValidationError):
        VentaEstadoUpdate.model_validate(body)
