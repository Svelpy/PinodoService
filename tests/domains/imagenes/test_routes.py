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
from app.domains.imagenes.models import Imagen
from app.domains.imagenes.routes import router
from app.domains.imagenes.services import ImagenService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role, TipoImagen
from app.shared.schemas.pagination import PaginatedResponse


URL = "https://res.cloudinary.com/demo/image/upload/v1/foto.jpg"


def _imagen() -> Imagen:
    return Imagen(producto_color_id=uuid4(), url=URL)


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


def test_post_multipart_pasa_archivo_y_datos_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    producto_color_id = uuid4()

    with patch.object(ImagenService, "create", new=AsyncMock(return_value=_imagen())) as service:
        response = client.post(
            "/imagenes/",
            data={"producto_color_id": str(producto_color_id), "tipo": "DETALLE"},
            files={"file": ("foto.png", b"\x89PNG", "image/png")},
        )

    assert response.status_code == 201
    assert response.json()["url"] == URL
    args = service.await_args.args
    assert args[0] is db_session
    assert args[1].producto_color_id == producto_color_id
    assert args[1].tipo is TipoImagen.DETALLE
    assert args[2].filename == "foto.png"
    assert args[3] == current_user.id


def test_post_tipo_por_defecto_es_modelo(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(ImagenService, "create", new=AsyncMock(return_value=_imagen())) as service:
        client.post(
            "/imagenes/",
            data={"producto_color_id": str(uuid4())},
            files={"file": ("foto.png", b"\x89PNG", "image/png")},
        )

    assert service.await_args.args[1].tipo is TipoImagen.MODELO


@pytest.mark.parametrize(
    ("data", "files"),
    [
        ({"producto_color_id": str(uuid4())}, None),
        ({}, {"file": ("foto.png", b"\x89PNG", "image/png")}),
        (
            {"producto_color_id": str(uuid4()), "tipo": "BODEGON"},
            {"file": ("foto.png", b"\x89PNG", "image/png")},
        ),
    ],
)
def test_post_rechaza_peticiones_incompletas(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    data: dict[str, str],
    files: dict[str, tuple[str, bytes, str]] | None,
) -> None:
    client, _, _ = route_context

    response = client.post("/imagenes/", data=data, files=files)

    assert response.status_code == 422


def test_list_filtra_por_color_y_tipo(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    producto_color_id = uuid4()
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[_imagen()])

    with patch.object(ImagenService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get(
            "/imagenes/",
            params={"producto_color_id": str(producto_color_id), "tipo": "MODELO"},
        )

    assert response.status_code == 200
    service.assert_awaited_once_with(
        db_session,
        page=1,
        per_page=20,
        producto_color_id=producto_color_id,
        tipo=TipoImagen.MODELO,
    )


def test_patch_solo_acepta_tipo(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    assert client.patch(f"/imagenes/{uuid4()}", json={"url": URL}).status_code == 422
    assert client.patch(f"/imagenes/{uuid4()}", json={"tipo": None}).status_code == 422


def test_delete_responde_204(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    imagen_id = uuid4()

    with patch.object(ImagenService, "delete", new=AsyncMock()) as service:
        response = client.delete(f"/imagenes/{imagen_id}")

    assert response.status_code == 204
    service.assert_awaited_once_with(db_session, imagen_id, current_user.id)


def test_lecturas_declaran_list_item_y_detail(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    paths = client.app.openapi()["paths"]

    def schema_ref(path: str) -> str:
        return paths[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]

    assert schema_ref("/imagenes/").endswith("PaginatedResponse_ImagenListItem_")
    assert schema_ref("/imagenes/{imagen_id}").endswith("/ImagenDetail")
    assert schema_ref("/imagenes/{imagen_id}/audit").endswith("/ImagenResponseAudit")
