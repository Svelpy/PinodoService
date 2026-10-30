from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.colores.repositories import ColorRepository
from app.domains.imagenes.repositories import ImagenRepository
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.schemas import (
    ProductoColorCreate,
    ProductoColorListItem,
    ProductoColorUpdate,
)
from app.domains.productos.repositories import ProductoRepository
from app.domains.skus.repositories import SkuRepository
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)


class ProductoColorService:
    """Reglas de negocio de los colores de cada producto."""

    @staticmethod
    def _duplicate_color() -> AppException:
        return AppException(
            "El producto ya tiene ese color.",
            409,
            ErrorCode.CONFLICT,
            {"color_id": "El producto ya tiene ese color."},
        )

    @staticmethod
    def _invalid_reference(field_name: str, message: str) -> AppException:
        return AppException(message, 422, ErrorCode.VALIDATION_ERROR, {field_name: message})

    @classmethod
    def _integrity_exception(cls, error: IntegrityError) -> AppException:
        original_error = error.orig
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "__cause__", None),
                "constraint_name",
                None,
            )

        if constraint_name == "uq_producto_colores_producto_color":
            return cls._duplicate_color()

        return AppException(
            "Los datos del color del producto entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        producto_color: ProductoColor | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        if producto_color is not None:
            await db_session.refresh(producto_color)

    @classmethod
    async def _validate_color(cls, db_session: AsyncSession, color_id: UUID) -> None:
        if await ColorRepository(db_session).get_by_id(color_id) is None:
            raise cls._invalid_reference("color_id", "El color no existe.")

    @classmethod
    async def _validate_unique_color(
        cls,
        repository: ProductoColorRepository,
        producto_id: UUID,
        color_id: UUID,
        exclude_id: UUID | None = None,
    ) -> None:
        existing = await repository.get_active_by_producto_and_color(
            producto_id,
            color_id,
            exclude_id=exclude_id,
        )
        if existing is not None:
            raise cls._duplicate_color()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        producto_color_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> ProductoColor:
        producto_color = await ProductoColorRepository(db_session).get_by_id(
            producto_color_id,
            include_deleted=include_deleted,
            for_update=for_update,
            load_detail=load_detail,
        )
        if producto_color is None:
            raise AppException(
                "Color del producto no encontrado.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return producto_color

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
        is_visible: bool | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[ProductoColorListItem]:
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

        producto_colores, total = await ProductoColorRepository(db_session).list(
            offset=(page - 1) * per_page,
            limit=per_page,
            producto_id=producto_id,
            color_id=color_id,
            is_visible=is_visible,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[ProductoColorListItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=producto_colores,
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: ProductoColorCreate,
        actor_id: UUID,
    ) -> ProductoColor:
        if await ProductoRepository(db_session).get_by_id(data.producto_id) is None:
            raise cls._invalid_reference("producto_id", "El producto no existe.")
        await cls._validate_color(db_session, data.color_id)

        repository = ProductoColorRepository(db_session)
        await cls._validate_unique_color(repository, data.producto_id, data.color_id)

        producto_color = ProductoColor(
            **data.model_dump(),
            created_by=actor_id,
            updated_by=actor_id,
        )
        repository.add(producto_color)
        await cls._commit(db_session, producto_color)

        logger.info(
            "Color de producto creado: producto_color_id=%s actor_id=%s",
            producto_color.id,
            actor_id,
        )
        return producto_color

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        producto_color_id: UUID,
        data: ProductoColorUpdate,
        actor_id: UUID,
    ) -> ProductoColor:
        """
        Actualiza el color o la visibilidad. Cambiar color_id corrige el color
        conservando sus imágenes y SKUs; el producto dueño no cambia.
        """
        changes = data.model_dump(exclude_unset=True)
        producto_color = await cls.get(db_session, producto_color_id, for_update=bool(changes))
        if not changes:
            return producto_color

        if changes.get("color_id", producto_color.color_id) != producto_color.color_id:
            await cls._validate_color(db_session, changes["color_id"])
            await cls._validate_unique_color(
                ProductoColorRepository(db_session),
                producto_color.producto_id,
                changes["color_id"],
                exclude_id=producto_color.id,
            )

        for field_name, value in changes.items():
            setattr(producto_color, field_name, value)
        producto_color.updated_at = utc_now()
        producto_color.updated_by = actor_id
        await cls._commit(db_session, producto_color)

        logger.info(
            "Color de producto actualizado: producto_color_id=%s actor_id=%s",
            producto_color.id,
            actor_id,
        )
        return producto_color

    @staticmethod
    async def delete_children(
        db_session: AsyncSession,
        producto_color_ids: Sequence[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> None:
        """
        Elimina lógicamente en cascada las imágenes y SKUs de esos colores de
        producto (AGENTS.md §5). No hace commit: lo hace quien coordina el borrado.
        """
        imagenes = await ImagenRepository(db_session).soft_delete_by_producto_color_ids(
            producto_color_ids,
            actor_id,
            now,
        )
        skus = await SkuRepository(db_session).soft_delete_by_producto_color_ids(
            producto_color_ids,
            actor_id,
            now,
        )
        logger.info(
            "Cascada de colores de producto: producto_color_ids=%s imagenes=%s skus=%s",
            list(producto_color_ids),
            imagenes,
            skus,
        )

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        producto_color_id: UUID,
        actor_id: UUID,
    ) -> ProductoColor:
        """
        Eliminación lógica en cascada: también elimina sus imágenes y SKUs. Los
        archivos de las imágenes se conservan en Cloudinary.
        """
        producto_color = await cls.get(db_session, producto_color_id, for_update=True)

        now = utc_now()
        await cls.delete_children(db_session, [producto_color.id], actor_id, now)
        producto_color.is_deleted = True
        producto_color.deleted_at = now
        producto_color.deleted_by = actor_id
        producto_color.updated_at = now
        producto_color.updated_by = actor_id
        await cls._commit(db_session, producto_color)

        logger.info(
            "Color de producto eliminado: producto_color_id=%s actor_id=%s",
            producto_color.id,
            actor_id,
        )
        return producto_color
