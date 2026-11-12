from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.ventas.schemas import (
    MAX_ITEMS_POR_VENTA,
    VentaCreate,
    VentaConfirmar,
    VentaDetail,
    VentaItemsUpdate,
    VentaResponse,
    VentaResponseAudit,
)
from app.domains.venta_pagos.schemas import MAX_PAGOS_POR_VENTA
from app.shared.enums import CanalVenta, EstadoVenta, MetodoPago


def _item(**overrides: object) -> dict[str, object]:
    return {"sku_id": str(uuid4()), "cantidad": 1, **overrides}


def _pago(**overrides: object) -> dict[str, object]:
    return {"metodo": "EFECTIVO", "monto": "10.00", **overrides}


def test_venta_create_valores_por_defecto() -> None:
    venta = VentaCreate.model_validate({"items": [_item()]})

    assert venta.canal == CanalVenta.PAGINA_WEB
    assert venta.pagos == []
    assert venta.descuento == Decimal("0")
    assert venta.referencia is None
    assert venta.cliente_telefono is None
    assert venta.nota is None


def test_venta_create_no_acepta_estado() -> None:
    # El estado lo deciden los pagos: sin pagos PENDIENTE, con pagos CONFIRMADA.
    with pytest.raises(ValidationError):
        VentaCreate.model_validate({"estado": "CONFIRMADA", "canal": "TIENDA", "items": [_item()]})


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
        {"estado": "PENDIENTE"},
        {"canal": None},
        {"canal": "BITCOIN"},
        {"metodo_pago": "QR"},
        {"pagos": None},
        {"pagos": [_pago(metodo="BITCOIN")]},
        {"pagos": [_pago(monto=0)]},
        {"pagos": [_pago(monto=-5)]},
        {"pagos": [_pago(monto=None)]},
        {"pagos": [_pago(referencia="   ")]},
        {"pagos": [_pago(venta_id=str(uuid4()))]},
        {"pagos": [_pago() for _ in range(MAX_PAGOS_POR_VENTA + 1)]},
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


def test_venta_create_acepta_pagos_mixtos() -> None:
    venta = VentaCreate.model_validate(
        {
            "items": [_item()],
            "pagos": [_pago(monto="20.50"), _pago(metodo="QR", monto=9.5, referencia=" 0048213 ")],
        }
    )

    assert [(pago.metodo, pago.monto) for pago in venta.pagos] == [
        (MetodoPago.EFECTIVO, Decimal("20.50")),
        (MetodoPago.QR, Decimal("9.5")),
    ]
    assert venta.pagos[1].referencia == "0048213"


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
        {"metodo_pago": "QR"},
        {"pagos": [_pago()]},
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


def test_venta_confirmar_recibe_pagos_mixtos() -> None:
    data = VentaConfirmar.model_validate({"pagos": [_pago(), _pago(metodo="QR", referencia="0048213")]})

    assert [pago.metodo for pago in data.pagos] == [MetodoPago.EFECTIVO, MetodoPago.QR]


def test_venta_confirmar_valores_por_defecto() -> None:
    # Sin pagos solo se confirma una venta de total 0: lo comprueba el service.
    data = VentaConfirmar.model_validate({})

    assert data.pagos == []
    assert data.recalcular_precios is False


@pytest.mark.parametrize(
    "data",
    [
        {"estado": "CONFIRMADA"},
        {"metodo_pago": "QR"},
        {"pagos": None},
        {"pagos": [_pago(monto=0)]},
        {"pagos": [_pago(metodo="BITCOIN")]},
        {"pagos": [_pago() for _ in range(MAX_PAGOS_POR_VENTA + 1)]},
        {"recalcular_precios": None},
        {"recalcular_precios": "true"},
    ],
)
def test_venta_confirmar_rechaza_invalidos(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VentaConfirmar.model_validate(data)


@pytest.mark.parametrize(
    "schema",
    [VentaCreate, VentaItemsUpdate, VentaConfirmar, VentaResponse, VentaResponseAudit, VentaDetail],
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
    # Cancelada después de confirmarse: estaba pagada completa y se devolvió todo.
    assert detail.total_pagado == sum(pago.monto for pago in detail.pagos) == detail.total
    assert all(pago.venta_id == detail.id for pago in detail.pagos)
    assert detail.estado == EstadoVenta.CANCELADA
    assert detail.confirmada_at is not None and detail.cancelada_at is not None

