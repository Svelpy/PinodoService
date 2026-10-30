import pytest
from pydantic import ValidationError

from app.domains.tallas.models import Talla
from app.domains.tallas.schemas import TallaCreate, TallaResponse, TallaUpdate


def test_talla_create_normaliza_etiqueta() -> None:
    assert TallaCreate(etiqueta="  6-7 años ").etiqueta == "6-7 años"


@pytest.mark.parametrize("etiqueta", ["", "   ", None, "x" * 31])
def test_talla_rechaza_etiqueta_invalida(etiqueta: object) -> None:
    with pytest.raises(ValidationError):
        TallaCreate(etiqueta=etiqueta)


def test_talla_update_rechaza_null() -> None:
    with pytest.raises(ValidationError):
        TallaUpdate(etiqueta=None)


def test_talla_response_desde_modelo() -> None:
    assert TallaResponse.model_validate(Talla(etiqueta="M")).etiqueta == "M"
