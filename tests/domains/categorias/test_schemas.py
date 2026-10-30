from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.categorias.models import Categoria
from app.domains.categorias.schemas import (
    CategoriaCreate,
    CategoriaDetail,
    CategoriaListItem,
    CategoriaResponse,
    CategoriaUpdate,
)
from app.domains.secciones.models import Seccion


def test_categoria_create_raiz_por_defecto() -> None:
    data = CategoriaCreate(seccion_id=uuid4(), nombre=" Cazadoras ")

    assert data.nombre == "Cazadoras"
    assert data.parent_id is None
    assert data.is_visible is True


def test_categoria_create_exige_seccion() -> None:
    with pytest.raises(ValidationError):
        CategoriaCreate(nombre="Cazadoras")


@pytest.mark.parametrize("field", ["seccion_id", "nombre", "is_visible"])
def test_categoria_update_rechaza_null_en_campos_no_nullable(field: str) -> None:
    with pytest.raises(ValidationError):
        CategoriaUpdate.model_validate({field: None})


def test_categoria_update_parent_null_convierte_en_raiz() -> None:
    assert CategoriaUpdate(parent_id=None).model_dump(exclude_unset=True) == {"parent_id": None}


def test_categoria_response_desde_modelo() -> None:
    categoria = Categoria(seccion_id=uuid4(), nombre="Bombers", slug="bombers")

    assert CategoriaResponse.model_validate(categoria).parent_id is None


def test_categoria_detail_baja_un_solo_nivel_de_subcategorias() -> None:
    seccion = Seccion(nombre="Mujer", slug="mujer")
    padre = Categoria(seccion_id=seccion.id, nombre="Cazadoras", slug="cazadoras")
    hija = Categoria(seccion_id=seccion.id, parent_id=padre.id, nombre="Bombers", slug="bombers")
    orm = SimpleNamespace(
        **padre.model_dump(),
        seccion=seccion,
        subcategorias=[SimpleNamespace(**hija.model_dump(), seccion=seccion)],
    )

    data = CategoriaDetail.model_validate(orm).model_dump()

    assert data["seccion"]["slug"] == "mujer"
    assert data["subcategorias"][0]["nombre"] == "Bombers"
    assert data["subcategorias"][0]["parent_id"] == padre.id
    assert "subcategorias" not in data["subcategorias"][0]
    assert "parent" not in data


def test_categoria_list_item_no_tiene_colecciones() -> None:
    assert "subcategorias" not in CategoriaListItem.model_fields
