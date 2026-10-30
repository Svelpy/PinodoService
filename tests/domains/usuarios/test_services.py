from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.security import hash_password, verify_password
from app.domains.auth.services import AuthService
from app.domains.usuarios.models import Usuario
from app.domains.usuarios.repositories import UsuarioRepository
from app.domains.usuarios.schemas import (
    UsuarioChangePassword,
    UsuarioCreate,
    UsuarioResetPassword,
    UsuarioUpdate,
    UsuarioUpdateMe,
)
from app.domains.usuarios.services import UsuarioService
from app.shared.enums import Role
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _usuario(rol: Role = Role.ADMIN, password: str = "Clave123") -> Usuario:
    return Usuario(
        email="ana@tienda.com",
        password_hash=hash_password(password),
        nombre="Ana",
        rol=rol,
    )


def _create_data(rol: Role = Role.ADMIN) -> UsuarioCreate:
    return UsuarioCreate(email="nuevo@tienda.com", password="Clave123", nombre="Luis", rol=rol)


@pytest.mark.asyncio
async def test_create_asigna_auditoria_y_hashea_password() -> None:
    session = _session()
    actor_id = uuid4()

    with (
        patch.object(UsuarioRepository, "get_active_by_email", new=AsyncMock(return_value=None)),
        patch.object(UsuarioRepository, "add") as add,
    ):
        usuario = await UsuarioService.create(session, _create_data(), actor_id, Role.OWNER)

    assert usuario.created_by == actor_id
    assert usuario.updated_by == actor_id
    assert usuario.rol is Role.ADMIN
    assert usuario.password_hash != "Clave123"
    assert verify_password("Clave123", usuario.password_hash)
    add.assert_called_once_with(usuario)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("actor_role", "target_role"),
    [
        (Role.OWNER, Role.OWNER),
        (Role.OWNER, Role.SUPERADMIN),
        (Role.ADMIN, Role.ADMIN),
        (Role.SUPERADMIN, Role.SUPERADMIN),
    ],
)
@pytest.mark.asyncio
async def test_create_rechaza_rol_igual_o_superior(actor_role: Role, target_role: Role) -> None:
    session = _session()

    with pytest.raises(AppException) as error:
        await UsuarioService.create(session, _create_data(target_role), uuid4(), actor_role)

    assert error.value.status_code == 403
    assert "rol" in error.value.details
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rechaza_email_duplicado() -> None:
    session = _session()

    with patch.object(
        UsuarioRepository,
        "get_active_by_email",
        new=AsyncMock(return_value=_usuario()),
    ):
        with pytest.raises(AppException) as error:
            await UsuarioService.create(session, _create_data(), uuid4(), Role.OWNER)

    assert error.value.status_code == 409
    assert error.value.details == {"email": "El email ya está registrado."}


@pytest.mark.asyncio
async def test_update_admin_no_puede_ascender_por_encima_de_su_rol() -> None:
    usuario = _usuario(Role.ADMIN)

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)):
        with pytest.raises(AppException) as error:
            await UsuarioService.update(
                _session(),
                usuario.id,
                UsuarioUpdate(rol=Role.OWNER),
                uuid4(),
                Role.OWNER,
            )

    assert error.value.status_code == 403
    assert usuario.rol is Role.ADMIN


@pytest.mark.asyncio
async def test_update_admin_no_puede_tocar_usuario_de_su_mismo_rol() -> None:
    usuario = _usuario(Role.OWNER)

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)):
        with pytest.raises(AppException) as error:
            await UsuarioService.update(
                _session(),
                usuario.id,
                UsuarioUpdate(nombre="Otro"),
                uuid4(),
                Role.OWNER,
            )

    assert error.value.status_code == 403
    assert usuario.nombre == "Ana"


@pytest.mark.asyncio
async def test_update_aplica_cambios_y_null_explicito() -> None:
    usuario = _usuario(Role.ADMIN)
    usuario.telefono = "71234567"
    actor_id = uuid4()
    session = _session()

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)):
        result = await UsuarioService.update(
            session,
            usuario.id,
            UsuarioUpdate(nombre="Ana María", telefono=None),
            actor_id,
            Role.OWNER,
        )

    assert result.nombre == "Ana María"
    assert result.telefono is None
    assert result.updated_by == actor_id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_me_no_aplica_jerarquia() -> None:
    usuario = _usuario(Role.SUPERADMIN)

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)):
        result = await UsuarioService.update(
            _session(),
            usuario.id,
            UsuarioUpdateMe(nombre="Ana María"),
            usuario.id,
        )

    assert result.nombre == "Ana María"
    assert result.rol is Role.SUPERADMIN


@pytest.mark.asyncio
async def test_update_rechaza_email_de_otro_usuario() -> None:
    usuario = _usuario(Role.ADMIN)

    with (
        patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)),
        patch.object(
            UsuarioRepository,
            "get_active_by_email",
            new=AsyncMock(return_value=_usuario()),
        ),
    ):
        with pytest.raises(AppException) as error:
            await UsuarioService.update(
                _session(),
                usuario.id,
                UsuarioUpdateMe(email="otro@tienda.com"),
                usuario.id,
            )

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_es_logico_y_revoca_sesiones() -> None:
    usuario = _usuario(Role.ADMIN)
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)),
        patch.object(AuthService, "revoke_for_user", new=AsyncMock()) as revoke,
    ):
        await UsuarioService.delete(session, usuario.id, actor_id, Role.OWNER)

    assert usuario.is_deleted is True
    assert usuario.deleted_by == actor_id
    assert usuario.deleted_at is not None
    revoke.assert_awaited_once_with(session, usuario.id, "user_deleted")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_rechaza_superadmin() -> None:
    usuario = _usuario(Role.SUPERADMIN)

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)):
        with pytest.raises(AppException) as error:
            await UsuarioService.delete(_session(), usuario.id, uuid4(), Role.SUPERADMIN)

    assert error.value.status_code == 403
    assert usuario.is_deleted is False


@pytest.mark.asyncio
async def test_change_password_exige_password_actual_correcta() -> None:
    usuario = _usuario(password="Clave123")

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)):
        with pytest.raises(AppException) as error:
            await UsuarioService.change_password(
                _session(),
                usuario.id,
                UsuarioChangePassword(current_password="Incorrecta1", new_password="Nueva123"),
                usuario.id,
            )

    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_change_password_actualiza_hash_y_revoca_sesiones() -> None:
    usuario = _usuario(password="Clave123")
    session = _session()

    with (
        patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)),
        patch.object(AuthService, "revoke_for_user", new=AsyncMock()) as revoke,
    ):
        await UsuarioService.change_password(
            session,
            usuario.id,
            UsuarioChangePassword(current_password="Clave123", new_password="Nueva123"),
            usuario.id,
        )

    assert verify_password("Nueva123", usuario.password_hash)
    revoke.assert_awaited_once_with(session, usuario.id, "password_changed")


@pytest.mark.asyncio
async def test_reset_password_respeta_jerarquia() -> None:
    usuario = _usuario(Role.OWNER)

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)):
        with pytest.raises(AppException) as error:
            await UsuarioService.reset_password(
                _session(),
                usuario.id,
                UsuarioResetPassword(new_password="Nueva123"),
                uuid4(),
                Role.OWNER,
            )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(UsuarioRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await UsuarioService.get(_session(), uuid4())

    assert error.value.status_code == 404
