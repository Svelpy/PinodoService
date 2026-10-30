import pytest
from pydantic import ValidationError

from app.domains.secciones.models import Seccion
from app.domains.secciones.schemas import (
    SeccionCreate,
    SeccionResponse,
    SeccionResponseAudit,
    SeccionUpdate,
)


def test_seccion_create_normaliza_nombre_y_visible_por_defecto() -> None:
    data = SeccionCreate(nombre="  Mujer  ")

    assert data.nombre == "Mujer"
    assert data.is_visible is True


@pytest.mark.parametrize("nombre", ["!!!", "   ", None])
def test_seccion_rechaza_nombre_sin_slug(nombre: object) -> None:
    with pytest.raises(ValidationError):
        SeccionCreate(nombre=nombre)


@pytest.mark.parametrize("field", ["nombre", "is_visible"])
def test_seccion_update_rechaza_null(field: str) -> None:
    with pytest.raises(ValidationError):
        SeccionUpdate.model_validate({field: None})


def test_seccion_update_conserva_false_explicito() -> None:
    assert SeccionUpdate(is_visible=False).model_dump(exclude_unset=True) == {"is_visible": False}


@pytest.mark.parametrize("is_visible", ["true", 1])
def test_seccion_rechaza_visibilidad_no_booleana(is_visible: object) -> None:
    with pytest.raises(ValidationError):
        SeccionCreate(nombre="Mujer", is_visible=is_visible)


def test_seccion_no_acepta_slug_ni_campos_extra() -> None:
    with pytest.raises(ValidationError):
        SeccionCreate(nombre="Mujer", slug="mujer")


def test_seccion_response_desde_modelo() -> None:
    seccion = Seccion(nombre="Mujer", slug="mujer")

    response = SeccionResponse.model_validate(seccion)
    audit = SeccionResponseAudit.model_validate(seccion)

    assert response.slug == "mujer"
    assert "is_deleted" not in response.model_dump()
    assert audit.is_deleted is False
