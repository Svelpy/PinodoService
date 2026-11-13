from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.config.models import Config
from app.domains.config.repositories import ConfigRepository
from app.domains.config.schemas import ConfigMantenimientoUpdate, ConfigUpdate
from app.domains.config.services import ConfigService
from app.integrations.cloudinary import CloudinaryService
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _config() -> Config:
    return Config(nombre_tienda="Tienda Moda", whatsapp="+59171234567")


@pytest.mark.asyncio
async def test_get_sin_configuracion_responde_404() -> None:
    with patch.object(ConfigRepository, "get", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await ConfigService.get(_session())

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_update_aplica_cambios_y_null_explicito() -> None:
    config = _config()
    actor_id = uuid4()
    session = _session()

    with patch.object(ConfigService, "get", new=AsyncMock(return_value=config)):
        result = await ConfigService.update(
            session,
            ConfigUpdate(whatsapp=None, horario={"Lunes": "09:00-20:00"}),
            actor_id,
            MagicMock(),
        )

    assert result.whatsapp is None
    assert result.horario == {"lunes": "09:00-20:00"}
    assert result.updated_by == actor_id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_mantenimiento_lo_activa_y_audita() -> None:
    config = _config()
    actor_id = uuid4()
    session = _session()

    with patch.object(ConfigService, "get", new=AsyncMock(return_value=config)) as get:
        result = await ConfigService.set_mantenimiento(
            session, ConfigMantenimientoUpdate(en_mantenimiento=True), actor_id
        )

    assert result.en_mantenimiento is True
    assert result.updated_by == actor_id
    assert get.await_args.kwargs == {"for_update": True}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_mantenimiento_sin_cambio_no_hace_commit() -> None:
    config = _config()
    config.en_mantenimiento = False
    session = _session()

    with patch.object(ConfigService, "get", new=AsyncMock(return_value=config)):
        result = await ConfigService.set_mantenimiento(
            session, ConfigMantenimientoUpdate(en_mantenimiento=False), uuid4()
        )

    assert result is config
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_vacio_no_hace_commit() -> None:
    config = _config()
    session = _session()

    with patch.object(ConfigService, "get", new=AsyncMock(return_value=config)):
        result = await ConfigService.update(session, ConfigUpdate(), uuid4(), MagicMock())

    assert result is config
    session.commit.assert_not_awaited()


OLD_LOGO = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/config/viejo.png"
NEW_LOGO = "https://res.cloudinary.com/demo/image/upload/v2/pinodo/config/nuevo.png"


@pytest.mark.asyncio
async def test_update_sube_logo_y_borra_el_anterior_tras_el_commit() -> None:
    config = _config()
    config.logo_url = OLD_LOGO
    session = _session()
    upload = AsyncMock(return_value={"url": NEW_LOGO, "public_id": "pinodo/config/nuevo"})

    with (
        patch.object(ConfigService, "get", new=AsyncMock(return_value=config)),
        patch.object(CloudinaryService, "upload_image", new=upload),
        patch.object(CloudinaryService, "safe_delete_image", new=AsyncMock()) as delete,
    ):
        result = await ConfigService.update(
            session, ConfigUpdate(), uuid4(), MagicMock(), logo=MagicMock()
        )

    assert result.logo_url == NEW_LOGO
    assert upload.await_args.args[1] == "config"
    session.commit.assert_awaited_once()
    delete.assert_awaited_once_with(OLD_LOGO)


@pytest.mark.asyncio
async def test_update_borra_el_archivo_subido_si_falla_el_commit() -> None:
    config = _config()
    config.logo_url = OLD_LOGO
    session = _session()
    session.commit = AsyncMock(side_effect=RuntimeError("db caída"))

    with (
        patch.object(ConfigService, "get", new=AsyncMock(return_value=config)),
        patch.object(
            CloudinaryService,
            "upload_image",
            new=AsyncMock(return_value={"url": NEW_LOGO, "public_id": "x"}),
        ),
        patch.object(CloudinaryService, "safe_delete_image", new=AsyncMock()) as delete,
    ):
        with pytest.raises(RuntimeError):
            await ConfigService.update(
                session, ConfigUpdate(), uuid4(), MagicMock(), logo=MagicMock()
            )

    delete.assert_awaited_once_with(NEW_LOGO)


@pytest.mark.asyncio
async def test_update_eliminar_favicon_lo_quita_y_borra_el_archivo() -> None:
    config = _config()
    config.favicon_url = OLD_LOGO
    session = _session()

    with (
        patch.object(ConfigService, "get", new=AsyncMock(return_value=config)),
        patch.object(CloudinaryService, "upload_image", new=AsyncMock()) as upload,
        patch.object(CloudinaryService, "safe_delete_image", new=AsyncMock()) as delete,
    ):
        result = await ConfigService.update(
            session, ConfigUpdate(), uuid4(), MagicMock(), eliminar_favicon=True
        )

    assert result.favicon_url is None
    upload.assert_not_awaited()
    delete.assert_awaited_once_with(OLD_LOGO)


@pytest.mark.asyncio
async def test_update_rechaza_subir_y_eliminar_el_logo_a_la_vez() -> None:
    with patch.object(CloudinaryService, "upload_image", new=AsyncMock()) as upload:
        with pytest.raises(AppException) as error:
            await ConfigService.update(
                _session(),
                ConfigUpdate(),
                uuid4(),
                MagicMock(),
                logo=MagicMock(),
                eliminar_logo=True,
            )

    assert error.value.status_code == 422
    upload.assert_not_awaited()
