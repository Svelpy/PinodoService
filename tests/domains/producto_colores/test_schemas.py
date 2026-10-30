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


@pytest.mark.parametrize("field", ["color_id", "is_visible"])
def test_producto_color_update_rechaza_null(field: str) -> None:
    with pytest.raises(ValidationError):
        ProductoColorUpdate.model_validate({field: None})


def test_producto_color_response_desde_modelo() -> None:
    producto_color = ProductoColor(producto_id=uuid4(), color_id=uuid4())

    assert ProductoColorResponse.model_validate(producto_color).is_visible is True


def _producto_color_orm() -> SimpleNamespace:
    color = Color(nombre="Azul", codigo_hex="#1E3A8A")
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
    data = ProductoColorDetail.model_validate(_producto_color_orm()).model_dump(mode="json")

    assert data["imagenes"][0]["url"] == "https://res.cloudinary.com/demo/x.jpg"
    assert data["skus"][0]["talla"]["etiqueta"] == "M"
    assert data["skus"][0]["precio"]["normal"] == 29.95
    assert "producto_color" not in data["skus"][0]
