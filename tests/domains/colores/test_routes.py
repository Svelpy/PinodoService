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
from app.domains.colores.models import Color
from app.domains.colores.routes import router
from app.domains.colores.services import ColorService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role
from app.shared.schemas.pagination import PaginatedResponse


def _color() -> Color:
    return Color(nombre="Azul marino", slug="azul-marino", codigo_hex="#1E3A8A")


@pytest.fixture
def route_context() -> Iterator[tuple[TestClient, CurrentUser, MagicMock]]:
    app = FastAPI()
    register_exception_handlers(app, get_settings())
    app.include_router(router)

    current_user = CurrentUser(id=uuid4(), rol=Role.ADMIN)
    db_session = MagicMock(spec=AsyncSession)

    async def override_principal() -> CurrentUser:
        return current_user

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_current_principal] = override_principal
    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        yield client, current_user, db_session


def test_list_devuelve_paginacion(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[_color()])

    with patch.object(ColorService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get("/colores/")

    assert response.status_code == 200
    assert response.json()["data"][0]["codigo_hex"] == "#1E3A8A"
    service.assert_awaited_once_with(db_session, page=1, per_page=20)


def test_create_pasa_el_actor_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context

    with patch.object(ColorService, "create", new=AsyncMock(return_value=_color())) as service:
        response = client.post("/colores/", json={"nombre": "Azul marino", "codigo_hex": "1e3a8a"})

    assert response.status_code == 201
    assert service.await_args.args[0] is db_session
    assert service.await_args.args[1].codigo_hex == "#1E3A8A"
    assert service.await_args.args[2] == current_user.id


def test_create_rechaza_hex_invalido(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.post("/colores/", json={"nombre": "Azul", "codigo_hex": "#12345G"})

    assert response.status_code == 422


def test_audit_expone_campos_de_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    color = _color()

    with patch.object(ColorService, "get", new=AsyncMock(return_value=color)):
        normal = client.get(f"/colores/{color.id}")
        audit = client.get(f"/colores/{color.id}/audit")

    assert "is_deleted" not in normal.json()
    assert audit.json()["is_deleted"] is False


def test_delete_responde_204(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    color_id = uuid4()

    with patch.object(ColorService, "delete", new=AsyncMock()) as service:
        response = client.delete(f"/colores/{color_id}")

    assert response.status_code == 204
    service.assert_awaited_once_with(db_session, color_id, current_user.id)
