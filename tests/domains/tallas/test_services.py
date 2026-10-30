from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.tallas.models import Talla
from app.domains.tallas.repositories import TallaRepository
from app.domains.tallas.schemas import TallaCreate, TallaUpdate
from app.domains.tallas.services import TallaService
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _talla() -> Talla:
    return Talla(etiqueta="M")


@pytest.mark.asyncio
async def test_create_asigna_auditoria() -> None:
    session = _session()
    actor_id = uuid4()

    with (
        patch.object(TallaRepository, "get_active_by_etiqueta", new=AsyncMock(return_value=None)),
        patch.object(TallaRepository, "add") as add,
    ):
        talla = await TallaService.create(session, TallaCreate(etiqueta=" XL "), actor_id)

    assert talla.etiqueta == "XL"
    assert talla.created_by == actor_id
    assert talla.updated_by == actor_id
    add.assert_called_once_with(talla)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_rechaza_etiqueta_duplicada() -> None:
    session = _session()

    with patch.object(
        TallaRepository,
        "get_active_by_etiqueta",
        new=AsyncMock(return_value=_talla()),
    ):
        with pytest.raises(AppException) as error:
            await TallaService.create(session, TallaCreate(etiqueta="m"), uuid4())

    assert error.value.status_code == 409
    assert "etiqueta" in error.value.details
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_valida_etiqueta_excluyendo_la_propia() -> None:
    talla = _talla()
    actor_id = uuid4()

    with (
        patch.object(TallaService, "get", new=AsyncMock(return_value=talla)),
        patch.object(
            TallaRepository,
            "get_active_by_etiqueta",
            new=AsyncMock(return_value=None),
        ) as get_by_etiqueta,
    ):
        result = await TallaService.update(
            _session(),
            talla.id,
            TallaUpdate(etiqueta="L"),
            actor_id,
        )

    get_by_etiqueta.assert_awaited_once_with("L", exclude_id=talla.id)
    assert result.etiqueta == "L"
    assert result.updated_by == actor_id


@pytest.mark.asyncio
async def test_update_vacio_no_hace_commit() -> None:
    talla = _talla()
    session = _session()

    with patch.object(TallaService, "get", new=AsyncMock(return_value=talla)):
        result = await TallaService.update(session, talla.id, TallaUpdate(), uuid4())

    assert result is talla
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_es_logico() -> None:
    talla = _talla()
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(TallaService, "get", new=AsyncMock(return_value=talla)),
        patch.object(
            TallaRepository,
            "has_active_dependents",
            new=AsyncMock(return_value=False),
        ),
    ):
        await TallaService.delete(session, talla.id, actor_id)

    assert talla.is_deleted is True
    assert talla.deleted_by == actor_id
    assert talla.deleted_at is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_rechaza_talla_en_uso() -> None:
    talla = _talla()
    session = _session()

    with (
        patch.object(TallaService, "get", new=AsyncMock(return_value=talla)),
        patch.object(
            TallaRepository,
            "has_active_dependents",
            new=AsyncMock(return_value=True),
        ),
    ):
        with pytest.raises(AppException) as error:
            await TallaService.delete(session, talla.id, uuid4())

    assert error.value.status_code == 409
    assert talla.is_deleted is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(TallaRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await TallaService.get(_session(), uuid4())

    assert error.value.status_code == 404
