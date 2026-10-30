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
from app.domains.skus.models import Sku
from app.domains.skus.routes import router
from app.domains.skus.services import SkuService
from app.domains.tallas.models import Talla
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role
from app.shared.schemas.pagination import PaginatedResponse


def _sku() -> Sku:
    return Sku(
        producto_color_id=uuid4(),
        talla_id=uuid4(),
        precio={"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
        stock={"cantidad": 12, "minimo": 3, "actualizado": "2026-10-30T10:00:00+00:00"},
    )


def _sku_con_talla() -> SimpleNamespace:
    return SimpleNamespace(**_sku().model_dump(), talla=Talla(etiqueta="M"))


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


def test_list_embebe_talla_expone_precio_como_numero_y_pasa_filtros(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    producto_color_id = uuid4()
    page = PaginatedResponse(total=1, page=1, per_page=20, total_pages=1, data=[_sku_con_talla()])

    with patch.object(SkuService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get(
            "/skus/",
            params={"producto_color_id": str(producto_color_id), "bajo_minimo": "true"},
        )

    assert response.status_code == 200
    item = response.json()["data"][0]
    assert item["precio"] == {"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"}
    assert item["stock"]["cantidad"] == 12
    assert item["talla"]["etiqueta"] == "M"
    service.assert_awaited_once_with(
        db_session,
        page=1,
        per_page=20,
        producto_color_id=producto_color_id,
        talla_id=None,
        is_visible=None,
        bajo_minimo=True,
    )


def test_get_devuelve_detail_con_la_talla(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    sku = _sku_con_talla()

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)) as service:
        response = client.get(f"/skus/{sku.id}")

    assert response.status_code == 200
    assert response.json()["talla"]["etiqueta"] == "M"
    service.assert_awaited_once_with(db_session, sku.id, load_detail=True)


def test_create_pasa_el_actor_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context

    with patch.object(SkuService, "create", new=AsyncMock(return_value=_sku())) as service:
        response = client.post(
            "/skus/",
            json={
                "producto_color_id": str(uuid4()),
                "talla_id": str(uuid4()),
                "precio": {"normal": 29.95},
            },
        )

    assert response.status_code == 201
    assert service.await_args.args[0] is db_session
    assert service.await_args.args[1].stock.cantidad == 0
    assert service.await_args.args[2] == current_user.id


@pytest.mark.parametrize(
    "precio",
    [
        {"normal": 0},
        {"normal": 20, "rebajado": 25},
        {"normal": 20, "rebaja_hasta": "2026-12-31"},
    ],
)
def test_create_rechaza_precios_invalidos(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    precio: dict[str, object],
) -> None:
    client, _, _ = route_context

    response = client.post(
        "/skus/",
        json={"producto_color_id": str(uuid4()), "talla_id": str(uuid4()), "precio": precio},
    )

    assert response.status_code == 422


def test_patch_rechaza_cambiar_el_color_y_stock_null(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    assert client.patch(f"/skus/{uuid4()}", json={"producto_color_id": str(uuid4())}).status_code == 422
    assert client.patch(f"/skus/{uuid4()}", json={"stock": None}).status_code == 422
    assert client.patch(
        f"/skus/{uuid4()}",
        json={"stock": {"cantidad": 1, "minimo": 0, "actualizado": "2026-01-01"}},
    ).status_code == 422


def test_audit_y_delete(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    sku = _sku()

    with patch.object(SkuService, "get", new=AsyncMock(return_value=sku)):
        audit = client.get(f"/skus/{sku.id}/audit")
    with patch.object(SkuService, "delete", new=AsyncMock()) as service:
        deleted = client.delete(f"/skus/{sku.id}")

    assert audit.json()["is_deleted"] is False
    assert deleted.status_code == 204
    service.assert_awaited_once_with(db_session, sku.id, current_user.id)
