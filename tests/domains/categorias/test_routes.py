from collections.abc import AsyncGenerator, Iterator
from types import SimpleNamespace
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
from app.domains.categorias.models import Categoria
from app.domains.categorias.routes import router
from app.domains.categorias.services import CategoriaService
from app.domains.secciones.models import Seccion
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role
from app.shared.schemas.pagination import PaginatedResponse


SECCION = Seccion(nombre="Mujer", slug="mujer")


def _categoria() -> Categoria:
    return Categoria(seccion_id=SECCION.id, nombre="Ropa", slug="ropa")


def _list_item() -> SimpleNamespace:
    return SimpleNamespace(**_categoria().model_dump(), seccion=SECCION)


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


def test_list_embebe_la_seccion_y_pasa_filtros(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[_list_item()])
    seccion_id = uuid4()

    with patch.object(CategoriaService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get("/categorias/", params={"seccion_id": str(seccion_id)})

    assert response.status_code == 200
    assert response.json()["data"][0]["seccion"]["slug"] == "mujer"
    assert "subcategorias" not in response.json()["data"][0]
    service.assert_awaited_once_with(
        db_session,
        page=1,
        per_page=20,
        seccion_id=seccion_id,
        parent_id=None,
        is_visible=None,
    )


def test_arbol_no_se_confunde_con_un_id(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context

    with patch.object(CategoriaService, "arbol", new=AsyncMock(return_value=[])) as service:
        response = client.get("/categorias/arbol")

    assert response.status_code == 200
    assert response.json() == []
    service.assert_awaited_once_with(db_session, seccion_id=None)


def test_get_devuelve_detail_con_subcategorias(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    detail = SimpleNamespace(**_list_item().__dict__, subcategorias=[_list_item()])

    with patch.object(CategoriaService, "get", new=AsyncMock(return_value=detail)) as service:
        response = client.get(f"/categorias/{detail.id}")

    assert response.status_code == 200
    assert response.json()["seccion"]["nombre"] == "Mujer"
    assert len(response.json()["subcategorias"]) == 1
    service.assert_awaited_once_with(db_session, detail.id, load_detail=True)


def test_audit_reutiliza_get_sin_cargar_el_detail(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    categoria = _categoria()

    with patch.object(CategoriaService, "get", new=AsyncMock(return_value=categoria)) as service:
        response = client.get(f"/categorias/{categoria.id}/audit")

    assert response.status_code == 200
    assert response.json()["is_deleted"] is False
    service.assert_awaited_once_with(db_session, categoria.id)


def test_create_rechaza_slug_enviado_por_el_cliente(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.post(
        "/categorias/",
        json={"seccion_id": str(uuid4()), "nombre": "Ropa", "slug": "ropa"},
    )

    assert response.status_code == 422


def test_delete_responde_204(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    categoria_id = uuid4()

    with patch.object(CategoriaService, "delete", new=AsyncMock()) as service:
        response = client.delete(f"/categorias/{categoria_id}")

    assert response.status_code == 204
    service.assert_awaited_once_with(db_session, categoria_id, current_user.id)
