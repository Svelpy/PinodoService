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
from app.domains.colores.models import Color
from app.domains.productos.models import Producto
from app.domains.productos.routes import router
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.services import ProductoService
from app.domains.secciones.models import Seccion
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role
from app.shared.schemas.pagination import PaginatedResponse


def _producto() -> Producto:
    return Producto(seccion_id=uuid4(), nombre="Camisa Oxford")


SECCION = Seccion(nombre="Hombre", slug="hombre")


def _list_item() -> SimpleNamespace:
    return SimpleNamespace(**_producto().model_dump(), seccion=SECCION)


def _detail() -> SimpleNamespace:
    producto = _list_item()
    color = Color(nombre="Azul", slug="azul", codigo_hex="#1E3A8A")
    producto_color = ProductoColor(producto_id=producto.id, color_id=color.id)
    return SimpleNamespace(
        **producto.__dict__,
        categorias=[Categoria(seccion_id=SECCION.id, nombre="Camisas", slug="camisas")],
        colores=[
            SimpleNamespace(**producto_color.model_dump(), color=color, imagenes=[], skus=[])
        ],
    )


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


def test_list_pasa_filtros_y_embebe_la_seccion(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    seccion_id = uuid4()
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[_list_item()])

    with patch.object(ProductoService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get(
            "/productos/",
            params={"seccion_id": str(seccion_id), "is_visible": "false", "nombre": "oxford"},
        )

    assert response.status_code == 200
    assert response.json()["data"][0]["nombre"] == "Camisa Oxford"
    item = response.json()["data"][0]
    assert item["seccion"]["slug"] == "hombre"
    assert "categorias" not in item and "colores" not in item
    service.assert_awaited_once_with(
        db_session,
        page=1,
        per_page=20,
        seccion_id=seccion_id,
        categoria_id=None,
        is_visible=False,
        nombre="oxford",
    )


def test_create_pasa_el_actor_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context

    with patch.object(ProductoService, "create", new=AsyncMock(return_value=_producto())) as service:
        response = client.post(
            "/productos/",
            json={"seccion_id": str(uuid4()), "nombre": "Camisa Oxford"},
        )

    assert response.status_code == 201
    assert service.await_args.args[0] is db_session
    assert service.await_args.args[2] == current_user.id


def test_create_rechaza_slug_y_campos_desconocidos(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.post(
        "/productos/",
        json={"seccion_id": str(uuid4()), "nombre": "Camisa", "slug": "camisa"},
    )

    assert response.status_code == 422


def test_get_devuelve_detail_con_seccion_categorias_y_colores(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    detail = _detail()

    with patch.object(ProductoService, "get", new=AsyncMock(return_value=detail)) as service:
        response = client.get(f"/productos/{detail.id}")

    body = response.json()
    assert response.status_code == 200
    assert body["seccion"]["nombre"] == "Hombre"
    assert [categoria["nombre"] for categoria in body["categorias"]] == ["Camisas"]
    assert body["colores"][0]["color"]["nombre"] == "Azul"
    assert body["colores"][0]["imagenes"] == [] and body["colores"][0]["skus"] == []
    assert "is_deleted" not in body
    service.assert_awaited_once_with(db_session, detail.id, load_detail=True)


def test_audit_reutiliza_get_sin_cargar_el_detail(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    producto = _producto()

    with patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)) as service:
        audit = client.get(f"/productos/{producto.id}/audit")

    assert audit.json()["is_deleted"] is False
    assert "seccion" not in audit.json()
    service.assert_awaited_once_with(db_session, producto.id)


def test_delete_responde_204(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    producto_id = uuid4()

    with patch.object(ProductoService, "delete", new=AsyncMock()) as service:
        response = client.delete(f"/productos/{producto_id}")

    assert response.status_code == 204
    service.assert_awaited_once_with(db_session, producto_id, current_user.id)
