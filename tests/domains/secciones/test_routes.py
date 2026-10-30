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
from app.domains.secciones.models import Seccion
from app.domains.secciones.routes import router
from app.domains.secciones.services import SeccionService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role
from app.shared.schemas.pagination import PaginatedResponse


def _seccion() -> Seccion:
    return Seccion(nombre="Mujer", slug="mujer")


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


def test_list_devuelve_paginacion_con_filtro_de_visibilidad(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[_seccion()])

    with patch.object(SeccionService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get("/secciones/", params={"is_visible": "true"})

    assert response.status_code == 200
    assert response.json()["data"][0]["slug"] == "mujer"
    service.assert_awaited_once_with(db_session, page=1, per_page=20, is_visible=True)


def test_create_pasa_el_actor_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context

    with patch.object(SeccionService, "create", new=AsyncMock(return_value=_seccion())) as service:
        response = client.post("/secciones/", json={"nombre": "Mujer"})

    assert response.status_code == 201
    assert service.await_args.args[0] is db_session
    assert service.await_args.args[2] == current_user.id


def test_create_rechaza_slug_enviado_por_el_cliente(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.post("/secciones/", json={"nombre": "Mujer", "slug": "otra"})

    assert response.status_code == 422


def test_audit_expone_campos_de_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    seccion = _seccion()

    with patch.object(SeccionService, "get", new=AsyncMock(return_value=seccion)):
        normal = client.get(f"/secciones/{seccion.id}")
        audit = client.get(f"/secciones/{seccion.id}/audit")

    assert "is_deleted" not in normal.json()
    assert audit.json()["is_deleted"] is False


def test_delete_responde_204(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    current_user.rol = Role.OWNER
    seccion_id = uuid4()

    with patch.object(SeccionService, "delete", new=AsyncMock()) as service:
        response = client.delete(f"/secciones/{seccion_id}")

    assert response.status_code == 204
    service.assert_awaited_once_with(db_session, seccion_id, current_user.id)


def test_delete_admin_responde_403(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(SeccionService, "delete", new=AsyncMock()) as service:
        response = client.delete(f"/secciones/{uuid4()}")

    assert response.status_code == 403
    service.assert_not_awaited()
