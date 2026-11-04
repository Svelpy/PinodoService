import asyncio
import re

import cloudinary
import cloudinary.uploader
from fastapi import UploadFile

from app.core.config import Settings
from app.core.logging import get_logger
from app.shared.errors.exceptions import AppException
from app.shared.errors.codes import ErrorCode

logger = get_logger(__name__)
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

# Imágenes subidas antes de crear su registro (POST /imagenes/uploads).
# La cuenta usa carpetas dinámicas: la carpeta (asset_folder) es independiente
# de la URL. Por eso la URL lleva un prefijo neutro que no cambia nunca, y la
# imagen vive en la carpeta y con la etiqueta de pendiente hasta que un create la
# asocia; entonces se mueve a la carpeta de su dueño y pierde la etiqueta, lo que
# permite limpiar las huérfanas.
UPLOADS_PREFIX = "imagenes"
PENDING_FOLDER = "pendientes"
PENDING_TAG = "pendiente"

def configure_cloudinary(settings: Settings) -> None:
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )

class CloudinaryService:
    @staticmethod
    def _extract_public_id(url: str) -> str:
        """
        Extrae el public_id de una URL de Cloudinary.
        """
        try:
            # Dividir por '/upload/' para obtener la parte derecha de la URL
            parts = url.split("/upload/")
            if len(parts) < 2:
                raise ValueError("URL de Cloudinary inválida")
            
            # Quitar la versión (ej: 'v123456789/') si existe
            right_part = parts[1]
            if right_part.startswith("v"):
                right_part = "/".join(right_part.split("/")[1:])
            
            # Quitar la extensión del archivo (ej: '.jpg')
            public_id = right_part.rsplit(".", 1)[0]
            return public_id

        except Exception:
            raise AppException("No se pudo extraer el identificador de la imagen", 400)
    
    @staticmethod
    def is_uploaded_image_url(url: str, settings: Settings) -> bool:
        """
        True si la URL es exactamente una de las que devuelve upload_pending:
        HTTPS, de la cuenta configurada (cloud_name), con el prefijo de subidas
        del proyecto y sin transformaciones ni parámetros añadidos.

        Prueba el origen, no que siga pendiente: que no esté ya asociada a otro
        registro lo comprueba el service en la base de datos.
        """
        if not isinstance(url, str) or not settings.CLOUDINARY_CLOUD_NAME:
            return False
        pattern = (
            rf"https://res\.cloudinary\.com/{re.escape(settings.CLOUDINARY_CLOUD_NAME)}"
            rf"/image/upload/v\d+/{re.escape(settings.CLOUDINARY_FOLDER_NAME or '')}"
            rf"/{UPLOADS_PREFIX}/[A-Za-z0-9_-]+\.[A-Za-z0-9]+"
        )
        return re.fullmatch(pattern, url) is not None

    @staticmethod
    async def upload_pending(file: UploadFile, settings: Settings) -> dict[str, str]:
        """Sube una imagen que todavía no pertenece a ningún registro."""
        return await CloudinaryService.upload_image(
            file,
            PENDING_FOLDER,
            settings,
            tags=[PENDING_TAG],
            public_id_prefix=UPLOADS_PREFIX,
        )

    @staticmethod
    async def upload_image(
        file: UploadFile,
        folder: str,
        settings: Settings,
        *,
        tags: list[str] | None = None,
        public_id_prefix: str | None = None,
    ) -> dict[str, str]:
        """
        Sube una imagen a Cloudinary.

        Retorna la URL segura y el public_id generado por Cloudinary.
        """
        # Validar Content-Type
        if not file.content_type or not file.content_type.startswith("image/"):
            raise AppException("El archivo debe ser una imagen", 400,code=ErrorCode.INVALID_IMAGE)
        
        # Bloquear SVG explícitamente
        filename = file.filename or ""
        if file.content_type == "image/svg+xml" or filename.lower().endswith(".svg"):
            raise AppException("Los archivos SVG no están permitidos", 400, code=ErrorCode.INVALID_IMAGE)
            
        # Leer archivo
        content = await file.read()
        
        try:
            if len(content) > MAX_IMAGE_SIZE:
                raise AppException("La imagen no puede pesar más de 5MB", 400, code=ErrorCode.INVALID_IMAGE)
            cloudinary_folder= f"{settings.CLOUDINARY_FOLDER_NAME}/{folder}"
            # Sin public_id_prefix, la carpeta también forma parte de la URL. Con
            # él, la URL usa ese prefijo y la imagen puede cambiar de carpeta
            # después sin que cambie su URL.
            location = (
                {
                    "asset_folder": cloudinary_folder,
                    "public_id_prefix": f"{settings.CLOUDINARY_FOLDER_NAME}/{public_id_prefix}",
                }
                if public_id_prefix
                else {"folder": cloudinary_folder}
            )
            # El SDK de Cloudinary es síncrono.
            response = await asyncio.to_thread(
                cloudinary.uploader.upload,
                content,
                resource_type="image",
                tags=tags or [],
                **location,
            )

            secure_url = response.get("secure_url")
            public_id = response.get("public_id")
            if not secure_url or not public_id:
                raise AppException("Cloudinary no devolvió los datos esperados",500)
            return {"url": secure_url,"public_id": public_id}

        finally:
            await file.seek(0)

    @staticmethod
    async def delete_image(image_url: str) -> bool:
        """
        Elimina una imagen de Cloudinary utilizando su public_id.

        Las URLs que no son de Cloudinary se ignoran: no hay nada que borrar.
        """
        if not image_url or "res.cloudinary.com" not in image_url:
            return False
        public_id = CloudinaryService._extract_public_id(image_url)
        if not public_id:
            return False
            
        response = await asyncio.to_thread(
            cloudinary.uploader.destroy,
            public_id,
            resource_type="image",
        )
        return response.get("result") == "ok"

    @staticmethod
    async def confirm_pending_uploads(destinations: dict[str, str], settings: Settings) -> None:
        """
        Confirma imágenes que ya quedaron asociadas a un registro: mueve cada una
        de la carpeta de pendientes a la de su dueño (destinations: url →
        carpeta relativa a la del proyecto) y les quita la etiqueta de
        pendiente, para que la limpieza de huérfanas no las elimine.

        Usa la API de subida (explicit y remove_tag), no la de administración, y
        la URL no cambia. No interrumpe la operación principal: si falla, solo
        se registra, y la imagen sigue funcionando desde su carpeta anterior.
        """
        if not destinations:
            return
        try:
            public_ids = {url: CloudinaryService._extract_public_id(url) for url in destinations}
            await asyncio.gather(
                *(
                    asyncio.to_thread(
                        cloudinary.uploader.explicit,
                        public_ids[url],
                        type="upload",
                        asset_folder=f"{settings.CLOUDINARY_FOLDER_NAME}/{folder}",
                    )
                    for url, folder in destinations.items()
                )
            )
            await asyncio.to_thread(
                cloudinary.uploader.remove_tag, PENDING_TAG, list(public_ids.values())
            )
        except Exception:
            logger.exception(
                "No se pudo confirmar imágenes pendientes en Cloudinary: %s", list(destinations)
            )

    @staticmethod
    async def safe_delete_image(image_url: str) -> bool:
        """
        Intenta eliminar una imagen sin interrumpir la operación principal.
        """
        try:
            return await CloudinaryService.delete_image(image_url)
        except Exception:
            logger.exception("No se pudo eliminar una imagen residual de Cloudinary: %s",image_url)
            return False

