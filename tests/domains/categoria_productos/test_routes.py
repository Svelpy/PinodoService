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
from app.domains.categoria_productos.routes import router
from app.domains.categoria_productos.services import CategoriaProductoService
from app.domains.categorias.models import Categoria
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role


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


def test_put_reemplaza_y_devuelve_las_categorias_resultantes(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    producto_id = uuid4()
    categoria = Categoria(seccion_id=uuid4(), nombre="Camisas", slug="camisas")

    with patch.object(
        CategoriaProductoService,
        "replace_categorias",
        new=AsyncMock(return_value=[categoria]),
    ) as service:
        response = client.put(
            f"/productos/{producto_id}/categorias",
            json={"categoria_ids": [str(categoria.id), str(categoria.id)]},
        )

    assert response.status_code == 200
    assert [item["nombre"] for item in response.json()] == ["Camisas"]
    args = service.await_args.args
    assert args[0] is db_session
    assert args[1] == producto_id
    assert args[2].categoria_ids == [categoria.id]
    assert args[3] == current_user.id


@pytest.mark.parametrize(
    "body",
    [{}, {"categoria_ids": None}, {"categoria_ids": ["no-es-uuid"]}, {"categoria_ids": [], "extra": 1}],
)
def test_put_rechaza_cuerpos_invalidos(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    body: dict[str, object],
) -> None:
    client, _, _ = route_context

    response = client.put(f"/productos/{uuid4()}/categorias", json=body)

    assert response.status_code == 422


def test_no_hay_crud_del_enlace(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    assert client.get(f"/productos/{uuid4()}/categorias").status_code == 405
    assert client.post(f"/productos/{uuid4()}/categorias", json={}).status_code == 405
