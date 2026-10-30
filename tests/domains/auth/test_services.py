from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import get_settings
from app.core.security import hash_password
from app.domains.auth.repositories import AuthSessionRepository
from app.domains.auth.schemas import UserLogin
from app.domains.auth.services import AuthService
from app.domains.usuarios.models import Usuario
from app.domains.usuarios.repositories import UsuarioRepository
from app.shared.enums import Role
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_login_por_email_emite_tokens_y_guarda_sesion() -> None:
    usuario = Usuario(
        email="ana@tienda.com",
        password_hash=hash_password("Clave123"),
        nombre="Ana",
        rol=Role.SUPERADMIN,
    )
    session = _session()

    with (
        patch.object(
            UsuarioRepository,
            "get_active_by_email",
            new=AsyncMock(return_value=usuario),
        ) as get_by_email,
        patch.object(AuthSessionRepository, "add", new=AsyncMock()) as add_session,
    ):
        tokens = await AuthService.login(
            session,
            UserLogin(email=" Ana@Tienda.com ", password="Clave123"),
            get_settings(),
        )

    get_by_email.assert_awaited_once_with("ana@tienda.com")
    add_session.assert_awaited_once()
    assert add_session.await_args.args[0].user_id == usuario.id
    assert tokens.access_token
    assert tokens.refresh_token
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("found", [True, False])
@pytest.mark.asyncio
async def test_login_falla_con_el_mismo_mensaje_si_no_existe_o_password_incorrecta(
    found: bool,
) -> None:
    usuario = Usuario(
        email="ana@tienda.com",
        password_hash=hash_password("Clave123"),
        nombre="Ana",
        rol=Role.ADMIN,
    )

    with patch.object(
        UsuarioRepository,
        "get_active_by_email",
        new=AsyncMock(return_value=usuario if found else None),
    ):
        with pytest.raises(AppException) as error:
            await AuthService.login(
                _session(),
                UserLogin(email="ana@tienda.com", password="Incorrecta1"),
                get_settings(),
            )

    assert error.value.status_code == 401
    assert error.value.message == "Email o contraseña incorrectos."
