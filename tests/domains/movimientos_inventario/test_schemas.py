from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.movimientos_inventario.schemas import (
    MAX_ITEMS_POR_AJUSTE,
    AjusteInventarioCreate,
    AjusteInventarioItem,
    AjusteInventarioResultado,
    MovimientoInventarioDetail,
    MovimientoInventarioListItem,
    MovimientoInventarioResponse,
    MovimientoInventarioResponseAudit,
    SkuCosto,
)
from app.shared.enums import MotivoAjuste


def _ajuste(motivo: str, *items: dict[str, object], **overrides: object) -> dict[str, object]:
    return {"motivo": motivo, "items": list(items), **overrides}


def _item(**campos: object) -> dict[str, object]:
    return {"sku_id": str(uuid4()), **campos}


def test_recepcion_valida() -> None:
    data = AjusteInventarioCreate.model_validate(
        _ajuste("RECEPCION", _item(cantidad=24, costo_unitario="12.50"), nota=" Lote ")
    )

    assert data.motivo == MotivoAjuste.RECEPCION
    assert data.nota == "Lote"
    assert data.items[0].costo_unitario == Decimal("12.50")


def test_recepcion_acepta_costo_cero() -> None:
    data = AjusteInventarioCreate.model_validate(_ajuste("RECEPCION", _item(cantidad=1, costo_unitario=0)))

    assert data.items[0].costo_unitario == 0


@pytest.mark.parametrize("contada", [0, 7])
def test_conteo_valido(contada: int) -> None:
    data = AjusteInventarioCreate.model_validate(_ajuste("CONTEO", _item(cantidad_contada=contada)))

    assert data.items[0].cantidad_contada == contada
    assert data.nota is None


@pytest.mark.parametrize("motivo", ["MERMA", "ROBO_PERDIDA"])
def test_salidas_se_envian_positivas(motivo: str) -> None:
    data = AjusteInventarioCreate.model_validate(_ajuste(motivo, _item(cantidad=2)))

    assert data.items[0].cantidad == 2


@pytest.mark.parametrize("cantidad", [3, -3])
def test_correccion_en_ambos_sentidos_con_nota(cantidad: int) -> None:
    data = AjusteInventarioCreate.model_validate(
        _ajuste("CORRECCION", _item(cantidad=cantidad), nota="Error de carga")
    )

    assert data.items[0].cantidad == cantidad


@pytest.mark.parametrize(
    "body",
    [
        _ajuste("INGRESO", _item(cantidad=1)),
        _ajuste(None, _item(cantidad=1)),
        {"motivo": "MERMA", "items": []},
        {"motivo": "MERMA", "items": None},
        {"motivo": "MERMA"},
        _ajuste("MERMA", _item(cantidad=1), nota="   "),
        _ajuste("MERMA", _item(cantidad=1), nota="x" * 201),
        _ajuste("MERMA", _item(cantidad=1), extra=1),
        _ajuste("MERMA", _item(cantidad=1, saldo=4)),
        _ajuste("MERMA", {"cantidad": 1}),
        _ajuste("MERMA", _item(cantidad=1, sku_id=None)),
        # RECEPCION
        _ajuste("RECEPCION", _item(cantidad=24)),
        _ajuste("RECEPCION", _item(cantidad=-2, costo_unitario=10)),
        _ajuste("RECEPCION", _item(costo_unitario=10)),
        _ajuste("RECEPCION", _item(cantidad=1, costo_unitario=-1)),
        _ajuste("RECEPCION", _item(cantidad=1, costo_unitario="1.001")),
        _ajuste("RECEPCION", _item(cantidad=1.5, costo_unitario=1)),
        _ajuste("RECEPCION", _item(cantidad=True, costo_unitario=1)),
        # CONTEO
        _ajuste("CONTEO", _item()),
        _ajuste("CONTEO", _item(cantidad_contada=-1)),
        _ajuste("CONTEO", _item(cantidad=2)),
        _ajuste("CONTEO", _item(cantidad_contada=2, cantidad=2)),
        _ajuste("CONTEO", _item(cantidad_contada=2, costo_unitario=10)),
        # MERMA / ROBO_PERDIDA
        _ajuste("MERMA", _item(cantidad=-2)),
        _ajuste("MERMA", _item(cantidad=0)),
        _ajuste("MERMA", _item(cantidad=2, costo_unitario=10)),
        _ajuste("ROBO_PERDIDA", _item(cantidad_contada=2)),
        # CORRECCION
        _ajuste("CORRECCION", _item(cantidad=1)),
        _ajuste("CORRECCION", _item(cantidad=0), nota="x"),
    ],
)
def test_ajuste_rechaza_invalidos(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AjusteInventarioCreate.model_validate(body)


def test_ajuste_rechaza_sku_repetido() -> None:
    sku_id = str(uuid4())

    with pytest.raises(ValidationError, match="repetido"):
        AjusteInventarioCreate.model_validate(
            _ajuste("MERMA", {"sku_id": sku_id, "cantidad": 1}, {"sku_id": sku_id, "cantidad": 2})
        )


def test_ajuste_limita_la_cantidad_de_items() -> None:
    items = [_item(cantidad=1) for _ in range(MAX_ITEMS_POR_AJUSTE + 1)]

    with pytest.raises(ValidationError):
        AjusteInventarioCreate.model_validate(_ajuste("MERMA", *items))


@pytest.mark.parametrize(
    "schema",
    [
        AjusteInventarioItem,
        AjusteInventarioCreate,
        MovimientoInventarioResponse,
        MovimientoInventarioResponseAudit,
        MovimientoInventarioListItem,
        MovimientoInventarioDetail,
        SkuCosto,
        AjusteInventarioResultado,
    ],
)
def test_ejemplos_validan_su_schema(schema: type) -> None:
    example = schema.model_config["json_schema_extra"]["example"]

    assert None not in example.values()
    assert list(schema.model_validate(example).model_dump()) == list(example)


def test_no_hay_create_ni_update_de_un_movimiento_suelto() -> None:
    import app.domains.movimientos_inventario.schemas as schemas

    assert not hasattr(schemas, "MovimientoInventarioCreate")
    assert not hasattr(schemas, "MovimientoInventarioUpdate")
    assert set(MovimientoInventarioListItem.model_fields) - set(MovimientoInventarioResponse.model_fields) == {
        "sku",
        "venta",
    }
