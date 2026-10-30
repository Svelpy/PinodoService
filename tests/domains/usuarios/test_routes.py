from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import get_current_principal
from app.domains.auth.schemas import CurrentUser
from app.domains.usuarios.models import Usuario
from app.domains.usuarios.routes import router
from app.domains.usuarios.services import UsuarioService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role
from app.shared.schemas.pagination import PaginatedResponse


def _usuario(**overrides: object) -> Usuario:
    values: dict[str, object] = {
        "email": "ana@tienda.com",
        "password_hash": "hash",
        "nombre": "Ana",
        "rol": Role.ADMIN,
    }
    values.update(overrides)
    return Usuario(**values)


@pytest.fixture
def route_context() -> Iterator[tuple[TestClient, CurrentUser, MagicMock]]:
    app = FastAPI()
    register_exception_handlers(app, get_settings())
    app.include_router(router)

    current_user = CurrentUser(id=uuid4(), rol=Role.OWNER)
    db_session = MagicMock(spec=AsyncSession)

    async def override_principal() -> CurrentUser:
        return current_user

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_current_principal] = override_principal
    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        yield client, current_user, db_session


def test_get_me_reutiliza_get_con_el_usuario_autenticado(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    usuario = _usuario(id=current_user.id)

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)) as service:
        response = client.get("/usuarios/me")

    assert response.status_code == 200
    assert response.json()["id"] == str(current_user.id)
    assert "password_hash" not in response.json()
    service.assert_awaited_once_with(db_session, current_user.id)


def test_update_me_rechaza_cambio_de_rol(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.patch("/usuarios/me", json={"rol": "SUPERADMIN"})

    assert response.status_code == 422


def test_list_devuelve_paginacion(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[_usuario()])

    with patch.object(UsuarioService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get("/usuarios/", params={"rol": "ADMIN"})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    service.assert_awaited_once_with(db_session, page=1, per_page=20, rol=Role.ADMIN)


def test_create_pasa_el_rol_del_actor_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, _ = route_context

    with patch.object(UsuarioService, "create", new=AsyncMock(return_value=_usuario())) as service:
        response = client.post(
            "/usuarios/",
            json={"email": "luis@tienda.com", "password": "Clave123", "nombre": "Luis", "rol": "ADMIN"},
        )

    assert response.status_code == 201
    assert service.await_args.kwargs == {"actor_id": current_user.id, "actor_role": Role.OWNER}


def test_audit_expone_campos_de_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    usuario = _usuario()

    with patch.object(UsuarioService, "get", new=AsyncMock(return_value=usuario)):
        normal = client.get(f"/usuarios/{usuario.id}")
        audit = client.get(f"/usuarios/{usuario.id}/audit")

    assert "is_deleted" not in normal.json()
    assert audit.json()["is_deleted"] is False


def test_delete_responde_204(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    usuario_id = uuid4()

    with patch.object(UsuarioService, "delete", new=AsyncMock()) as service:
        response = client.delete(f"/usuarios/{usuario_id}")

    assert response.status_code == 204
    service.assert_awaited_once_with(db_session, usuario_id, current_user.id, Role.OWNER)
