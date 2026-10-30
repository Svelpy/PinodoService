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


@pytest.mark.asyncio
async def test_create_sube_a_la_carpeta_del_producto_y_guarda_la_url() -> None:
    producto_color = _producto_color()
    session = _session()
    actor_id = uuid4()
    file = MagicMock()

    with (
        patch.object(
            ProductoColorRepository,
            "get_by_id",
            new=AsyncMock(return_value=producto_color),
        ),
        patch.object(
            CloudinaryService,
            "upload_image",
            new=AsyncMock(return_value={"url": URL, "public_id": "x"}),
        ) as upload,
        patch.object(ImagenRepository, "add") as add,
    ):
        imagen = await ImagenService.create(
            session,
            ImagenCreate(producto_color_id=producto_color.id, tipo=TipoImagen.PRENDA),
            file,
            actor_id,
            get_settings(),
        )

    assert upload.await_args.args[0] is file
    assert upload.await_args.args[1] == (
        f"productos/{producto_color.producto_id}/{producto_color.id}"
    )
    assert imagen.url == URL
    assert imagen.tipo is TipoImagen.PRENDA
    assert imagen.created_by == actor_id
    add.assert_called_once_with(imagen)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_no_sube_nada_si_el_color_no_existe() -> None:
    with (
        patch.object(ProductoColorRepository, "get_by_id", new=AsyncMock(return_value=None)),
        patch.object(CloudinaryService, "upload_image", new=AsyncMock()) as upload,
    ):
        with pytest.raises(AppException) as error:
            await ImagenService.create(
                _session(),
                ImagenCreate(producto_color_id=uuid4()),
                MagicMock(),
                uuid4(),
                get_settings(),
            )

    assert error.value.status_code == 422
    assert "producto_color_id" in error.value.details
    upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_borra_el_archivo_subido_si_falla_el_registro() -> None:
    session = _session()
    session.commit = AsyncMock(side_effect=RuntimeError("fallo de base de datos"))

    with (
        patch.object(
            ProductoColorRepository,
            "get_by_id",
            new=AsyncMock(return_value=_producto_color()),
        ),
        patch.object(
            CloudinaryService,
            "upload_image",
            new=AsyncMock(return_value={"url": URL, "public_id": "x"}),
        ),
        patch.object(CloudinaryService, "safe_delete_image", new=AsyncMock()) as safe_delete,
        patch.object(ImagenRepository, "add"),
    ):
        with pytest.raises(RuntimeError):
            await ImagenService.create(
                session,
                ImagenCreate(producto_color_id=uuid4()),
                MagicMock(),
                uuid4(),
                get_settings(),
            )

    safe_delete.assert_awaited_once_with(URL)
    session.rollback.assert_awaited_once()


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
