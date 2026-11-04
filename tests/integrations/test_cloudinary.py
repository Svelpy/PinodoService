from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.cloudinary import PENDING_TAG, CloudinaryService


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.CLOUDINARY_CLOUD_NAME = "micuenta"
    settings.CLOUDINARY_FOLDER_NAME = "pinodo"
    return settings


VALIDA = "https://res.cloudinary.com/micuenta/image/upload/v1730700000/pinodo/pendientes/abc_123-x.jpg"


def test_acepta_la_url_que_devuelve_upload_pending() -> None:
    assert CloudinaryService.is_pending_upload_url(VALIDA, _settings()) is True


@pytest.mark.parametrize(
    "url",
    [
        # Otra cuenta de Cloudinary.
        "https://res.cloudinary.com/otracuenta/image/upload/v1730700000/pinodo/pendientes/abc.jpg",
        # Otro proyecto en la misma cuenta.
        "https://res.cloudinary.com/micuenta/image/upload/v1730700000/otro/pendientes/abc.jpg",
        # Imagen ya asociada a un producto, no pendiente.
        "https://res.cloudinary.com/micuenta/image/upload/v1730700000/pinodo/productos/abc.jpg",
        # Sin HTTPS.
        "http://res.cloudinary.com/micuenta/image/upload/v1730700000/pinodo/pendientes/abc.jpg",
        # Dominio que imita a Cloudinary.
        "https://res.cloudinary.com.evil.com/micuenta/image/upload/v1/pinodo/pendientes/abc.jpg",
        "https://evil.com/res.cloudinary.com/micuenta/image/upload/v1/pinodo/pendientes/abc.jpg",
        # Transformación añadida.
        "https://res.cloudinary.com/micuenta/image/upload/w_9999/v1/pinodo/pendientes/abc.jpg",
        # Recorrido de rutas.
        "https://res.cloudinary.com/micuenta/image/upload/v1/pinodo/pendientes/../productos/abc.jpg",
        # Parámetros o fragmentos añadidos.
        VALIDA + "?x=1",
        VALIDA + "#x",
        # No es una URL de imagen.
        "https://res.cloudinary.com/micuenta/video/upload/v1/pinodo/pendientes/abc.mp4",
        "",
    ],
)
def test_rechaza_urls_que_no_son_pendientes_de_esta_cuenta(url: str) -> None:
    assert CloudinaryService.is_pending_upload_url(url, _settings()) is False


def test_rechaza_valores_que_no_son_texto() -> None:
    assert CloudinaryService.is_pending_upload_url(None, _settings()) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_upload_pending_sube_a_pendientes_con_etiqueta() -> None:
    upload = AsyncMock(return_value={"url": VALIDA, "public_id": "pinodo/pendientes/abc"})
    file = MagicMock()

    with patch.object(CloudinaryService, "upload_image", new=upload):
        result = await CloudinaryService.upload_pending(file, _settings())

    assert result["url"] == VALIDA
    assert upload.await_args.args[1] == "pendientes"
    assert upload.await_args.kwargs["tags"] == [PENDING_TAG]
