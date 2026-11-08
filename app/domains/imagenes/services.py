from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.imagenes.models import Imagen
from app.domains.imagenes.repositories import ImagenRepository
from app.domains.imagenes.schemas import (
    ImagenBibliotecaItem,
    ImagenCreate,
    ImagenListItem,
    ImagenResponse,
)
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.integrations.cloudinary import CloudinaryService
from app.shared.enums import TipoImagen
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)


class ImagenService:
    """Reglas de negocio de las imágenes de cada color de producto."""

    @staticmethod
    async def _commit(db_session: AsyncSession, imagen: Imagen) -> None:
        try:
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise
        await db_session.refresh(imagen)

    @staticmethod
    async def get(
        db_session: AsyncSession,
        imagen_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Imagen:
        imagen = await ImagenRepository(db_session).get_by_id(
            imagen_id,
            include_deleted=include_deleted,
            for_update=for_update,
        )
        if imagen is None:
            raise AppException(
                "Imagen no encontrada.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return imagen

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        producto_color_id: UUID | None = None,
        tipo: TipoImagen | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[ImagenListItem]:
        if page < 1:
            raise AppException(
                "La página debe ser mayor o igual a 1.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )
        if per_page < 1 or per_page > 100:
            raise AppException(
                "La cantidad por página debe estar entre 1 y 100.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )

        imagenes, total = await ImagenRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            producto_color_id=producto_color_id,
            tipo=tipo,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[ImagenListItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=imagenes,
        )

    @staticmethod
    async def list_biblioteca(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
        tipo: TipoImagen | None = None,
        nombre: str | None = None,
    ) -> PaginatedResponse[ImagenBibliotecaItem]:
        if page < 1:
            raise AppException(
                "La página debe ser mayor o igual a 1.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )
        if per_page < 1 or per_page > 100:
            raise AppException(
                "La cantidad por página debe estar entre 1 y 100.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )

        rows, total = await ImagenRepository(db_session).list_biblioteca(
            offset=(page - 1) * per_page,
            limit=per_page,
            producto_id=producto_id,
            color_id=color_id,
            tipo=tipo,
            nombre=nombre.strip() if nombre else None,
        )
        items = [
            ImagenBibliotecaItem(
                **ImagenResponse.model_validate(imagen).model_dump(),
                producto_id=row_producto_id,
                producto_nombre=producto_nombre,
                color_id=row_color_id,
                color_nombre=color_nombre,
                color_codigo_hex=color_codigo_hex,
            )
            for imagen, row_producto_id, producto_nombre, row_color_id, color_nombre, color_codigo_hex in rows
        ]
        return PaginatedResponse[ImagenBibliotecaItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=items,
        )

    @staticmethod
    async def upload_pending(file: UploadFile, settings: Settings, actor_id: UUID) -> str:
        """
        Sube una imagen antes de que exista su color de producto y devuelve su
        URL. No crea ningún registro: lo crea el create del producto al recibirla.
        """
        uploaded = await CloudinaryService.upload_pending(file, settings)
        logger.info("Imagen pendiente subida: actor_id=%s url=%s", actor_id, uploaded["url"])
        return uploaded["url"]

    @staticmethod
    def folder_for(producto_id: UUID, producto_color_id: UUID) -> str:
        """Carpeta de Cloudinary, relativa a la del proyecto, de las imágenes de un color."""
        return f"productos/{producto_id}/{producto_color_id}"

    @staticmethod
    async def validate_upload_url(db_session: AsyncSession, url: str, settings: Settings) -> None:
        """
        La url debe ser una subida de POST /imagenes/uploads y no estar ya
        asociada a otra imagen activa, porque un archivo vive en la carpeta de
        un solo color.
        """
        if not CloudinaryService.is_uploaded_image_url(url, settings):
            message = "La imagen debe subirse antes con POST /imagenes/uploads."
            raise AppException(message, 422, ErrorCode.VALIDATION_ERROR, {"url": message})
        if await ImagenRepository(db_session).get_active_by_url(url) is not None:
            message = "La imagen ya está asociada a otro color."
            raise AppException(message, 409, ErrorCode.CONFLICT, {"url": message})

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: ImagenCreate,
        actor_id: UUID,
        settings: Settings,
    ) -> Imagen:
        """
        Asocia a un color existente una imagen ya subida con POST
        /imagenes/uploads. Tras el commit, la imagen se mueve en Cloudinary a la
        carpeta de su color y deja de estar pendiente; su url no cambia.
        """
        producto_color = await ProductoColorRepository(db_session).get_by_id(
            data.producto_color_id
        )
        if producto_color is None:
            raise AppException(
                "El color del producto no existe.",
                422,
                ErrorCode.VALIDATION_ERROR,
                {"producto_color_id": "El color del producto no existe."},
            )
        await cls.validate_upload_url(db_session, data.url, settings)

        imagen = Imagen(**data.model_dump(), created_by=actor_id, updated_by=actor_id)
        ImagenRepository(db_session).add(imagen)
        await cls._commit(db_session, imagen)
        await CloudinaryService.confirm_pending_uploads(
            {data.url: cls.folder_for(producto_color.producto_id, producto_color.id)},
            settings,
        )

        logger.info("Imagen creada: imagen_id=%s actor_id=%s", imagen.id, actor_id)
        return imagen

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        imagen_id: UUID,
        actor_id: UUID,
    ) -> Imagen:
        """
        Eliminación lógica. El archivo se conserva en Cloudinary para que el
        registro borrado siga apuntando a una URL válida y pueda restaurarse.
        """
        imagen = await cls.get(db_session, imagen_id, for_update=True)

        now = utc_now()
        imagen.is_deleted = True
        imagen.deleted_at = now
        imagen.deleted_by = actor_id
        imagen.updated_at = now
        imagen.updated_by = actor_id
        await cls._commit(db_session, imagen)

        logger.info("Imagen eliminada: imagen_id=%s actor_id=%s", imagen.id, actor_id)
        return imagen
