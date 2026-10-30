from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.colores.models import Color
from app.domains.colores.repositories import ColorRepository
from app.domains.colores.schemas import ColorCreate, ColorUpdate
from app.domains.colores.services import ColorService
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _color() -> Color:
    return Color(nombre="Azul marino", slug="azul-marino", codigo_hex="#1E3A8A")


@pytest.mark.asyncio
async def test_create_genera_slug_normaliza_hex_y_asigna_auditoria() -> None:
    session = _session()
    actor_id = uuid4()

    with (
        patch.object(ColorRepository, "get_active_by_slug", new=AsyncMock(return_value=None)),
        patch.object(ColorRepository, "add") as add,
    ):
        color = await ColorService.create(
            session,
            ColorCreate(nombre="Azúl  Marino", codigo_hex="1e3a8a"),
            actor_id,
        )

    assert color.slug == "azul-marino"
    assert color.codigo_hex == "#1E3A8A"
    assert color.created_by == actor_id
    assert color.updated_by == actor_id
    add.assert_called_once_with(color)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_rechaza_slug_duplicado() -> None:
    session = _session()

    with patch.object(
        ColorRepository,
        "get_active_by_slug",
        new=AsyncMock(return_value=_color()),
    ):
        with pytest.raises(AppException) as error:
            await ColorService.create(
                session,
                ColorCreate(nombre="AZUL MARINO", codigo_hex="#1E3A8A"),
                uuid4(),
            )

    assert error.value.status_code == 409
    assert "nombre" in error.value.details
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_nombre_regenera_slug() -> None:
    color = _color()
    actor_id = uuid4()

    with (
        patch.object(ColorService, "get", new=AsyncMock(return_value=color)),
        patch.object(
            ColorRepository,
            "get_active_by_slug",
            new=AsyncMock(return_value=None),
        ) as get_by_slug,
    ):
        result = await ColorService.update(
            _session(),
            color.id,
            ColorUpdate(nombre="Marino"),
            actor_id,
        )

    get_by_slug.assert_awaited_once_with("marino", exclude_id=color.id)
    assert result.nombre == "Marino"
    assert result.slug == "marino"
    assert result.updated_by == actor_id


@pytest.mark.asyncio
async def test_update_solo_hex_conserva_slug() -> None:
    color = _color()

    with (
        patch.object(ColorService, "get", new=AsyncMock(return_value=color)),
        patch.object(ColorRepository, "get_active_by_slug", new=AsyncMock()) as get_by_slug,
    ):
        result = await ColorService.update(
            _session(),
            color.id,
            ColorUpdate(codigo_hex="#172554"),
            uuid4(),
        )

    get_by_slug.assert_not_awaited()
    assert result.slug == "azul-marino"
    assert result.codigo_hex == "#172554"


@pytest.mark.asyncio
async def test_delete_es_logico() -> None:
    color = _color()
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(ColorService, "get", new=AsyncMock(return_value=color)),
        patch.object(
            ColorRepository,
            "has_active_dependents",
            new=AsyncMock(return_value=False),
        ),
    ):
        await ColorService.delete(session, color.id, actor_id)

    assert color.is_deleted is True
    assert color.deleted_by == actor_id
    assert color.deleted_at is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_rechaza_color_en_uso() -> None:
    color = _color()
    session = _session()

    with (
        patch.object(ColorService, "get", new=AsyncMock(return_value=color)),
        patch.object(
            ColorRepository,
            "has_active_dependents",
            new=AsyncMock(return_value=True),
        ),
    ):
        with pytest.raises(AppException) as error:
            await ColorService.delete(session, color.id, uuid4())

    assert error.value.status_code == 409
    assert color.is_deleted is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(ColorRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await ColorService.get(_session(), uuid4())

    assert error.value.status_code == 404
