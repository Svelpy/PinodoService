import pytest

from app.domains.movimientos_inventario.schemas import (
    MovimientoInventarioResponse,
    MovimientoOrigen,
    SkuCosto,
    SkuResumen,
)


@pytest.mark.parametrize(
    "schema",
    [SkuResumen, MovimientoOrigen, MovimientoInventarioResponse, SkuCosto],
)
def test_ejemplos_validan_su_schema(schema: type) -> None:
    example = schema.model_config["json_schema_extra"]["example"]

    assert None not in example.values()
    assert list(schema.model_validate(example).model_dump()) == list(example)


def test_el_sku_del_kardex_no_trae_precio_ni_stock() -> None:
    # El stock de hoy no es el saldo del movimiento.
    assert set(SkuResumen.model_fields) == {
        "id",
        "codigo_barras",
        "producto_id",
        "producto_nombre",
        "color_nombre",
        "talla_etiqueta",
    }


def test_un_movimiento_no_se_crea_ni_se_edita_por_schema() -> None:
    import app.domains.movimientos_inventario.schemas as schemas

    for nombre in ("MovimientoInventarioCreate", "MovimientoInventarioUpdate", "MovimientoInventarioResponseAudit"):
        assert not hasattr(schemas, nombre)


def test_origen_solo_ajuste_o_venta() -> None:
    with pytest.raises(ValueError):
        MovimientoOrigen.model_validate({**MovimientoOrigen.model_config["json_schema_extra"]["example"], "tipo": "SKU"})
