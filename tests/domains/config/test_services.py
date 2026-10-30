from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.config.models import Config
from app.domains.config.repositories import ConfigRepository
from app.domains.config.schemas import ConfigUpdate
from app.domains.config.services import ConfigService
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
            ConfigUpdate(whatsapp=None, en_mantenimiento=True, horario={"Lunes": "09:00-20:00"}),
            actor_id,
        )

    assert result.whatsapp is None
    assert result.en_mantenimiento is True
    assert result.horario == {"lunes": "09:00-20:00"}
    assert result.updated_by == actor_id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_vacio_no_hace_commit() -> None:
    config = _config()
    session = _session()

    with patch.object(ConfigService, "get", new=AsyncMock(return_value=config)):
        result = await ConfigService.update(session, ConfigUpdate(), uuid4())

    assert result is config
    session.commit.assert_not_awaited()
