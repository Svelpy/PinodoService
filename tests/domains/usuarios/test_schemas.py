import pytest
from pydantic import ValidationError

from app.domains.usuarios.models import Usuario
from app.domains.usuarios.schemas import (
    UsuarioChangePassword,
    UsuarioCreate,
    UsuarioResetPassword,
    UsuarioResponse,
    UsuarioResponseAudit,
    UsuarioUpdate,
    UsuarioUpdateMe,
)
from app.shared.enums import Role


def _create_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "email": "Ana@Tienda.COM ",
        "password": "Clave123",
        "nombre": " Ana ",
        "rol": "ADMIN",
    }
    data.update(overrides)
    return data


def test_usuario_create_normaliza_datos() -> None:
    data = UsuarioCreate.model_validate(_create_data(telefono=" 71234567 "))

    assert data.email == "ana@tienda.com"
    assert data.nombre == "Ana"
    assert data.telefono == "71234567"
    assert data.apellidos is None
    assert data.rol is Role.ADMIN


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "no-es-email"},
        {"password": "123"},
        {"nombre": "Ana123"},
        {"telefono": "12"},
        {"rol": "CLIENTE"},
        {"rol": None},
    ],
)
def test_usuario_create_rechaza_datos_invalidos(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UsuarioCreate.model_validate(_create_data(**overrides))


@pytest.mark.parametrize("field", ["email", "nombre"])
def test_usuario_update_me_rechaza_null_en_campos_no_nullable(field: str) -> None:
    with pytest.raises(ValidationError):
        UsuarioUpdateMe.model_validate({field: None})


def test_usuario_update_me_permite_limpiar_campos_nullable() -> None:
    data = UsuarioUpdateMe(apellidos=None, telefono=None)

    assert data.model_dump(exclude_unset=True) == {"apellidos": None, "telefono": None}


def test_usuario_update_me_no_permite_cambiar_rol() -> None:
    with pytest.raises(ValidationError):
        UsuarioUpdateMe.model_validate({"rol": "OWNER"})


def test_usuario_update_permite_rol_pero_no_null() -> None:
    assert UsuarioUpdate(rol=Role.OWNER).rol is Role.OWNER

    with pytest.raises(ValidationError):
        UsuarioUpdate(rol=None)


def test_usuario_password_schemas() -> None:
    assert UsuarioResetPassword(new_password="Nueva123").new_password == "Nueva123"
    assert UsuarioChangePassword(current_password="Actual123", new_password="Nueva123")

    with pytest.raises(ValidationError):
        UsuarioChangePassword(new_password="Nueva123")


def test_usuario_response_no_expone_password_hash() -> None:
    usuario = Usuario(
        email="ana@tienda.com",
        password_hash="hash",
        nombre="Ana",
        rol=Role.ADMIN,
    )

    assert "password_hash" not in UsuarioResponse.model_validate(usuario).model_dump()
    assert "password_hash" not in UsuarioResponseAudit.model_validate(usuario).model_dump()
