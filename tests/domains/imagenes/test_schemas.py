from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.imagenes.models import Imagen
from app.domains.imagenes.schemas import (
    ImagenCreate,
    ImagenDetail,
    ImagenListItem,
    ImagenResponse,
    ImagenUpdate,
)
from app.shared.enums import TipoImagen


def test_imagen_create_tipo_modelo_por_defecto() -> None:
    assert ImagenCreate(producto_color_id=uuid4()).tipo is TipoImagen.MODELO


@pytest.mark.parametrize("overrides", [{"url": "https://a.com/x.jpg"}, {"tipo": "BODEGON"}, {"tipo": None}])
def test_imagen_create_rechaza_url_y_tipo_invalido(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ImagenCreate.model_validate({"producto_color_id": str(uuid4()), **overrides})


def test_imagen_update_no_permite_cambiar_dueno_ni_null() -> None:
    with pytest.raises(ValidationError):
        ImagenUpdate.model_validate({"producto_color_id": str(uuid4())})

    with pytest.raises(ValidationError):
        ImagenUpdate(tipo=None)


def test_imagen_response_desde_modelo() -> None:
    imagen = Imagen(producto_color_id=uuid4(), url="https://res.cloudinary.com/demo/x.jpg")

    assert ImagenResponse.model_validate(imagen).tipo is TipoImagen.MODELO


def test_imagen_list_item_y_detail_no_anaden_campos() -> None:
    assert ImagenListItem.model_fields.keys() == ImagenResponse.model_fields.keys()
    assert ImagenDetail.model_fields.keys() == ImagenResponse.model_fields.keys()
