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
from app.domains.imagenes.schemas import ImagenBibliotecaItem, ImagenResponse
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


def test_post_json_pasa_los_datos_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    producto_color_id = uuid4()

    with patch.object(ImagenService, "create", new=AsyncMock(return_value=_imagen())) as service:
        response = client.post(
            "/imagenes/",
            json={"producto_color_id": str(producto_color_id), "url": SUBIDA, "tipo": "DETALLE"},
        )

    assert response.status_code == 201
    args = service.await_args.args
    assert args[0] is db_session
    assert (args[1].producto_color_id, args[1].url, args[1].tipo) == (
        producto_color_id,
        SUBIDA,
        TipoImagen.DETALLE,
    )
    assert args[2] == current_user.id


@pytest.mark.parametrize(
    "body",
    [
        {"url": "https://res.cloudinary.com/demo/image/upload/v1/pinodo/imagenes/a.jpg"},
        {"producto_color_id": "11111111-1111-4111-8111-111111111111"},
        {"producto_color_id": "11111111-1111-4111-8111-111111111111", "url": "x", "tipo": "BODEGON"},
    ],
)
def test_post_rechaza_peticiones_incompletas(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    body: dict[str, str],
) -> None:
    client, _, _ = route_context

    with patch.object(ImagenService, "create", new=AsyncMock()) as service:
        response = client.post("/imagenes/", json=body)

    assert response.status_code == 422
    service.assert_not_awaited()


def test_post_ya_no_acepta_archivos(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(ImagenService, "create", new=AsyncMock()) as service:
        response = client.post(
            "/imagenes/",
            data={"producto_color_id": str(uuid4())},
            files={"file": ("foto.png", b"\x89PNG", "image/png")},
        )

    assert response.status_code == 422
    service.assert_not_awaited()


SUBIDA = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/imagenes/foto.jpg"


def test_no_existe_listado(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    # La galería de un color viene en el Detail; para navegar, /imagenes/biblioteca.
    response = client.get("/imagenes/")

    assert response.status_code == 405


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

    assert "get" not in paths["/imagenes/"]
    assert schema_ref("/imagenes/{imagen_id}").endswith("/ImagenDetail")
    assert schema_ref("/imagenes/{imagen_id}/audit").endswith("/ImagenResponseAudit")


PENDIENTE = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/imagenes/foto.jpg"


def test_upload_pendiente_devuelve_la_url_sin_crear_registro(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context

    with (
        patch.object(ImagenService, "upload_pending", new=AsyncMock(return_value=PENDIENTE)) as upload,
        patch.object(ImagenService, "create", new=AsyncMock()) as create,
    ):
        response = client.post(
            "/imagenes/uploads",
            files={"file": ("foto.jpg", b"jpg", "image/jpeg")},
        )

    assert response.status_code == 201
    assert response.json() == {"url": PENDIENTE}
    assert upload.await_args.args[2] == current_user.id
    create.assert_not_awaited()
    db_session.commit.assert_not_called()


def test_upload_pendiente_exige_archivo(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.post("/imagenes/uploads")

    assert response.status_code == 422


def test_upload_pendiente_cajero_responde_403(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.CAJERO

    with patch.object(ImagenService, "upload_pending", new=AsyncMock()) as upload:
        response = client.post(
            "/imagenes/uploads",
            files={"file": ("foto.jpg", b"jpg", "image/jpeg")},
        )

    assert response.status_code == 403
    upload.assert_not_awaited()


def test_biblioteca_pasa_los_filtros_y_no_choca_con_get_por_id(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    item = ImagenBibliotecaItem(
        **ImagenResponse.model_validate(_imagen()).model_dump(),
        producto_id=uuid4(),
        producto_nombre="Camisa Oxford",
        color_id=uuid4(),
        color_nombre="Azul",
        color_codigo_hex="#1E3A8A",
    )
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[item])
    producto_id = uuid4()

    with (
        patch.object(ImagenService, "list_biblioteca", new=AsyncMock(return_value=page)) as service,
        patch.object(ImagenService, "get", new=AsyncMock()) as get,
    ):
        response = client.get(
            "/imagenes/biblioteca",
            params={"producto_id": str(producto_id), "tipo": "MODELO", "nombre": "camisa"},
        )

    assert response.status_code == 200
    assert response.json()["data"][0]["producto_nombre"] == "Camisa Oxford"
    assert response.json()["data"][0]["color_codigo_hex"] == "#1E3A8A"
    service.assert_awaited_once_with(
        db_session,
        page=1,
        per_page=20,
        producto_id=producto_id,
        color_id=None,
        tipo=TipoImagen.MODELO,
        nombre="camisa",
    )
    get.assert_not_awaited()


def test_biblioteca_cajero_puede_leer(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.CAJERO
    page = PaginatedResponse(total=0, page=1, per_page=20, total_pages=0, data=[])

    with patch.object(ImagenService, "list_biblioteca", new=AsyncMock(return_value=page)):
        response = client.get("/imagenes/biblioteca")

    assert response.status_code == 200
