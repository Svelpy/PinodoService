"""Schemas de entrada del create en un solo paso (DetailCreate)."""

from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.domains.imagenes.schemas import ImagenDetailCreate
from app.domains.producto_colores.schemas import ProductoColorDetailCreate
from app.domains.productos.schemas import ProductoCreate, ProductoDetailCreate
from app.domains.skus.schemas import SkuCreate, SkuDetailCreate
from app.shared.enums import TipoImagen


URL = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/imagenes/foto.jpg"


def _sku(**overrides: object) -> dict[str, object]:
    return {"talla_id": str(uuid4()), "precio": {"normal": 29.95}, **overrides}


def _color(**overrides: object) -> dict[str, object]:
    return {"color_id": str(uuid4()), **overrides}


@pytest.mark.parametrize(
    "schema",
    [ImagenDetailCreate, SkuDetailCreate, SkuCreate, ProductoColorDetailCreate, ProductoDetailCreate],
)
def test_el_ejemplo_pasa_la_validacion_y_sigue_el_orden_de_declaracion(
    schema: type[BaseModel],
) -> None:
    example = schema.model_config["json_schema_extra"]["example"]

    schema.model_validate(example)
    assert list(example) == list(schema.model_fields)


# --- ImagenDetailCreate -----------------------------------------------------


def test_imagen_tipo_por_defecto_es_modelo() -> None:
    assert ImagenDetailCreate(url=URL).tipo is TipoImagen.MODELO


@pytest.mark.parametrize(
    "data",
    [
        {"url": None},
        {"url": "no-es-una-url"},
        {"url": URL, "tipo": None},
        {"url": URL, "tipo": "PORTADA"},
        {"url": URL, "producto_color_id": str(uuid4())},
    ],
)
def test_imagen_rechaza_datos_invalidos(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ImagenDetailCreate.model_validate(data)


# --- SkuDetailCreate / SkuCreate --------------------------------------------


def test_sku_minimo_aplica_valores_por_defecto() -> None:
    sku = SkuDetailCreate.model_validate(_sku())

    assert sku.is_visible is True
    assert sku.codigo_barras is None
    assert (sku.stock.cantidad, sku.stock.minimo) == (0, 0)


def test_sku_detail_create_rechaza_la_foreign_key_de_dueno() -> None:
    with pytest.raises(ValidationError):
        SkuDetailCreate.model_validate(_sku(producto_color_id=str(uuid4())))


def test_sku_create_hereda_las_validaciones_y_exige_la_foreign_key() -> None:
    with pytest.raises(ValidationError):
        SkuCreate.model_validate(_sku())
    with pytest.raises(ValidationError):
        SkuCreate.model_validate(
            _sku(producto_color_id=str(uuid4()), precio={"normal": 10, "rebajado": 20})
        )


# --- ProductoColorDetailCreate ----------------------------------------------


def test_color_sin_hijos_tiene_listas_vacias() -> None:
    color = ProductoColorDetailCreate.model_validate(_color())

    assert color.imagenes == []
    assert color.skus == []


def test_color_rechaza_tallas_repetidas() -> None:
    talla_id = str(uuid4())

    with pytest.raises(ValidationError, match="talla no puede repetirse"):
        ProductoColorDetailCreate.model_validate(
            _color(skus=[_sku(talla_id=talla_id), _sku(talla_id=talla_id)])
        )


@pytest.mark.parametrize(
    "overrides",
    [{"imagenes": None}, {"skus": None}, {"producto_id": str(uuid4())}, {"is_visible": None}],
)
def test_color_rechaza_datos_invalidos(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProductoColorDetailCreate.model_validate(_color(**overrides))


# --- ProductoDetailCreate ---------------------------------------------------


def test_producto_sin_colecciones_equivale_a_producto_create() -> None:
    data = {"seccion_id": str(uuid4()), "nombre": "Camisa Oxford"}

    producto = ProductoDetailCreate.model_validate(data)

    assert producto.categoria_ids == []
    assert producto.colores == []
    assert producto.model_dump(exclude={"categoria_ids", "colores"}) == (
        ProductoCreate.model_validate(data).model_dump()
    )


def test_producto_hereda_las_validaciones_de_producto_create() -> None:
    with pytest.raises(ValidationError):
        ProductoDetailCreate.model_validate({"seccion_id": str(uuid4()), "nombre": "   "})


def test_producto_deduplica_categorias_conservando_el_orden() -> None:
    a, b = uuid4(), uuid4()

    producto = ProductoDetailCreate.model_validate(
        {"seccion_id": str(uuid4()), "nombre": "Camisa", "categoria_ids": [str(a), str(b), str(a)]}
    )

    assert producto.categoria_ids == [a, b]


def test_producto_rechaza_colores_repetidos() -> None:
    color_id = str(uuid4())

    with pytest.raises(ValidationError, match="color no puede repetirse"):
        ProductoDetailCreate.model_validate(
            {
                "seccion_id": str(uuid4()),
                "nombre": "Camisa",
                "colores": [_color(color_id=color_id), _color(color_id=color_id)],
            }
        )


def test_producto_arbol_completo() -> None:
    producto = ProductoDetailCreate.model_validate(
        {
            "seccion_id": str(uuid4()),
            "nombre": "Camisa Oxford",
            "colores": [
                _color(imagenes=[{"url": URL, "tipo": "DETALLE"}], skus=[_sku(), _sku()]),
                _color(skus=[_sku()]),
            ],
        }
    )

    assert len(producto.colores) == 2
    assert producto.colores[0].imagenes[0].tipo is TipoImagen.DETALLE
    assert [len(color.skus) for color in producto.colores] == [2, 1]


def test_el_error_indica_la_ruta_del_campo_dentro_del_arbol() -> None:
    with pytest.raises(ValidationError) as error:
        ProductoDetailCreate.model_validate(
            {
                "seccion_id": str(uuid4()),
                "nombre": "Camisa",
                "colores": [_color(), _color(skus=[_sku(precio={"normal": 0})])],
            }
        )

    assert error.value.errors()[0]["loc"] == ("colores", 1, "skus", 0, "precio", "normal")


def test_producto_rechaza_codigo_de_barras_repetido_en_el_arbol() -> None:
    with pytest.raises(ValidationError, match="código de barras no puede repetirse"):
        ProductoDetailCreate.model_validate(
            {
                "seccion_id": str(uuid4()),
                "nombre": "Camisa",
                "colores": [
                    _color(skus=[_sku(codigo_barras="841")]),
                    _color(skus=[_sku(codigo_barras="841")]),
                ],
            }
        )


def test_rechaza_la_misma_imagen_dos_veces_en_un_color_o_en_el_producto() -> None:
    imagen = {"url": URL}
    with pytest.raises(ValidationError, match="imagen no puede repetirse dentro del mismo color"):
        ProductoColorDetailCreate.model_validate(_color(imagenes=[imagen, imagen]))
    with pytest.raises(ValidationError, match="imagen no puede repetirse dentro del mismo producto"):
        ProductoDetailCreate.model_validate(
            {
                "seccion_id": str(uuid4()),
                "nombre": "Camisa",
                "colores": [_color(imagenes=[imagen]), _color(imagenes=[imagen])],
            }
        )
