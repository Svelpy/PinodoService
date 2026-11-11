from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.venta_pagos.schemas import (
    VentaPagoCreate,
    VentaPagoDetail,
    VentaPagoDetailCreate,
    VentaPagoListItem,
    VentaPagoResponse,
    VentaPagoResponseAudit,
    VentaPagoUpdate,
)
from app.shared.enums import MetodoPago


def _pago(**overrides: object) -> dict[str, object]:
    return {"venta_id": str(uuid4()), "metodo": "QR", "monto": "150.50", **overrides}


def test_create_normaliza_y_convierte_el_monto() -> None:
    pago = VentaPagoCreate.model_validate(_pago(referencia="  0048213 "))

    assert pago.metodo == MetodoPago.QR
    assert pago.monto == Decimal("150.50")
    assert pago.referencia == "0048213"


def test_create_referencia_es_opcional() -> None:
    assert VentaPagoCreate.model_validate(_pago()).referencia is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"venta_id": None},
        {"metodo": None},
        {"metodo": "TARJETA"},
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
def test_create_rechaza_invalidos(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VentaPagoCreate.model_validate(_pago(**overrides))


def test_detail_create_no_acepta_venta_id() -> None:
    with pytest.raises(ValidationError):
        VentaPagoDetailCreate.model_validate(_pago())


def test_update_solo_marca_lo_enviado_y_acepta_null() -> None:
    data = VentaPagoUpdate.model_validate({"referencia": None})

    assert data.model_dump(exclude_unset=True) == {"referencia": None}
    assert VentaPagoUpdate.model_validate({}).model_dump(exclude_unset=True) == {}


@pytest.mark.parametrize("body", [{"monto": 10}, {"metodo": "EFECTIVO"}, {"referencia": ""}])
def test_update_no_corrige_monto_ni_metodo(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VentaPagoUpdate.model_validate(body)


@pytest.mark.parametrize(
    "schema",
    [
        VentaPagoDetailCreate,
        VentaPagoCreate,
        VentaPagoUpdate,
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
