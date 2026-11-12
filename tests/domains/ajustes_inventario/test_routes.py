from collections.abc import AsyncGenerator, Iterator
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.domains.ajustes_inventario.routes import router
from app.domains.ajustes_inventario.schemas import (
    AjusteInventarioDetail,
    AjusteInventarioResponse,
    AjusteInventarioResultado,
)
from app.domains.ajustes_inventario.services import AjusteInventarioService
from app.domains.auth.dependencies import get_current_principal
from app.domains.auth.schemas import CurrentUser
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import MotivoAjuste, Role
from app.shared.schemas.pagination import PaginatedResponse


def _example(schema: type) -> object:
    return schema.model_validate(schema.model_config["json_schema_extra"]["example"])


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


def test_create_pasa_el_actor_y_responde_el_documento(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context

    with patch.object(
        AjusteInventarioService, "create", new=AsyncMock(return_value=_example(AjusteInventarioResultado))
    ) as service:
        response = client.post(
            "/ajustes-inventario/",
            json={"motivo": "RECEPCION", "items": [{"sku_id": str(uuid4()), "cantidad": 24, "costo_unitario": 12.5}]},
        )

    assert response.status_code == 201
    body = response.json()
    assert (body["ajuste"]["numero"], body["ajuste"]["valor"]) == (12, 450)
    assert body["ajuste"]["movimientos"][0]["origen"]["numero"] == 12
    args = service.await_args.args
    assert args[0] is db_session
    assert args[1].items[0].costo_unitario == Decimal("12.5")
    assert args[2] == current_user.id


@pytest.mark.parametrize(
    "body",
    [
        {"motivo": "RECEPCION", "items": [{"sku_id": str(uuid4()), "cantidad": 1}]},
        {"motivo": "INICIAL", "items": [{"sku_id": str(uuid4()), "cantidad": 1, "costo_unitario": 1}]},
    ],
)
def test_create_invalido_no_llega_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    body: dict[str, object],
) -> None:
    client, _, _ = route_context

    with patch.object(AjusteInventarioService, "create", new=AsyncMock()) as service:
        response = client.post("/ajustes-inventario/", json=body)

    assert response.status_code == 422
    service.assert_not_awaited()


def test_list_pasa_filtros_y_no_trae_lineas(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    page = PaginatedResponse[AjusteInventarioResponse](
        total=1, page=1, per_page=20, total_pages=1, data=[_example(AjusteInventarioResponse)]
    )

    with patch.object(AjusteInventarioService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get("/ajustes-inventario/?motivo=MERMA&desde=2026-11-01")

    assert response.status_code == 200
    assert "movimientos" not in response.json()["data"][0]
    assert service.await_args.kwargs["motivo"] == MotivoAjuste.MERMA


def test_get_responde_el_documento_con_sus_lineas(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    detail = _example(AjusteInventarioDetail)

    with patch.object(AjusteInventarioService, "get", new=AsyncMock(return_value=detail)):
        response = client.get(f"/ajustes-inventario/{detail.id}")

    assert response.status_code == 200
    assert len(response.json()["movimientos"]) == 1


@pytest.mark.parametrize(("method", "path"), [("get", "/ajustes-inventario/"), ("post", "/ajustes-inventario/")])
def test_cajero_no_accede(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    method: str,
    path: str,
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.CAJERO

    assert client.request(method, path, json={}).status_code == 403


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_un_ajuste_no_se_edita_ni_se_elimina(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    method: str,
) -> None:
    client, _, _ = route_context

    assert client.request(method, f"/ajustes-inventario/{uuid4()}").status_code == 405
