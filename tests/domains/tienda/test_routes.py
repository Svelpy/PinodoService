from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.domains.config.models import Config
from app.domains.config.services import ConfigService
from app.domains.tienda.routes import router
from app.domains.tienda.services import TiendaService
from app.middlewares.exception_handlers import register_exception_handlers
from app.middlewares.limiter import limiter, register_rate_limiter
from app.shared.enums import OrdenTienda
from app.shared.schemas.pagination import PaginatedResponse


VACIO = PaginatedResponse(total=0, page=1, per_page=24, total_pages=0, data=[])


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app, get_settings())
    register_rate_limiter(app)
    app.include_router(router)

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield MagicMock(spec=AsyncSession)

    app.dependency_overrides[get_db] = override_db
    limiter.reset()

    with TestClient(app) as test_client:
        yield test_client
    limiter.reset()


def _config(en_mantenimiento: bool) -> Config:
    return Config(nombre_tienda="Tienda Moda", en_mantenimiento=en_mantenimiento)


def test_config_es_publica_y_responde_en_mantenimiento(client: TestClient) -> None:
    with patch.object(ConfigService, "get", new=AsyncMock(return_value=_config(True))):
        response = client.get("/tienda/config")

    assert response.status_code == 200
    assert response.json()["en_mantenimiento"] is True
    assert "updated_by" not in response.json()
    assert "updated_at" not in response.json()


@pytest.mark.parametrize(
    "path",
    ["/tienda/navegacion", "/tienda/productos", "/tienda/productos/filtros", f"/tienda/productos/{uuid4()}"],
)
def test_en_mantenimiento_todo_menos_config_responde_503(client: TestClient, path: str) -> None:
    with (
        patch.object(ConfigService, "get", new=AsyncMock(return_value=_config(True))),
        patch.object(TiendaService, "navegacion", new=AsyncMock()) as navegacion,
        patch.object(TiendaService, "listar_productos", new=AsyncMock()) as listar,
        patch.object(TiendaService, "filtros", new=AsyncMock()) as filtros,
        patch.object(TiendaService, "get_producto", new=AsyncMock()) as get,
    ):
        response = client.get(path)

    assert response.status_code == 503
    assert response.json()["code"] == "MAINTENANCE"
    for service in (navegacion, listar, filtros, get):
        service.assert_not_awaited()


def test_listado_pasa_filtros_repetidos(client: TestClient) -> None:
    color_a, color_b, talla = uuid4(), uuid4(), uuid4()

    with (
        patch.object(ConfigService, "get", new=AsyncMock(return_value=_config(False))),
        patch.object(TiendaService, "listar_productos", new=AsyncMock(return_value=VACIO)) as listar,
    ):
        response = client.get(
            "/tienda/productos",
            params=[
                ("color_id", str(color_a)),
                ("color_id", str(color_b)),
                ("talla_id", str(talla)),
                ("orden", "PRECIO_DESC"),
                ("disponible", "true"),
                ("precio_max", "99.90"),
            ],
        )

    assert response.status_code == 200
    kwargs = listar.await_args.kwargs
    assert kwargs["color_ids"] == [color_a, color_b]
    assert kwargs["talla_ids"] == [talla]
    assert kwargs["orden"] == OrdenTienda.PRECIO_DESC
    assert kwargs["disponible"] is True
    assert kwargs["per_page"] == 24
    assert str(kwargs["precio_max"]) == "99.90"


@pytest.mark.parametrize(
    "params",
    [
        {"orden": "BARATO"},
        {"per_page": "61"},
        {"precio_min": "-1"},
        {"precio_min": "1.999"},
        {"color_id": "no-es-uuid"},
    ],
)
def test_listado_rechaza_parametros_invalidos(client: TestClient, params: dict[str, str]) -> None:
    with (
        patch.object(ConfigService, "get", new=AsyncMock(return_value=_config(False))),
        patch.object(TiendaService, "listar_productos", new=AsyncMock()) as listar,
    ):
        response = client.get("/tienda/productos", params=params)

    assert response.status_code == 422
    listar.assert_not_awaited()


def test_ficha_rechaza_id_no_uuid(client: TestClient) -> None:
    with patch.object(ConfigService, "get", new=AsyncMock(return_value=_config(False))):
        response = client.get("/tienda/productos/vestido-midi")

    assert response.status_code == 422


def test_rate_limit_responde_429(client: TestClient) -> None:
    with patch.object(ConfigService, "get", new=AsyncMock(return_value=_config(False))):
        statuses = [client.get("/tienda/config").status_code for _ in range(121)]

    assert statuses[:120] == [200] * 120
    assert statuses[120] == 429
