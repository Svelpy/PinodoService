from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.venta_pagos.schemas import (
    VentaPagoDetail,
    VentaPagoDetailCreate,
    VentaPagoListItem,
    VentaPagoResponse,
    VentaPagoResponseAudit,
)
from app.shared.enums import MetodoPago


def _pago(**overrides: object) -> dict[str, object]:
    return {"metodo": "QR", "monto": "150.50", **overrides}


def test_detail_create_normaliza_y_convierte_el_monto() -> None:
    pago = VentaPagoDetailCreate.model_validate(_pago(referencia="  0048213 "))

    assert pago.metodo == MetodoPago.QR
    assert pago.monto == Decimal("150.50")
    assert pago.referencia == "0048213"


def test_detail_create_referencia_es_opcional() -> None:
    assert VentaPagoDetailCreate.model_validate(_pago()).referencia is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"metodo": None},
        {"metodo": "BITCOIN"},
        {"monto": None},
        {"monto": 0},
        {"monto": -1},
        {"monto": "abc"},
        {"monto": True},
        {"monto": "1.001"},
        {"referencia": "   "},
        {"referencia": "x" * 101},
        {"comprobante_url": "https://example.com/a.jpg"},
        {"tipo": "REEMBOLSO"},
    ],
)
def test_detail_create_rechaza_invalidos(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VentaPagoDetailCreate.model_validate(_pago(**overrides))


def test_detail_create_no_acepta_venta_id() -> None:
    # La venta la asigna el service: el pago siempre se envía dentro de su venta.
    with pytest.raises(ValidationError):
        VentaPagoDetailCreate.model_validate(_pago(venta_id=str(uuid4())))


@pytest.mark.parametrize(
    "schema",
    [
        VentaPagoDetailCreate,
        VentaPagoResponse,
        VentaPagoResponseAudit,
        VentaPagoListItem,
        VentaPagoDetail,
    ],
)
def test_ejemplos_validan_su_schema(schema: type) -> None:
    example = schema.model_config["json_schema_extra"]["example"]

    assert None not in example.values()
    assert list(schema.model_validate(example).model_dump()) == list(example)
