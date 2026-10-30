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
from app.domains.config.models import Config
from app.domains.config.routes import router
from app.domains.config.services import ConfigService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role


def _config() -> Config:
    return Config(nombre_tienda="Tienda Moda")


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


def test_get_y_audit(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    config = _config()

    with patch.object(ConfigService, "get", new=AsyncMock(return_value=config)):
        normal = client.get("/config/")
        audit = client.get("/config/audit")

    assert normal.status_code == 200
    assert normal.json()["nombre_tienda"] == "Tienda Moda"
    assert "updated_by" not in normal.json()
    assert "updated_by" in audit.json()


def test_patch_rechaza_horario_invalido(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.patch("/config/", json={"horario": {"lunes": "20:00-09:00"}})

    assert response.status_code == 422


def test_no_hay_post_ni_delete(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    assert client.post("/config/", json={"nombre_tienda": "Otra"}).status_code == 405
    assert client.delete("/config/").status_code == 405
