from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.imagenes.models import Imagen
from app.domains.imagenes.schemas import (
    ImagenCreate,
    ImagenDetail,
    ImagenListItem,
    ImagenResponse,
)
from app.shared.enums import TipoImagen


SUBIDA = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/imagenes/foto.jpg"


def test_imagen_create_hereda_url_y_tipo_y_exige_el_color() -> None:
    data = ImagenCreate(producto_color_id=uuid4(), url=SUBIDA)

    assert data.tipo is TipoImagen.MODELO
    example = ImagenCreate.model_config["json_schema_extra"]["example"]
    ImagenCreate.model_validate(example)
    assert list(example) == list(ImagenCreate.model_fields)


@pytest.mark.parametrize(
    "overrides",
    [{"url": None}, {"url": "no-es-url"}, {"tipo": "BODEGON"}, {"tipo": None}, {"producto_color_id": None}],
)
def test_imagen_create_rechaza_datos_invalidos(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ImagenCreate.model_validate({"producto_color_id": str(uuid4()), "url": SUBIDA, **overrides})


def test_imagen_response_desde_modelo() -> None:
    imagen = Imagen(producto_color_id=uuid4(), url="https://res.cloudinary.com/demo/x.jpg")

    assert ImagenResponse.model_validate(imagen).tipo is TipoImagen.MODELO


def test_imagen_list_item_y_detail_no_anaden_campos() -> None:
    assert ImagenListItem.model_fields.keys() == ImagenResponse.model_fields.keys()
    assert ImagenDetail.model_fields.keys() == ImagenResponse.model_fields.keys()


def test_ejemplo_de_biblioteca_valida_y_sigue_el_orden() -> None:
    from app.domains.imagenes.schemas import ImagenBibliotecaItem

    example = ImagenBibliotecaItem.model_config["json_schema_extra"]["example"]
    ImagenBibliotecaItem.model_validate(example)
    assert list(example) == list(ImagenBibliotecaItem.model_fields)
