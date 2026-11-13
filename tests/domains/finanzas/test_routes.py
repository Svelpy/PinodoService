from collections.abc import AsyncGenerator, Iterator
from datetime import date
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
from app.domains.finanzas.routes import router
from app.domains.finanzas.schemas import ReporteRentabilidad, ReporteVentas
from app.domains.finanzas.services import FinanzasService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role
from app.shared.services.excel import XLSX_MEDIA_TYPE


@pytest.fixture
def route_context() -> Iterator[tuple[TestClient, CurrentUser, MagicMock]]:
    app = FastAPI()
    register_exception_handlers(app, get_settings())
    app.include_router(router)

    current_user = CurrentUser(id=uuid4(), rol=Role.OWNER)
    db_session = MagicMock(spec=AsyncSession)

    async def override_principal() -> CurrentUser:
        return current_user

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_current_principal] = override_principal
    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        yield client, current_user, db_session


def _ejemplo(schema: type) -> object:
    return schema.model_validate(schema.model_config["json_schema_extra"]["example"])


def test_ventas_pasa_las_fechas_y_responde_json(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, db_session = route_context

    with patch.object(FinanzasService, "ventas", new=AsyncMock(return_value=_ejemplo(ReporteVentas))) as service:
        response = client.get("/finanzas/ventas", params={"desde": "2026-10-01", "hasta": "2026-10-31"})

    assert response.status_code == 200
    body = response.json()
    assert body["resumen"]["total_vendido"] == 26296
    assert body["detalle"][0]["metodos_pago"] == ["EFECTIVO", "QR"]
    assert service.await_args.args[0] is db_session
    assert service.await_args.kwargs == {"desde": date(2026, 10, 1), "hasta": date(2026, 10, 31)}


def test_rentabilidad_sin_filtros(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(
        FinanzasService, "rentabilidad", new=AsyncMock(return_value=_ejemplo(ReporteRentabilidad))
    ) as service:
        response = client.get("/finanzas/rentabilidad")

    assert response.status_code == 200
    assert response.json()["resumen"]["margen_bruto"] == 12798
    assert service.await_args.kwargs == {"desde": None, "hasta": None}


@pytest.mark.parametrize(
    ("ruta", "metodo"),
    [("/finanzas/ventas/excel", "ventas_excel"), ("/finanzas/rentabilidad/excel", "rentabilidad_excel")],
)
def test_excel_se_descarga_como_archivo(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    ruta: str,
    metodo: str,
) -> None:
    client, current_user, db_session = route_context
    archivo = ("reporte_2026-10-01_2026-10-31.xlsx", b"PK\x03\x04contenido")

    with patch.object(FinanzasService, metodo, new=AsyncMock(return_value=archivo)) as service:
        response = client.get(ruta, params={"desde": "2026-10-01"})

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    assert response.headers["content-disposition"] == 'attachment; filename="reporte_2026-10-01_2026-10-31.xlsx"'
    assert response.content == archivo[1]
    assert service.await_args.args == (db_session, service.await_args.args[1], current_user)
    assert service.await_args.kwargs == {"desde": date(2026, 10, 1), "hasta": None}


@pytest.mark.parametrize(
    "ruta",
    ["/finanzas/ventas", "/finanzas/ventas/excel", "/finanzas/rentabilidad", "/finanzas/rentabilidad/excel"],
)
def test_el_cajero_no_ve_los_reportes(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    ruta: str,
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.CAJERO

    assert client.get(ruta).status_code == 403


def test_fecha_invalida_responde_422(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    assert client.get("/finanzas/ventas", params={"desde": "31-10-2026"}).status_code == 422
