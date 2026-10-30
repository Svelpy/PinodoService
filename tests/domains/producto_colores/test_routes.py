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
from app.domains.colores.models import Color
from app.domains.imagenes.models import Imagen
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.routes import router
from app.domains.producto_colores.services import ProductoColorService
from app.domains.skus.models import Sku
from app.domains.tallas.models import Talla
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role
from app.shared.schemas.pagination import PaginatedResponse


def _producto_color() -> ProductoColor:
    return ProductoColor(producto_id=uuid4(), color_id=uuid4())


COLOR = Color(nombre="Azul", slug="azul", codigo_hex="#1E3A8A")


def _list_item() -> SimpleNamespace:
    return SimpleNamespace(**_producto_color().model_dump(), color=COLOR)


def _detail() -> SimpleNamespace:
    producto_color = _list_item()
    imagen = Imagen(producto_color_id=producto_color.id, url="https://res.cloudinary.com/x.jpg")
    sku = Sku(
        producto_color_id=producto_color.id,
        talla_id=uuid4(),
        precio={"normal": 29.95, "rebajado": None, "rebaja_hasta": None},
        stock={"cantidad": 3, "minimo": 1, "actualizado": None},
    )
    return SimpleNamespace(
        **producto_color.__dict__,
        imagenes=[imagen],
        skus=[SimpleNamespace(**sku.model_dump(), talla=Talla(etiqueta="M"))],
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


def test_list_filtra_por_producto_y_embebe_el_color(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    producto_id = uuid4()
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[_list_item()])

    with patch.object(ProductoColorService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get("/producto-colores/", params={"producto_id": str(producto_id)})

    assert response.status_code == 200
    item = response.json()["data"][0]
    assert item["color"]["codigo_hex"] == "#1E3A8A"
    assert "imagenes" not in item and "skus" not in item
    service.assert_awaited_once_with(
        db_session,
        page=1,
        per_page=20,
        producto_id=producto_id,
        color_id=None,
        is_visible=None,
    )


def test_create_pasa_el_actor_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context

    with patch.object(
        ProductoColorService,
        "create",
        new=AsyncMock(return_value=_producto_color()),
    ) as service:
        response = client.post(
            "/producto-colores/",
            json={"producto_id": str(uuid4()), "color_id": str(uuid4())},
        )

    assert response.status_code == 201
    assert service.await_args.args[0] is db_session
    assert service.await_args.args[2] == current_user.id


def test_patch_rechaza_cambiar_el_producto(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.patch(f"/producto-colores/{uuid4()}", json={"producto_id": str(uuid4())})

    assert response.status_code == 422


def test_get_devuelve_detail_con_color_imagenes_y_skus(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    detail = _detail()

    with patch.object(ProductoColorService, "get", new=AsyncMock(return_value=detail)) as service:
        response = client.get(f"/producto-colores/{detail.id}")

    body = response.json()
    assert response.status_code == 200
    assert body["color"]["nombre"] == "Azul"
    assert body["imagenes"][0]["url"].startswith("https://")
    assert body["skus"][0]["talla"]["etiqueta"] == "M"
    assert body["skus"][0]["precio"]["normal"] == 29.95
    assert "is_deleted" not in body
    service.assert_awaited_once_with(db_session, detail.id, load_detail=True)


def test_audit_reutiliza_get_sin_cargar_el_detail(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    producto_color = _producto_color()

    with patch.object(
        ProductoColorService,
        "get",
        new=AsyncMock(return_value=producto_color),
    ) as service:
        audit = client.get(f"/producto-colores/{producto_color.id}/audit")

    assert audit.json()["is_deleted"] is False
    assert "color" not in audit.json()
    service.assert_awaited_once_with(db_session, producto_color.id)


def test_delete_responde_204(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    producto_color_id = uuid4()

    with patch.object(ProductoColorService, "delete", new=AsyncMock()) as service:
        response = client.delete(f"/producto-colores/{producto_color_id}")

    assert response.status_code == 204
    service.assert_awaited_once_with(db_session, producto_color_id, current_user.id)
