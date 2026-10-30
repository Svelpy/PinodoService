from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.colores.models import Color
from app.domains.colores.repositories import ColorRepository
from app.domains.colores.schemas import ColorCreate, ColorResponse, ColorUpdate
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.services.slug import generate_slug


logger = get_logger(__name__)


class ColorService:
    """Reglas de negocio del dominio de colores."""

    @staticmethod
    def _slug_conflict() -> AppException:
        return AppException(
            "Ya existe un color con ese nombre.",
            409,
            ErrorCode.CONFLICT,
            {"nombre": "Ya existe un color con ese nombre."},
        )

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

        if constraint_name == "uq_colores_slug":
            return cls._slug_conflict()

        return AppException(
            "Los datos del color entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        color: Color | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        if color is not None:
            await db_session.refresh(color)

    @classmethod
    async def _validate_unique_slug(
        cls,
        repository: ColorRepository,
        slug: str,
        exclude_id: UUID | None = None,
    ) -> None:
        if await repository.get_active_by_slug(slug, exclude_id=exclude_id) is not None:
            raise cls._slug_conflict()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        color_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Color:
        color = await ColorRepository(db_session).get_by_id(
            color_id,
            include_deleted=include_deleted,
            for_update=for_update,
        )
        if color is None:
            raise AppException(
                "Color no encontrado.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return color

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        include_deleted: bool = False,
    ) -> PaginatedResponse[ColorResponse]:
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

        colores, total = await ColorRepository(db_session).list(
            offset=(page - 1) * per_page,
            limit=per_page,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[ColorResponse](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=colores,
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: ColorCreate,
        actor_id: UUID,
    ) -> Color:
        repository = ColorRepository(db_session)
        slug = generate_slug(data.nombre)
        await cls._validate_unique_slug(repository, slug)

        color = Color(
            **data.model_dump(),
            slug=slug,
            created_by=actor_id,
            updated_by=actor_id,
        )
        repository.add(color)
        await cls._commit(db_session, color)

        logger.info("Color creado: color_id=%s actor_id=%s", color.id, actor_id)
        return color

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        color_id: UUID,
        data: ColorUpdate,
        actor_id: UUID,
    ) -> Color:
        """Actualiza un color. Si cambia el nombre, se regenera el slug."""
        changes = data.model_dump(exclude_unset=True)
        color = await cls.get(db_session, color_id, for_update=bool(changes))
        if not changes:
            return color

        if "nombre" in changes:
            slug = generate_slug(changes["nombre"])
            await cls._validate_unique_slug(
                ColorRepository(db_session),
                slug,
                exclude_id=color.id,
            )
            changes["slug"] = slug

        for field_name, value in changes.items():
            setattr(color, field_name, value)
        color.updated_at = utc_now()
        color.updated_by = actor_id
        await cls._commit(db_session, color)

        logger.info("Color actualizado: color_id=%s actor_id=%s", color.id, actor_id)
        return color

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        color_id: UUID,
        actor_id: UUID,
    ) -> Color:
        """Eliminación lógica. Se rechaza si algún producto activo usa el color."""
        color = await cls.get(db_session, color_id, for_update=True)
        if await ColorRepository(db_session).has_active_dependents(color.id):
            raise AppException(
                "No se puede eliminar un color asignado a productos activos.",
                409,
                ErrorCode.CONFLICT,
            )

        now = utc_now()
        color.is_deleted = True
        color.deleted_at = now
        color.deleted_by = actor_id
        color.updated_at = now
        color.updated_by = actor_id
        await cls._commit(db_session, color)

        logger.info("Color eliminado: color_id=%s actor_id=%s", color.id, actor_id)
        return color
