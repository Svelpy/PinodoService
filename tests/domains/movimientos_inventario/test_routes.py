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
from app.domains.movimientos_inventario.routes import router
from app.domains.movimientos_inventario.schemas import MovimientoInventarioResponse, SkuCosto
from app.domains.movimientos_inventario.services import MovimientoInventarioService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import MotivoAjuste, Role, TipoMovimiento
from app.shared.schemas.pagination import PaginatedResponse


def _movimiento() -> MovimientoInventarioResponse:
    return MovimientoInventarioResponse.model_validate(
        MovimientoInventarioResponse.model_config["json_schema_extra"]["example"]
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


def test_list_pasa_filtros_y_responde_sku_y_origen(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    page = PaginatedResponse[MovimientoInventarioResponse](
        total=1, page=1, per_page=20, total_pages=1, data=[_movimiento()]
    )
    sku_id, ajuste_id, user_id = uuid4(), uuid4(), uuid4()

    with patch.object(MovimientoInventarioService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get(
            f"/movimientos-inventario/?sku_id={sku_id}&tipo=AJUSTE&motivo=MERMA&ajuste_id={ajuste_id}&user_id={user_id}&desde=2026-11-01"
        )

    assert response.status_code == 200
    [fila] = response.json()["data"]
    assert fila["sku"]["producto_nombre"] == "Camisa Oxford"
    assert fila["origen"] == {"tipo": "AJUSTE", "id": fila["origen"]["id"], "numero": 12, "motivo": "RECEPCION"}
    assert fila["usuario"]["rol"] == "ADMIN"
    assert set(fila["usuario"]) == {"id", "nombre", "apellidos", "rol"}
    assert service.await_args.args[0] is db_session
    kwargs = service.await_args.kwargs
    assert (kwargs["sku_id"], kwargs["tipo"], kwargs["motivo"], kwargs["ajuste_id"]) == (
        sku_id,
        TipoMovimiento.AJUSTE,
        MotivoAjuste.MERMA,
        ajuste_id,
    )
    assert kwargs["user_id"] == user_id


def test_get_responde_la_fila(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    movimiento = _movimiento()

    with patch.object(MovimientoInventarioService, "get", new=AsyncMock(return_value=movimiento)):
        response = client.get(f"/movimientos-inventario/{movimiento.id}")

    assert response.status_code == 200
    assert response.json()["saldo_valor"] == 432


def test_costos_no_se_confunde_con_un_id(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    costo = SkuCosto.model_validate(SkuCosto.model_config["json_schema_extra"]["example"])
    page = PaginatedResponse[SkuCosto](total=1, page=1, per_page=20, total_pages=1, data=[costo])

    with patch.object(MovimientoInventarioService, "list_costos", new=AsyncMock(return_value=page)) as service:
        response = client.get("/movimientos-inventario/costos?nombre=camisa")

    assert response.status_code == 200
    assert response.json()["data"][0]["valor"] == 150
    assert service.await_args.kwargs["nombre"] == "camisa"


@pytest.mark.parametrize("path", ["/movimientos-inventario/", "/movimientos-inventario/costos"])
def test_cajero_no_accede_al_kardex_ni_a_los_costos(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    path: str,
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.CAJERO

    assert client.get(path).status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/movimientos-inventario/"),
        ("post", "/movimientos-inventario/ajustes"),
        ("patch", "/movimientos-inventario/{id}"),
        ("put", "/movimientos-inventario/{id}"),
        ("delete", "/movimientos-inventario/{id}"),
        ("get", "/movimientos-inventario/{id}/audit"),
    ],
)
def test_el_kardex_es_de_solo_lectura(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    method: str,
    path: str,
) -> None:
    client, _, _ = route_context

    response = client.request(method, path.format(id=uuid4()), json={})

    assert response.status_code in (404, 405)
