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
from app.domains.config.models import Config
from app.domains.config.routes import router
from app.domains.config.services import ConfigService
from app.middlewares.exception_handlers import register_exception_handlers
from app.shared.enums import Role


def _config() -> Config:
    return Config(nombre_tienda="Tienda Moda")


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


def test_get_y_audit(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context
    config = _config()

    with patch.object(ConfigService, "get", new=AsyncMock(return_value=config)):
        normal = client.get("/config/")
        audit = client.get("/config/audit")

    assert normal.status_code == 200
    assert normal.json()["nombre_tienda"] == "Tienda Moda"
    assert "updated_by" not in normal.json()
    assert "updated_by" in audit.json()


def test_patch_rechaza_horario_invalido(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(ConfigService, "update", new=AsyncMock()) as service:
        invalido = client.patch("/config/", data={"horario": '{"lunes": "20:00-09:00"}'})
        no_json = client.patch("/config/", data={"horario": "lunes 9 a 20"})

    assert invalido.status_code == 422
    assert "horario" in invalido.json()["details"]
    assert no_json.status_code == 422
    assert no_json.json()["details"]["horario"] == "El valor debe ser un objeto JSON válido."
    service.assert_not_awaited()


def test_patch_form_envia_solo_campos_presentes_y_vacio_como_null(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context

    with patch.object(ConfigService, "update", new=AsyncMock(return_value=_config())) as service:
        response = client.patch(
            "/config/",
            data={
                "whatsapp": "",
                "horario": '{"Lunes": "09:00-20:00"}',
            },
        )

    assert response.status_code == 200
    args, kwargs = service.await_args
    assert args[0] is db_session
    assert args[1].model_dump(exclude_unset=True) == {
        "whatsapp": None,
        "horario": {"lunes": "09:00-20:00"},
    }
    assert args[2] == current_user.id
    assert kwargs["logo"] is None
    assert kwargs["favicon"] is None
    assert kwargs["eliminar_logo"] is False


def test_patch_form_ignora_en_mantenimiento(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(ConfigService, "update", new=AsyncMock(return_value=_config())) as service:
        response = client.patch(
            "/config/",
            data={"ciudad": "Santa Cruz", "en_mantenimiento": "true"},
        )

    assert response.status_code == 200
    assert service.await_args.args[1].model_dump(exclude_unset=True) == {"ciudad": "Santa Cruz"}


@pytest.mark.parametrize("rol", [Role.OWNER, Role.ADMIN, Role.CAJERO])
def test_patch_mantenimiento_rechaza_roles_que_no_son_superadmin(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    rol: Role,
) -> None:
    client, current_user, _ = route_context
    current_user.rol = rol

    with patch.object(ConfigService, "set_mantenimiento", new=AsyncMock()) as service:
        response = client.patch("/config/mantenimiento", json={"en_mantenimiento": True})

    assert response.status_code == 403
    service.assert_not_awaited()


def test_patch_mantenimiento_superadmin(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, current_user, db_session = route_context
    current_user.rol = Role.SUPERADMIN
    config = _config()
    config.en_mantenimiento = True

    with patch.object(
        ConfigService, "set_mantenimiento", new=AsyncMock(return_value=config)
    ) as service:
        response = client.patch("/config/mantenimiento", json={"en_mantenimiento": True})

    assert response.status_code == 200
    assert response.json()["en_mantenimiento"] is True
    args = service.await_args.args
    assert args[0] is db_session
    assert args[1].en_mantenimiento is True
    assert args[2] == current_user.id


@pytest.mark.parametrize(
    "body",
    [{}, {"en_mantenimiento": None}, {"en_mantenimiento": True, "ciudad": "X"}],
)
def test_patch_mantenimiento_rechaza_body_invalido(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
    body: dict[str, object],
) -> None:
    client, current_user, _ = route_context
    current_user.rol = Role.SUPERADMIN

    with patch.object(ConfigService, "set_mantenimiento", new=AsyncMock()) as service:
        response = client.patch("/config/mantenimiento", json=body)

    assert response.status_code == 422
    service.assert_not_awaited()


def test_patch_form_rechaza_vaciar_nombre_tienda(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(ConfigService, "update", new=AsyncMock()) as service:
        response = client.patch("/config/", data={"nombre_tienda": ""})

    assert response.status_code == 422
    assert "nombre_tienda" in response.json()["details"]
    service.assert_not_awaited()


def test_patch_form_pasa_los_archivos_al_service(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(ConfigService, "update", new=AsyncMock(return_value=_config())) as service:
        response = client.patch(
            "/config/",
            data={"eliminar_favicon": "true"},
            files={"logo": ("logo.png", b"png", "image/png")},
        )

    assert response.status_code == 200
    kwargs = service.await_args.kwargs
    assert kwargs["logo"].filename == "logo.png"
    assert kwargs["favicon"] is None
    assert kwargs["eliminar_favicon"] is True


def test_patch_form_ignora_selector_de_archivo_vacio(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    with patch.object(ConfigService, "update", new=AsyncMock(return_value=_config())) as service:
        response = client.patch(
            "/config/",
            files={"logo": ("", b"", "application/octet-stream")},
        )

    assert response.status_code == 200
    assert service.await_args.kwargs["logo"] is None


def test_no_hay_post_ni_delete(
    route_context: tuple[TestClient, CurrentUser, MagicMock],
) -> None:
    client, _, _ = route_context

    assert client.post("/config/", json={"nombre_tienda": "Otra"}).status_code == 405
    assert client.delete("/config/").status_code == 405
