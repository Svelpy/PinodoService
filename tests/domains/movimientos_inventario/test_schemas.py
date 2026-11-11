from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.movimientos_inventario.schemas import (
    MovimientoInventarioCreate,
    MovimientoInventarioDetail,
    MovimientoInventarioListItem,
    MovimientoInventarioResponse,
    MovimientoInventarioResponseAudit,
    SkuCosto,
)
from app.shared.enums import TipoMovimiento


def _ingreso(**overrides: object) -> dict[str, object]:
    return {"sku_id": str(uuid4()), "tipo": "INGRESO", "cantidad": 24, "costo_unitario": "12.50", **overrides}


def _ajuste(**overrides: object) -> dict[str, object]:
    return {"sku_id": str(uuid4()), "tipo": "AJUSTE", "cantidad": -2, "motivo": " Merma ", **overrides}


def test_ingreso_valido() -> None:
    data = MovimientoInventarioCreate.model_validate(_ingreso())

    assert data.tipo == TipoMovimiento.INGRESO
    assert data.costo_unitario == Decimal("12.50")
    assert data.motivo is None


def test_ingreso_acepta_costo_cero() -> None:
    assert MovimientoInventarioCreate.model_validate(_ingreso(costo_unitario=0)).costo_unitario == 0


@pytest.mark.parametrize("cantidad", [3, -3])
def test_ajuste_valido_en_ambos_sentidos(cantidad: int) -> None:
    data = MovimientoInventarioCreate.model_validate(_ajuste(cantidad=cantidad))

    assert data.cantidad == cantidad
    assert data.motivo == "Merma"
    assert data.costo_unitario is None


@pytest.mark.parametrize(
    "body",
    [
        _ingreso(tipo="VENTA"),
        _ingreso(tipo="ANULACION"),
        _ingreso(tipo=None),
        _ingreso(sku_id=None),
        _ingreso(cantidad=0),
        _ingreso(cantidad=-1),
        _ingreso(cantidad=1.5),
        _ingreso(cantidad=True),
        _ingreso(cantidad=None),
        _ingreso(costo_unitario=None),
        _ingreso(costo_unitario=-1),
        _ingreso(costo_unitario="1.001"),
        _ajuste(motivo=None),
        _ajuste(motivo="   "),
        _ajuste(motivo="x" * 201),
        _ajuste(costo_unitario=10),
        _ingreso(saldo=10),
        _ingreso(venta_id=str(uuid4())),
    ],
)
def test_create_rechaza_invalidos(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MovimientoInventarioCreate.model_validate(body)


@pytest.mark.parametrize(
    "schema",
    [
        MovimientoInventarioCreate,
        MovimientoInventarioResponse,
        MovimientoInventarioResponseAudit,
        MovimientoInventarioListItem,
        MovimientoInventarioDetail,
        SkuCosto,
    ],
)
def test_ejemplos_validan_su_schema(schema: type) -> None:
    example = schema.model_config["json_schema_extra"]["example"]

    assert None not in example.values()
    assert list(schema.model_validate(example).model_dump()) == list(example)


def test_response_no_tiene_update_ni_listitem_campos_de_mas() -> None:
    # Un movimiento no se edita: no hay schema Update.
    import app.domains.movimientos_inventario.schemas as schemas

    assert not hasattr(schemas, "MovimientoInventarioUpdate")
    assert set(MovimientoInventarioListItem.model_fields) - set(MovimientoInventarioResponse.model_fields) == {
        "sku",
        "venta",
    }
