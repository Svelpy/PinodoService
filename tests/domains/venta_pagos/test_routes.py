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
    [
        ("post", "/venta-pagos/"),
        ("get", "/venta-pagos/"),
        ("get", "/venta-pagos/{id}"),
        ("patch", "/venta-pagos/{id}"),
        ("put", "/venta-pagos/{id}"),
        ("delete", "/venta-pagos/{id}"),
    ],
)
def test_un_pago_no_se_crea_lista_edita_ni_elimina_por_su_cuenta(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    method: str,
    path: str,
) -> None:
    # Se registra y se consulta con su venta, y la devolución se hace anulando la venta.
    client, _, _ = route_context

    response = getattr(client, method)(path.format(id=uuid4()))

    assert response.status_code in {404, 405}
