from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.colores.models import Color
from app.domains.imagenes.models import Imagen
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.schemas import (
    ProductoColorCreate,
    ProductoColorDetail,
    ProductoColorListItem,
    ProductoColorResponse,
    ProductoColorUpdate,
)
from app.domains.skus.models import Sku
from app.domains.tallas.models import Talla


def test_producto_color_create_visible_por_defecto() -> None:
    assert ProductoColorCreate(producto_id=uuid4(), color_id=uuid4()).is_visible is True


def test_producto_color_update_no_permite_cambiar_dueno() -> None:
    with pytest.raises(ValidationError):
        ProductoColorUpdate.model_validate({"producto_id": str(uuid4())})


def test_producto_color_update_rechaza_visibilidad_null() -> None:
    with pytest.raises(ValidationError):
        ProductoColorUpdate.model_validate({"is_visible": None})


def test_producto_color_update_usa_el_body_del_create_mas_eliminados() -> None:
    from app.domains.producto_colores.schemas import ProductoColorDetailCreate

    assert list(ProductoColorUpdate.model_fields) == [
        *ProductoColorDetailCreate.model_fields,
        "sku_ids_eliminar",
    ]


def test_producto_color_response_desde_modelo() -> None:
    producto_color = ProductoColor(producto_id=uuid4(), color_id=uuid4())

    assert ProductoColorResponse.model_validate(producto_color).is_visible is True


def _producto_color_orm() -> SimpleNamespace:
    color = Color(nombre="Azul", slug="azul", codigo_hex="#1E3A8A")
    producto_color = ProductoColor(producto_id=uuid4(), color_id=color.id)
    talla = Talla(etiqueta="M")
    sku = Sku(producto_color_id=producto_color.id, talla_id=talla.id, precio={"normal": 29.95})
    imagen = Imagen(producto_color_id=producto_color.id, url="https://res.cloudinary.com/demo/x.jpg")
    return SimpleNamespace(
        **producto_color.model_dump(),
        color=color,
        imagenes=[imagen],
        skus=[SimpleNamespace(**sku.model_dump(), talla=talla)],
    )


def test_producto_color_list_item_embebe_color_sin_colecciones() -> None:
    data = ProductoColorListItem.model_validate(_producto_color_orm()).model_dump()

    assert data["color"]["nombre"] == "Azul"
    assert "imagenes" not in data
    assert "skus" not in data
    assert "producto" not in data


def test_producto_color_detail_embebe_hijos_hasta_las_hojas() -> None:
    data = ProductoColorDetail.model_validate(
        _producto_color_orm(), context={"today": date(2026, 11, 6)}
    ).model_dump(mode="json")

    assert data["imagenes"][0]["url"] == "https://res.cloudinary.com/demo/x.jpg"
    assert data["skus"][0]["talla"]["etiqueta"] == "M"
    assert data["skus"][0]["precio"]["normal"] == 29.95
    assert data["skus"][0]["precio_vigente"] == 29.95
    assert "producto_color" not in data["skus"][0]


def test_producto_color_create_hereda_el_arbol_y_exige_el_producto() -> None:
    from app.domains.producto_colores.schemas import ProductoColorCreate

    example = ProductoColorCreate.model_config["json_schema_extra"]["example"]
    ProductoColorCreate.model_validate(example)
    assert list(example) == list(ProductoColorCreate.model_fields)

    minimo = ProductoColorCreate.model_validate({"producto_id": str(uuid4()), "color_id": str(uuid4())})
    assert (minimo.imagenes, minimo.skus) == ([], [])
    with pytest.raises(ValidationError):
        ProductoColorCreate.model_validate({"color_id": str(uuid4())})


def test_producto_color_rechaza_codigo_de_barras_repetido() -> None:
    from app.domains.producto_colores.schemas import ProductoColorDetailCreate

    sku = {"precio": {"normal": 10}, "codigo_barras": "841"}
    with pytest.raises(ValidationError, match="código de barras no puede repetirse"):
        ProductoColorDetailCreate.model_validate(
            {"color_id": str(uuid4()), "skus": [{**sku, "talla_id": str(uuid4())}, {**sku, "talla_id": str(uuid4())}]}
        )


# --- PATCH con imágenes y SKUs ----------------------------------------------

from app.domains.skus.schemas import SkuDetailUpdate  # noqa: E402

PRECIO = {"normal": 29.95}


def test_ejemplos_del_patch_validan_su_schema() -> None:
    for schema in (ProductoColorUpdate, SkuDetailUpdate):
        example = schema.model_config["json_schema_extra"]["example"]
        schema.model_validate(example)
        assert list(example) == [name for name in schema.model_fields if name in example]


def test_patch_acepta_un_body_vacio() -> None:
    assert ProductoColorUpdate.model_validate({}).model_fields_set == set()


@pytest.mark.parametrize("campo", ["color_id", "is_visible", "imagenes", "skus", "sku_ids_eliminar"])
def test_patch_rechaza_null(campo: str) -> None:
    with pytest.raises(ValidationError):
        ProductoColorUpdate.model_validate({campo: None})


def test_fila_existente_no_admite_stock_y_la_nueva_si() -> None:
    with pytest.raises(ValidationError, match="POST /movimientos-inventario/"):
        SkuDetailUpdate.model_validate(
            {"id": str(uuid4()), "talla_id": str(uuid4()), "precio": PRECIO, "stock": {"cantidad": 1}}
        )

    nueva = SkuDetailUpdate.model_validate({"talla_id": str(uuid4()), "precio": PRECIO})
    assert nueva.id is None and nueva.stock is None
    existente = SkuDetailUpdate.model_validate({"id": str(uuid4()), "talla_id": str(uuid4()), "precio": PRECIO})
    # Solo lo enviado cambia en un SKU existente.
    assert "codigo_barras" not in existente.model_fields_set
    assert "costo" not in existente.model_fields_set


def test_patch_rechaza_editar_y_eliminar_el_mismo_sku() -> None:
    sku_id = str(uuid4())
    with pytest.raises(ValidationError, match="editarse y eliminarse"):
        ProductoColorUpdate.model_validate(
            {
                "skus": [{"id": sku_id, "talla_id": str(uuid4()), "precio": PRECIO}],
                "sku_ids_eliminar": [sku_id],
            }
        )


@pytest.mark.parametrize(
    ("filas", "mensaje"),
    [
        ([{"id": "A", "talla": "1"}, {"id": "A", "talla": "2"}], "SKU no puede repetirse"),
        ([{"talla": "1"}, {"talla": "1"}], "talla no puede repetirse"),
    ],
)
def test_patch_rechaza_filas_repetidas(filas: list[dict[str, str]], mensaje: str) -> None:
    ids = {"A": str(uuid4())}
    tallas = {"1": str(uuid4()), "2": str(uuid4())}
    skus = [
        {**({"id": ids[f["id"]]} if "id" in f else {}), "talla_id": tallas[f["talla"]], "precio": PRECIO}
        for f in filas
    ]
    with pytest.raises(ValidationError, match=mensaje):
        ProductoColorUpdate.model_validate({"skus": skus})


def test_patch_quita_ids_eliminados_repetidos() -> None:
    sku_id = uuid4()
    data = ProductoColorUpdate.model_validate({"sku_ids_eliminar": [str(sku_id), str(sku_id)]})
    assert data.sku_ids_eliminar == [sku_id]
