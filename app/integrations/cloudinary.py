import asyncio

import cloudinary
import cloudinary.uploader
from fastapi import UploadFile

from app.core.config import Settings
from app.core.logging import get_logger
from app.shared.errors.exceptions import AppException
from app.shared.errors.codes import ErrorCode

logger = get_logger(__name__)
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

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
    async def upload_image(
        file: UploadFile,
        folder: str,
        settings: Settings,
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
            # El SDK de Cloudinary es síncrono.
            response = await asyncio.to_thread(
                cloudinary.uploader.upload,
                content, 
                folder=cloudinary_folder,
                resource_type="image"
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
        """
        if not image_url:
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
    async def safe_delete_image(image_url: str) -> bool:
        """
        Intenta eliminar una imagen sin interrumpir la operación principal.
        """
        try:
            return await CloudinaryService.delete_image(image_url)
        except Exception:
            logger.exception("No se pudo eliminar una imagen residual de Cloudinary: %s",image_url)
            return False

