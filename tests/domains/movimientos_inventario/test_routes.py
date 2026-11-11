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
from app.domains.auth.dependencies import get_current_principal
from app.domains.auth.schemas import CurrentUser
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.movimientos_inventario.routes import router
from app.domains.movimientos_inventario.schemas import SkuCosto
from app.domains.movimientos_inventario.services import MovimientoInventarioService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role, TipoMovimiento
from app.shared.schemas.pagination import PaginatedResponse


def _movimiento() -> MovimientoInventario:
    movimiento = MovimientoInventario(
        sku_id=uuid4(),
        tipo=TipoMovimiento.INGRESO,
        cantidad=24,
        saldo=30,
        costo_unitario=Decimal("12.50"),
        costo_promedio=Decimal("12.10"),
        motivo="Lote de noviembre",
        created_by=uuid4(),
        updated_by=uuid4(),
    )
    movimiento.sku = None
    movimiento.venta = None
    return movimiento


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


def test_create_pasa_el_actor_y_responde_detail(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    movimiento = _movimiento()

    with patch.object(MovimientoInventarioService, "create", new=AsyncMock(return_value=movimiento)) as service:
        response = client.post(
            "/movimientos-inventario/",
            json={"sku_id": str(movimiento.sku_id), "tipo": "INGRESO", "cantidad": 24, "costo_unitario": 12.5},
        )

    assert response.status_code == 201
    body = response.json()
    assert (body["costo_unitario"], body["costo_promedio"], body["saldo"]) == (12.5, 12.1, 30)
    assert body["sku"] is None and body["venta"] is None
    args = service.await_args.args
    assert args[0] is db_session
    assert args[1].costo_unitario == Decimal("12.5")
    assert args[2] == current_user.id


def test_create_no_acepta_movimientos_de_venta(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(MovimientoInventarioService, "create", new=AsyncMock()) as service:
        response = client.post(
            "/movimientos-inventario/",
            json={"sku_id": str(uuid4()), "tipo": "VENTA", "cantidad": -1},
        )

    assert response.status_code == 422
    service.assert_not_awaited()


def test_list_pasa_filtros(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context
    page = PaginatedResponse[MovimientoInventario](
        total=1, page=1, per_page=20, total_pages=1, data=[_movimiento()]
    )
    sku_id = uuid4()

    with patch.object(MovimientoInventarioService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get(f"/movimientos-inventario/?sku_id={sku_id}&tipo=AJUSTE&desde=2026-11-01")

    assert response.status_code == 200
    assert response.json()["data"][0]["tipo"] == "INGRESO"
    assert service.await_args.args[0] is db_session
    kwargs = service.await_args.kwargs
    assert (kwargs["sku_id"], kwargs["tipo"]) == (sku_id, TipoMovimiento.AJUSTE)


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


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/movimientos-inventario/"),
        ("get", "/movimientos-inventario/costos"),
        ("post", "/movimientos-inventario/"),
    ],
)
def test_cajero_no_accede_al_kardex_ni_a_los_costos(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    method: str,
    path: str,
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.CAJERO

    response = client.request(method, path, json={})

    assert response.status_code == 403


def test_admin_no_tiene_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    assert client.get(f"/movimientos-inventario/{uuid4()}/audit").status_code == 403


def test_superadmin_consulta_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.SUPERADMIN
    movimiento = _movimiento()

    with patch.object(MovimientoInventarioService, "get", new=AsyncMock(return_value=movimiento)):
        response = client.get(f"/movimientos-inventario/{movimiento.id}/audit")

    assert response.status_code == 200
    assert response.json()["updated_by"] == str(movimiento.updated_by)


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_un_movimiento_no_se_edita_ni_se_elimina(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    method: str,
) -> None:
    client, _, _ = route_context

    assert getattr(client, method)(f"/movimientos-inventario/{uuid4()}").status_code == 405
