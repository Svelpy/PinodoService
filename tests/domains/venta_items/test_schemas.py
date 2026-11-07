from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.venta_items.schemas import VentaItemCreate, VentaItemResponse


def test_venta_item_create_valores_por_defecto() -> None:
    item = VentaItemCreate.model_validate({"sku_id": str(uuid4()), "cantidad": 1})

    assert item.descuento_unitario == Decimal("0")


@pytest.mark.parametrize(
    "overrides",
    [
        {"cantidad": 0},
        {"cantidad": -1},
        {"cantidad": 1.5},
        {"cantidad": "2"},
        {"cantidad": True},
        {"cantidad": None},
        {"descuento_unitario": -1},
        {"descuento_unitario": "1.999"},
        {"descuento_unitario": None},
        {"sku_id": None},
        {"precio_unitario": 10},
        {"subtotal": 10},
        {"producto_nombre": "Camisa"},
    ],
)
def test_venta_item_create_rechaza_invalidos(overrides: dict[str, object]) -> None:
    data: dict[str, object] = {"sku_id": str(uuid4()), "cantidad": 1, **overrides}

    with pytest.raises(ValidationError):
        VentaItemCreate.model_validate(data)


def test_venta_item_response_serializa_importes_como_numero() -> None:
    item = VentaItemResponse.model_validate(
        SimpleNamespace(
            id=uuid4(),
            sku_id=uuid4(),
            cantidad=2,
            precio_normal=Decimal("29.95"),
            precio_unitario=Decimal("19.95"),
            descuento_unitario=Decimal("0.00"),
            subtotal=Decimal("39.90"),
            producto_nombre="Camisa Oxford",
            color_nombre="Azul marino",
            talla_etiqueta="M",
            codigo_barras=None,
        )
    )

    data = item.model_dump(mode="json")
    assert data["precio_normal"] == 29.95
    assert data["subtotal"] == 39.9
    assert data["codigo_barras"] is None


@pytest.mark.parametrize("schema", [VentaItemCreate, VentaItemResponse])
def test_ejemplos_validan_su_schema(schema: type) -> None:
    example = schema.model_config["json_schema_extra"]["example"]

    assert None not in example.values()
    assert list(schema.model_validate(example).model_dump()) == list(example)
