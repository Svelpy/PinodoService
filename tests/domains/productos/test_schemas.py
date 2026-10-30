from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.categorias.models import Categoria
from app.domains.colores.models import Color
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.domains.productos.schemas import (
    ProductoCreate,
    ProductoDetail,
    ProductoListItem,
    ProductoResponse,
    ProductoUpdate,
)
from app.domains.secciones.models import Seccion
from app.domains.skus.models import Sku
from app.domains.tallas.models import Talla


def test_producto_create_normaliza_textos() -> None:
    data = ProductoCreate(
        seccion_id=uuid4(),
        nombre=" Camisa Oxford ",
        composicion=" 100 % algodón ",
    )

    assert data.nombre == "Camisa Oxford"
    assert data.composicion == "100 % algodón"
    assert data.descripcion is None


@pytest.mark.parametrize("descripcion", ["", "   "])
def test_producto_rechaza_texto_opcional_vacio(descripcion: str) -> None:
    with pytest.raises(ValidationError):
        ProductoCreate(seccion_id=uuid4(), nombre="Camisa", descripcion=descripcion)


@pytest.mark.parametrize("field", ["seccion_id", "nombre", "is_visible"])
def test_producto_update_rechaza_null_en_campos_no_nullable(field: str) -> None:
    with pytest.raises(ValidationError):
        ProductoUpdate.model_validate({field: None})


def test_producto_update_permite_limpiar_textos() -> None:
    data = ProductoUpdate(descripcion=None, cuidados=None)

    assert data.model_dump(exclude_unset=True) == {"descripcion": None, "cuidados": None}


def test_producto_response_desde_modelo() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa Oxford")

    assert ProductoResponse.model_validate(producto).nombre == "Camisa Oxford"


def _producto_orm() -> SimpleNamespace:
    seccion = Seccion(nombre="Hombre", slug="hombre")
    producto = Producto(seccion_id=seccion.id, nombre="Camisa Oxford")
    categoria = Categoria(seccion_id=seccion.id, nombre="Camisas", slug="camisas")
    color = Color(nombre="Azul", slug="azul", codigo_hex="#1E3A8A")
    producto_color = ProductoColor(producto_id=producto.id, color_id=color.id)
    talla = Talla(etiqueta="M")
    sku = Sku(producto_color_id=producto_color.id, talla_id=talla.id, precio={"normal": 29.95})
    return SimpleNamespace(
        **producto.model_dump(),
        seccion=seccion,
        categorias=[categoria],
        colores=[
            SimpleNamespace(
                **producto_color.model_dump(),
                color=color,
                imagenes=[],
                skus=[SimpleNamespace(**sku.model_dump(), talla=talla)],
            )
        ],
    )


def test_producto_list_item_embebe_seccion_sin_colecciones() -> None:
    data = ProductoListItem.model_validate(_producto_orm()).model_dump()

    assert data["seccion"]["nombre"] == "Hombre"
    assert "colores" not in data
    assert "categorias" not in data


def test_producto_detail_embebe_el_agregado_completo_sin_volver_al_dueno() -> None:
    data = ProductoDetail.model_validate(_producto_orm()).model_dump(mode="json")
    color = data["colores"][0]

    assert data["categorias"][0]["slug"] == "camisas"
    assert "seccion" not in data["categorias"][0]
    assert color["color"]["codigo_hex"] == "#1E3A8A"
    assert color["skus"][0]["talla"]["etiqueta"] == "M"
    assert "producto" not in color
    assert color["producto_id"] == data["id"]
