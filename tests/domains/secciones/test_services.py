from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.secciones.models import Seccion
from app.domains.secciones.repositories import SeccionRepository
from app.domains.secciones.schemas import SeccionCreate, SeccionUpdate
from app.domains.secciones.services import SeccionService
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _seccion(nombre: str = "Mujer") -> Seccion:
    return Seccion(nombre=nombre, slug=nombre.lower())


@pytest.mark.asyncio
async def test_create_genera_slug_y_asigna_auditoria() -> None:
    session = _session()
    actor_id = uuid4()

    with (
        patch.object(SeccionRepository, "get_active_by_slug", new=AsyncMock(return_value=None)),
        patch.object(SeccionRepository, "add") as add,
    ):
        seccion = await SeccionService.create(
            session,
            SeccionCreate(nombre="Niños y Bebés"),
            actor_id,
        )

    assert seccion.slug == "ninos-y-bebes"
    assert seccion.is_visible is True
    assert seccion.created_by == actor_id
    assert seccion.updated_by == actor_id
    add.assert_called_once_with(seccion)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_rechaza_slug_duplicado() -> None:
    session = _session()

    with patch.object(
        SeccionRepository,
        "get_active_by_slug",
        new=AsyncMock(return_value=_seccion()),
    ):
        with pytest.raises(AppException) as error:
            await SeccionService.create(session, SeccionCreate(nombre="MUJER"), uuid4())

    assert error.value.status_code == 409
    assert "nombre" in error.value.details
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_nombre_regenera_slug() -> None:
    seccion = _seccion()
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(SeccionService, "get", new=AsyncMock(return_value=seccion)),
        patch.object(
            SeccionRepository,
            "get_active_by_slug",
            new=AsyncMock(return_value=None),
        ) as get_by_slug,
    ):
        result = await SeccionService.update(
            session,
            seccion.id,
            SeccionUpdate(nombre="Hombre"),
            actor_id,
        )

    get_by_slug.assert_awaited_once_with("hombre", exclude_id=seccion.id)
    assert result.nombre == "Hombre"
    assert result.slug == "hombre"
    assert result.updated_by == actor_id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_sin_nombre_conserva_slug() -> None:
    seccion = _seccion()

    with (
        patch.object(SeccionService, "get", new=AsyncMock(return_value=seccion)),
        patch.object(SeccionRepository, "get_active_by_slug", new=AsyncMock()) as get_by_slug,
    ):
        result = await SeccionService.update(
            _session(),
            seccion.id,
            SeccionUpdate(is_visible=False),
            uuid4(),
        )

    get_by_slug.assert_not_awaited()
    assert result.slug == "mujer"
    assert result.is_visible is False


@pytest.mark.asyncio
async def test_update_vacio_no_hace_commit() -> None:
    seccion = _seccion()
    session = _session()

    with patch.object(SeccionService, "get", new=AsyncMock(return_value=seccion)):
        result = await SeccionService.update(session, seccion.id, SeccionUpdate(), uuid4())

    assert result is seccion
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_es_logico() -> None:
    seccion = _seccion()
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(SeccionService, "get", new=AsyncMock(return_value=seccion)),
        patch.object(
            SeccionRepository,
            "has_active_dependents",
            new=AsyncMock(return_value=False),
        ),
    ):
        await SeccionService.delete(session, seccion.id, actor_id)

    assert seccion.is_deleted is True
    assert seccion.deleted_by == actor_id
    assert seccion.deleted_at is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_rechaza_seccion_con_dependientes() -> None:
    seccion = _seccion()
    session = _session()

    with (
        patch.object(SeccionService, "get", new=AsyncMock(return_value=seccion)),
        patch.object(
            SeccionRepository,
            "has_active_dependents",
            new=AsyncMock(return_value=True),
        ),
    ):
        with pytest.raises(AppException) as error:
            await SeccionService.delete(session, seccion.id, uuid4())

    assert error.value.status_code == 409
    assert seccion.is_deleted is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await SeccionService.get(_session(), uuid4())

    assert error.value.status_code == 404
