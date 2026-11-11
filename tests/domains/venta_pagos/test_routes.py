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
from app.domains.venta_pagos.models import VentaPago
from app.domains.venta_pagos.routes import router
from app.domains.venta_pagos.services import VentaPagoService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import MetodoPago, Role
from app.shared.schemas.pagination import PaginatedResponse


def _pago() -> VentaPago:
    return VentaPago(
        venta_id=uuid4(),
        metodo=MetodoPago.QR,
        monto=Decimal("150.50"),
        referencia="0048213",
        created_by=uuid4(),
        updated_by=uuid4(),
    )


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
    pago = _pago()

    with patch.object(VentaPagoService, "create", new=AsyncMock(return_value=pago)) as service:
        response = client.post(
            "/venta-pagos/",
            json={"venta_id": str(pago.venta_id), "metodo": "QR", "monto": 150.5},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["monto"] == 150.5
    assert body["venta_id"] == str(pago.venta_id)
    assert "updated_by" not in body
    args = service.await_args.args
    assert args[0] is db_session
    assert args[1].monto == Decimal("150.5")
    assert args[2] == current_user


def test_create_rechaza_monto_cero(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(VentaPagoService, "create", new=AsyncMock()) as service:
        response = client.post("/venta-pagos/", json={"venta_id": str(uuid4()), "metodo": "QR", "monto": 0})

    assert response.status_code == 422
    service.assert_not_awaited()


def test_list_pasa_filtros(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    page = PaginatedResponse[VentaPago](total=1, page=1, per_page=20, total_pages=1, data=[_pago()])
    venta_id = uuid4()

    with patch.object(VentaPagoService, "list", new=AsyncMock(return_value=page)) as service:
        response = client.get(f"/venta-pagos/?venta_id={venta_id}&metodo=QR&desde=2026-11-01")

    assert response.status_code == 200
    assert response.json()["data"][0]["metodo"] == "QR"
    assert service.await_args.args[:2] == (db_session, current_user)
    kwargs = service.await_args.kwargs
    assert kwargs["venta_id"] == venta_id
    assert kwargs["metodo"] == MetodoPago.QR


def test_get_responde_detail(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    pago = _pago()

    with patch.object(VentaPagoService, "get", new=AsyncMock(return_value=pago)) as service:
        response = client.get(f"/venta-pagos/{pago.id}")

    assert response.status_code == 200
    service.assert_awaited_once_with(db_session, pago.id, current_user)


def test_cajero_no_tiene_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(VentaPagoService, "get", new=AsyncMock()) as service:
        response = client.get(f"/venta-pagos/{uuid4()}/audit")

    assert response.status_code == 403
    service.assert_not_awaited()


def test_superadmin_consulta_auditoria(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.SUPERADMIN
    pago = _pago()

    with patch.object(VentaPagoService, "get", new=AsyncMock(return_value=pago)):
        response = client.get(f"/venta-pagos/{pago.id}/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["updated_by"] == str(pago.updated_by)
    assert "is_deleted" not in body


def test_patch_solo_acepta_referencia(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    pago = _pago()

    with patch.object(VentaPagoService, "update", new=AsyncMock(return_value=pago)) as service:
        ok = client.patch(f"/venta-pagos/{pago.id}", json={"referencia": None})
        rechazado = client.patch(f"/venta-pagos/{pago.id}", json={"monto": 10})

    assert ok.status_code == 200
    assert rechazado.status_code == 422
    args = service.await_args.args
    assert args[:2] == (db_session, pago.id)
    assert args[2].model_dump(exclude_unset=True) == {"referencia": None}
    assert args[3] == current_user


def test_upload_comprobante_llama_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    pago = _pago()

    with patch.object(VentaPagoService, "upload_comprobante", new=AsyncMock(return_value=pago)) as service:
        response = client.post(
            f"/venta-pagos/{pago.id}/comprobante",
            files={"file": ("comprobante.jpg", b"\xff\xd8\xff", "image/jpeg")},
        )

    assert response.status_code == 200
    args = service.await_args.args
    assert args[:2] == (db_session, pago.id)
    assert args[3] == current_user


@pytest.mark.parametrize(
    ("method", "path"),
    [("delete", "/venta-pagos/{id}"), ("put", "/venta-pagos/{id}")],
)
def test_un_pago_no_se_elimina_ni_se_reemplaza(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    method: str,
    path: str,
) -> None:
    client, _, _ = route_context

    response = getattr(client, method)(path.format(id=uuid4()))

    assert response.status_code == 405
