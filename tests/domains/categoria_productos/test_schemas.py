from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categoria_productos.schemas import (
    CategoriaProductoCreate,
    CategoriaProductoDetail,
    CategoriaProductoListItem,
    CategoriaProductoResponse,
    CategoriaProductoUpdate,
)
from app.domains.categorias.models import Categoria
from app.domains.productos.models import Producto


def test_categoria_producto_create_exige_ambas_referencias() -> None:
    with pytest.raises(ValidationError):
        CategoriaProductoCreate(categoria_id=uuid4())


@pytest.mark.parametrize("field", ["categoria_id", "producto_id"])
def test_categoria_producto_update_rechaza_null(field: str) -> None:
    with pytest.raises(ValidationError):
        CategoriaProductoUpdate.model_validate({field: None})


def test_categoria_producto_response_desde_modelo() -> None:
    enlace = CategoriaProducto(categoria_id=uuid4(), producto_id=uuid4())

    assert CategoriaProductoResponse.model_validate(enlace).id == enlace.id


def test_categoria_producto_list_item_embebe_ambas_referencias() -> None:
    seccion_id = uuid4()
    categoria = Categoria(seccion_id=seccion_id, nombre="Camisas", slug="camisas")
    producto = Producto(seccion_id=seccion_id, nombre="Camisa Oxford")
    enlace = CategoriaProducto(categoria_id=categoria.id, producto_id=producto.id)
    orm = SimpleNamespace(**enlace.model_dump(), categoria=categoria, producto=producto)

    data = CategoriaProductoListItem.model_validate(orm).model_dump()

    assert data["categoria"]["slug"] == "camisas"
    assert data["producto"]["nombre"] == "Camisa Oxford"


def test_categoria_producto_detail_no_anade_campos() -> None:
    assert CategoriaProductoDetail.model_fields.keys() == CategoriaProductoListItem.model_fields.keys()
