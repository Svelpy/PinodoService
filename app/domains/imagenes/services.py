from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.imagenes.models import Imagen
from app.domains.imagenes.repositories import ImagenRepository
from app.domains.imagenes.schemas import ImagenCreate, ImagenListItem, ImagenUpdate
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

        imagenes, total = await ImagenRepository(db_session).list(
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

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: ImagenCreate,
        file: UploadFile,
        actor_id: UUID,
        settings: Settings,
    ) -> Imagen:
        """
        Sube el archivo a Cloudinary y registra la imagen.

        El color del producto se valida antes de subir, para no dejar archivos
        huérfanos; si el registro falla, el archivo recién subido se elimina.
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

        uploaded = await CloudinaryService.upload_image(
            file,
            f"productos/{producto_color.producto_id}/{producto_color.id}",
            settings,
        )

        imagen = Imagen(
            **data.model_dump(),
            url=uploaded["url"],
            created_by=actor_id,
            updated_by=actor_id,
        )
        try:
            ImagenRepository(db_session).add(imagen)
            await cls._commit(db_session, imagen)
        except Exception:
            await CloudinaryService.safe_delete_image(uploaded["url"])
            raise

        logger.info("Imagen creada: imagen_id=%s actor_id=%s", imagen.id, actor_id)
        return imagen

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        imagen_id: UUID,
        data: ImagenUpdate,
        actor_id: UUID,
    ) -> Imagen:
        """Solo cambia el tipo; para cambiar el archivo se elimina y se sube otra imagen."""
        changes = data.model_dump(exclude_unset=True)
        imagen = await cls.get(db_session, imagen_id, for_update=bool(changes))
        if not changes:
            return imagen

        for field_name, value in changes.items():
            setattr(imagen, field_name, value)
        imagen.updated_at = utc_now()
        imagen.updated_by = actor_id
        await cls._commit(db_session, imagen)

        logger.info("Imagen actualizada: imagen_id=%s actor_id=%s", imagen.id, actor_id)
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
