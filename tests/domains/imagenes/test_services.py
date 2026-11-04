from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.domains.imagenes.models import Imagen
from app.domains.imagenes.repositories import ImagenRepository
from app.domains.imagenes.schemas import ImagenCreate, ImagenUpdate
from app.domains.imagenes.services import ImagenService
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.integrations.cloudinary import CloudinaryService
from app.shared.enums import TipoImagen
from app.shared.errors.exceptions import AppException


URL = "https://res.cloudinary.com/demo/image/upload/v1/tienda/productos/foto.jpg"


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _producto_color() -> ProductoColor:
    return ProductoColor(producto_id=uuid4(), color_id=uuid4())


def _imagen() -> Imagen:
    return Imagen(producto_color_id=uuid4(), url=URL)


SUBIDA = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/imagenes/foto.jpg"


def _settings() -> MagicMock:
    return MagicMock(CLOUDINARY_CLOUD_NAME="demo", CLOUDINARY_FOLDER_NAME="pinodo")


@pytest.mark.asyncio
async def test_create_asocia_la_subida_y_la_mueve_a_la_carpeta_del_color() -> None:
    producto_color = _producto_color()
    session = _session()
    actor_id = uuid4()
    settings = _settings()

    with (
        patch.object(ProductoColorRepository, "get_by_id", new=AsyncMock(return_value=producto_color)),
        patch.object(ImagenRepository, "get_active_by_url", new=AsyncMock(return_value=None)),
        patch.object(ImagenRepository, "add") as add,
        patch.object(CloudinaryService, "upload_image", new=AsyncMock()) as upload,
        patch.object(CloudinaryService, "confirm_pending_uploads", new=AsyncMock()) as confirm,
    ):
        imagen = await ImagenService.create(
            session,
            ImagenCreate(producto_color_id=producto_color.id, url=SUBIDA, tipo=TipoImagen.PRENDA),
            actor_id,
            settings,
        )

    assert (imagen.url, imagen.tipo, imagen.created_by) == (SUBIDA, TipoImagen.PRENDA, actor_id)
    add.assert_called_once_with(imagen)
    session.commit.assert_awaited_once()
    upload.assert_not_awaited()  # ya no sube archivos
    confirm.assert_awaited_once_with(
        {SUBIDA: f"productos/{producto_color.producto_id}/{producto_color.id}"}, settings
    )


@pytest.mark.asyncio
async def test_create_rechaza_color_inexistente() -> None:
    with patch.object(ProductoColorRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await ImagenService.create(
                _session(), ImagenCreate(producto_color_id=uuid4(), url=SUBIDA), uuid4(), _settings()
            )

    assert error.value.status_code == 422
    assert "producto_color_id" in error.value.details


@pytest.mark.asyncio
async def test_create_rechaza_url_que_no_viene_de_uploads() -> None:
    otra = "https://res.cloudinary.com/otra/image/upload/v1/pinodo/imagenes/foto.jpg"

    with patch.object(
        ProductoColorRepository, "get_by_id", new=AsyncMock(return_value=_producto_color())
    ):
        with pytest.raises(AppException) as error:
            await ImagenService.create(
                _session(), ImagenCreate(producto_color_id=uuid4(), url=otra), uuid4(), _settings()
            )

    assert (error.value.status_code, list(error.value.details)) == (422, ["url"])


@pytest.mark.asyncio
async def test_create_rechaza_url_ya_asociada_sin_guardar_ni_mover() -> None:
    session = _session()

    with (
        patch.object(ProductoColorRepository, "get_by_id", new=AsyncMock(return_value=_producto_color())),
        patch.object(ImagenRepository, "get_active_by_url", new=AsyncMock(return_value=_imagen())),
        patch.object(CloudinaryService, "confirm_pending_uploads", new=AsyncMock()) as confirm,
    ):
        with pytest.raises(AppException) as error:
            await ImagenService.create(
                session, ImagenCreate(producto_color_id=uuid4(), url=SUBIDA), uuid4(), _settings()
            )

    assert error.value.status_code == 409
    session.commit.assert_not_awaited()
    confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_no_mueve_la_imagen_si_falla_el_commit() -> None:
    session = _session()
    session.commit = AsyncMock(side_effect=RuntimeError("fallo de base de datos"))

    with (
        patch.object(ProductoColorRepository, "get_by_id", new=AsyncMock(return_value=_producto_color())),
        patch.object(ImagenRepository, "get_active_by_url", new=AsyncMock(return_value=None)),
        patch.object(ImagenRepository, "add"),
        patch.object(CloudinaryService, "confirm_pending_uploads", new=AsyncMock()) as confirm,
    ):
        with pytest.raises(RuntimeError):
            await ImagenService.create(
                session, ImagenCreate(producto_color_id=uuid4(), url=SUBIDA), uuid4(), _settings()
            )

    confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cambia_el_tipo() -> None:
    imagen = _imagen()
    actor_id = uuid4()

    with patch.object(ImagenService, "get", new=AsyncMock(return_value=imagen)):
        result = await ImagenService.update(
            _session(),
            imagen.id,
            ImagenUpdate(tipo=TipoImagen.DETALLE),
            actor_id,
        )

    assert result.tipo is TipoImagen.DETALLE
    assert result.url == URL
    assert result.updated_by == actor_id


def test_update_no_acepta_url_ni_producto_color() -> None:
    with pytest.raises(ValueError):
        ImagenUpdate.model_validate({"url": URL})
    with pytest.raises(ValueError):
        ImagenUpdate.model_validate({"producto_color_id": str(uuid4())})


@pytest.mark.asyncio
async def test_delete_es_logico_y_conserva_el_archivo() -> None:
    imagen = _imagen()
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(ImagenService, "get", new=AsyncMock(return_value=imagen)),
        patch.object(CloudinaryService, "delete_image", new=AsyncMock()) as delete_image,
        patch.object(CloudinaryService, "safe_delete_image", new=AsyncMock()) as safe_delete,
    ):
        await ImagenService.delete(session, imagen.id, actor_id)

    assert imagen.is_deleted is True
    assert imagen.deleted_by == actor_id
    assert imagen.url == URL
    delete_image.assert_not_awaited()
    safe_delete.assert_not_awaited()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(ImagenRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await ImagenService.get(_session(), uuid4())

    assert error.value.status_code == 404
