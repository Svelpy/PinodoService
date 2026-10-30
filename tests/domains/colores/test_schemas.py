import pytest
from pydantic import ValidationError

from app.domains.colores.models import Color
from app.domains.colores.schemas import ColorCreate, ColorResponse, ColorUpdate


def test_color_create_normaliza_hex() -> None:
    data = ColorCreate(nombre=" Azul marino ", codigo_hex="1e3a8a")

    assert data.nombre == "Azul marino"
    assert data.codigo_hex == "#1E3A8A"


@pytest.mark.parametrize("codigo_hex", ["#FFF", "azul", None])
def test_color_rechaza_hex_invalido(codigo_hex: object) -> None:
    with pytest.raises(ValidationError):
        ColorCreate(nombre="Azul", codigo_hex=codigo_hex)


@pytest.mark.parametrize("field", ["nombre", "codigo_hex"])
def test_color_update_rechaza_null(field: str) -> None:
    with pytest.raises(ValidationError):
        ColorUpdate.model_validate({field: None})


def test_color_response_desde_modelo() -> None:
    response = ColorResponse.model_validate(Color(nombre="Azul", slug="azul", codigo_hex="#1E3A8A"))

    assert response.slug == "azul"
    assert response.codigo_hex == "#1E3A8A"


@pytest.mark.parametrize("nombre", ["---", "   "])
def test_color_rechaza_nombre_sin_slug(nombre: str) -> None:
    with pytest.raises(ValidationError):
        ColorCreate(nombre=nombre, codigo_hex="#1E3A8A")


def test_color_create_rechaza_slug_del_cliente() -> None:
    with pytest.raises(ValidationError):
        ColorCreate.model_validate({"nombre": "Azul", "slug": "azul", "codigo_hex": "#1E3A8A"})
