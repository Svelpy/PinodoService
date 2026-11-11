from collections.abc import AsyncGenerator, Iterator
from datetime import date
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
from app.domains.venta_items.models import VentaItem
from app.domains.ventas.models import Venta
from app.domains.ventas.routes import router
from app.domains.ventas.services import VentaService
from app.middlewares.exception_handlers import register_exception_handlers
from app.domains.ventas.schemas import VentaPaginatedResponse, VentaResumen, VentaResumenConfirmada
from app.shared.enums import EstadoVenta, MetodoPago, Role


def _venta() -> Venta:
    venta = Venta(
        numero=7,
        subtotal=Decimal("39.90"),
        descuento=Decimal("0"),
        total=Decimal("39.90"),
        created_by=uuid4(),
    )
    venta.items = [
        VentaItem(
            venta_id=venta.id,
            sku_id=uuid4(),
            cantidad=2,
            precio_normal=Decimal("29.95"),
            precio_unitario=Decimal("19.95"),
            descuento_unitario=Decimal("0"),
            subtotal=Decimal("39.90"),
            producto_nombre="Camisa Oxford",
            color_nombre="Azul marino",
            talla_etiqueta="M",
        )
    ]
    return venta


@pytest.fixture
def route_context() -> Iterator[tuple[TestClient, CurrentUser, MagicMock]]:
    app = FastAPI()
    register_exception_handlers(app, get_settings())
    app.include_router(router)

    current_user = CurrentUser(id=uuid4(), rol=Role.CAJERO)
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
    venta = _venta()

    with patch.object(VentaService, "create", new=AsyncMock(return_value=venta)) as service:
        response = client.post(
            "/ventas/",
            json={"estado": "CONFIRMADA", "canal": "TIENDA", "items": [{"sku_id": str(uuid4()), "cantidad": 2}]},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["numero"] == 7
    assert body["total"] == 39.9
    assert body["items"][0]["producto_nombre"] == "Camisa Oxford"
    assert body["items"][0]["precio_unitario"] == 19.95
    args = service.await_args.args
    assert args[0] is db_session
    assert args[1].estado == EstadoVenta.CONFIRMADA
    assert args[2] == current_user


def test_create_rechaza_cuerpo_invalido(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(VentaService, "create", new=AsyncMock()) as service:
        response = client.post("/ventas/", json={"estado": "CANCELADA", "items": []})

    assert response.status_code == 422
    service.assert_not_awaited()


def test_list_pasa_filtros_y_actor(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    cero = Decimal("0")
    page = VentaPaginatedResponse(
        total=1,
        page=1,
        per_page=20,
        total_pages=1,
        data=[_venta()],
        resumen=VentaResumen(
            confirmada=VentaResumenConfirmada(efectivo=cero, qr=cero, transferencia=cero, total=cero),
            pendiente=Decimal("39.90"),
            pendiente_pagado=cero,
            cancelada=cero,
        ),
    )

    with patch.object(VentaService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get("/ventas/?estado=PENDIENTE&metodo_pago=QR&desde=2026-11-01&hasta=2026-11-07")

    assert response.status_code == 200
    body = response.json()
    assert "items" not in body["data"][0]
    assert "pagos" not in body["data"][0]
    assert body["data"][0]["total_pagado"] == 0
    assert body["resumen"]["pendiente"] == 39.9
    assert service.await_args.args[:2] == (db_session, current_user)
    kwargs = service.await_args.kwargs
    assert kwargs["estado"] == EstadoVenta.PENDIENTE
    assert kwargs["metodo_pago"] == MetodoPago.QR
    assert kwargs["desde"] == date(2026, 11, 1)
    assert kwargs["hasta"] == date(2026, 11, 7)


def test_get_carga_el_detail_con_el_actor(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    venta = _venta()

    with patch.object(VentaService, "get", new=AsyncMock(return_value=venta)) as service:
        response = client.get(f"/ventas/{venta.id}")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["pagos"] == []
    service.assert_awaited_once_with(db_session, venta.id, current_user, load_detail=True)


def test_cajero_no_tiene_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(VentaService, "get", new=AsyncMock()) as service:
        response = client.get(f"/ventas/{uuid4()}/audit")

    assert response.status_code == 403
    service.assert_not_awaited()


def test_superadmin_consulta_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.SUPERADMIN
    venta = _venta()
    venta.updated_by = uuid4()

    with patch.object(VentaService, "get", new=AsyncMock(return_value=venta)):
        response = client.get(f"/ventas/{venta.id}/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["updated_by"] == str(venta.updated_by)
    assert "items" not in body
    assert "is_deleted" not in body


def test_put_items_llama_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    venta = _venta()

    with patch.object(VentaService, "replace_items", new=AsyncMock(return_value=venta)) as service:
        response = client.put(
            f"/ventas/{venta.id}/items",
            json={"canal": "TIENDA", "items": [{"sku_id": str(uuid4()), "cantidad": 1}]},
        )

    assert response.status_code == 200
    args = service.await_args.args
    assert args[:2] == (db_session, venta.id)
    assert args[2].model_dump(exclude_unset=True).keys() == {"canal", "items"}
    assert args[3] == current_user


def test_patch_estado_llama_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    venta = _venta()

    with patch.object(VentaService, "change_estado", new=AsyncMock(return_value=venta)) as service:
        response = client.patch(f"/ventas/{venta.id}/estado", json={"estado": "CONFIRMADA"})

    assert response.status_code == 200
    args = service.await_args.args
    assert args[:2] == (db_session, venta.id)
    assert args[2].estado == EstadoVenta.CONFIRMADA
    assert args[3] == current_user


def test_patch_estado_rechaza_pendiente(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    response = client.patch(f"/ventas/{uuid4()}/estado", json={"estado": "PENDIENTE"})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [("patch", "/ventas/{id}"), ("delete", "/ventas/{id}")],
)
def test_no_existen_patch_ni_delete(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    method: str,
    path: str,
) -> None:
    client, _, _ = route_context

    response = getattr(client, method)(path.format(id=uuid4()))

    assert response.status_code == 405
