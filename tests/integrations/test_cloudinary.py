from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.cloudinary import PENDING_TAG, CloudinaryService


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.CLOUDINARY_CLOUD_NAME = "micuenta"
    settings.CLOUDINARY_FOLDER_NAME = "pinodo"
    return settings


VALIDA = "https://res.cloudinary.com/micuenta/image/upload/v1730700000/pinodo/imagenes/abc_123-x.jpg"


def test_acepta_la_url_que_devuelve_upload_pending() -> None:
    assert CloudinaryService.is_uploaded_image_url(VALIDA, _settings()) is True


@pytest.mark.parametrize(
    "url",
    [
        # Otra cuenta de Cloudinary.
        "https://res.cloudinary.com/otracuenta/image/upload/v1730700000/pinodo/imagenes/abc.jpg",
        # Otro proyecto en la misma cuenta.
        "https://res.cloudinary.com/micuenta/image/upload/v1730700000/otro/imagenes/abc.jpg",
        # Subida por otro camino (por ejemplo, el logo de config).
        "https://res.cloudinary.com/micuenta/image/upload/v1730700000/pinodo/config/abc.jpg",
        # Sin HTTPS.
        "http://res.cloudinary.com/micuenta/image/upload/v1730700000/pinodo/imagenes/abc.jpg",
        # Dominio que imita a Cloudinary.
        "https://res.cloudinary.com.evil.com/micuenta/image/upload/v1/pinodo/imagenes/abc.jpg",
        "https://evil.com/res.cloudinary.com/micuenta/image/upload/v1/pinodo/imagenes/abc.jpg",
        # Transformación añadida.
        "https://res.cloudinary.com/micuenta/image/upload/w_9999/v1/pinodo/imagenes/abc.jpg",
        # Recorrido de rutas.
        "https://res.cloudinary.com/micuenta/image/upload/v1/pinodo/imagenes/../productos/abc.jpg",
        # Parámetros o fragmentos añadidos.
        VALIDA + "?x=1",
        VALIDA + "#x",
        # No es una URL de imagen.
        "https://res.cloudinary.com/micuenta/video/upload/v1/pinodo/imagenes/abc.mp4",
        "",
    ],
)
def test_rechaza_urls_que_no_son_subidas_de_esta_cuenta(url: str) -> None:
    assert CloudinaryService.is_uploaded_image_url(url, _settings()) is False


def test_rechaza_valores_que_no_son_texto() -> None:
    assert CloudinaryService.is_uploaded_image_url(None, _settings()) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_upload_pending_sube_a_pendientes_con_etiqueta() -> None:
    upload = AsyncMock(return_value={"url": VALIDA, "public_id": "pinodo/imagenes/abc"})
    file = MagicMock()

    with patch.object(CloudinaryService, "upload_image", new=upload):
        result = await CloudinaryService.upload_pending(file, _settings())

    assert result["url"] == VALIDA
    # Carpeta de pendientes, pero una url con prefijo neutro que no cambia al moverla.
    assert upload.await_args.args[1] == "pendientes"
    assert upload.await_args.kwargs["tags"] == [PENDING_TAG]
    assert upload.await_args.kwargs["public_id_prefix"] == "imagenes"


@pytest.mark.asyncio
async def test_confirm_mueve_cada_imagen_a_su_carpeta_y_quita_la_etiqueta() -> None:
    otra = VALIDA.replace("abc_123-x", "def")
    with (
        patch("app.integrations.cloudinary.cloudinary.uploader.explicit") as explicit,
        patch("app.integrations.cloudinary.cloudinary.uploader.remove_tag") as remove_tag,
    ):
        await CloudinaryService.confirm_pending_uploads(
            {VALIDA: "productos/P/C1", otra: "productos/P/C2"}, _settings()
        )

    movidas = {c.args[0]: c.kwargs["asset_folder"] for c in explicit.call_args_list}
    assert movidas == {
        "pinodo/imagenes/abc_123-x": "pinodo/productos/P/C1",
        "pinodo/imagenes/def": "pinodo/productos/P/C2",
    }
    assert remove_tag.call_args.args == (PENDING_TAG, ["pinodo/imagenes/abc_123-x", "pinodo/imagenes/def"])


@pytest.mark.asyncio
async def test_confirm_no_interrumpe_si_cloudinary_falla() -> None:
    with patch(
        "app.integrations.cloudinary.cloudinary.uploader.explicit", side_effect=RuntimeError("caído")
    ):
        await CloudinaryService.confirm_pending_uploads({VALIDA: "productos/P/C"}, _settings())


@pytest.mark.asyncio
async def test_confirm_sin_imagenes_no_llama_a_cloudinary() -> None:
    with patch("app.integrations.cloudinary.cloudinary.uploader.explicit") as explicit:
        await CloudinaryService.confirm_pending_uploads({}, _settings())

    explicit.assert_not_called()
