import pytest
from pydantic import ValidationError

from app.domains.config.models import Config
from app.domains.config.schemas import ConfigCreate, ConfigResponse, ConfigResponseAudit, ConfigUpdate


def test_config_create_minima_con_valores_por_defecto() -> None:
    data = ConfigCreate(nombre_tienda=" Tienda Moda ")

    assert data.nombre_tienda == "Tienda Moda"
    assert data.horario == {}
    assert data.redes_sociales == {}
    assert data.en_mantenimiento is False


def test_config_create_normaliza_campos() -> None:
    data = ConfigCreate(
        nombre_tienda="Tienda Moda",
        email_contacto=" Contacto@Tienda.com ",
        horario={"Sabado": "10:00-14:00"},
        redes_sociales={"Instagram": "https://instagram.com/tienda"},
    )

    assert data.email_contacto == "contacto@tienda.com"
    assert data.horario == {"sábado": "10:00-14:00"}
    assert data.redes_sociales == {"instagram": "https://instagram.com/tienda"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"logo_url": "logo.png"},
        {"horario": {"lunes": "20:00-09:00"}},
        {"horario": None},
        {"redes_sociales": None},
        {"whatsapp": "abc"},
        {"moneda": "BOB"},
    ],
)
def test_config_create_rechaza_datos_invalidos(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ConfigCreate.model_validate({"nombre_tienda": "Tienda Moda", **overrides})


@pytest.mark.parametrize("field", ["nombre_tienda", "horario", "redes_sociales", "en_mantenimiento"])
def test_config_update_rechaza_null_en_campos_no_nullable(field: str) -> None:
    with pytest.raises(ValidationError):
        ConfigUpdate.model_validate({field: None})


def test_config_update_permite_limpiar_campos_nullable() -> None:
    data = ConfigUpdate(whatsapp=None, map_url=None, horario={})

    assert data.model_dump(exclude_unset=True) == {"whatsapp": None, "map_url": None, "horario": {}}


def test_config_response_desde_modelo() -> None:
    config = Config(nombre_tienda="Tienda Moda", horario={"lunes": "09:00-20:00"})

    assert ConfigResponse.model_validate(config).horario == {"lunes": "09:00-20:00"}
    assert ConfigResponseAudit.model_validate(config).updated_by is None
