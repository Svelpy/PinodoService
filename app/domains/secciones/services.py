from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.secciones.models import Seccion
from app.domains.secciones.repositories import SeccionRepository
from app.domains.secciones.schemas import SeccionCreate, SeccionResponse, SeccionUpdate
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.services.slug import generate_slug


logger = get_logger(__name__)


class SeccionService:
    """Reglas de negocio del dominio de secciones."""

    @staticmethod
    def _slug_conflict() -> AppException:
        return AppException(
            "Ya existe una sección con ese nombre.",
            409,
            ErrorCode.CONFLICT,
            {"nombre": "Ya existe una sección con ese nombre."},
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

        if constraint_name == "uq_secciones_slug":
            return cls._slug_conflict()

        return AppException(
            "Los datos de la sección entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        seccion: Seccion | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        if seccion is not None:
            await db_session.refresh(seccion)

    @classmethod
    async def _validate_unique_slug(
        cls,
        repository: SeccionRepository,
        slug: str,
        exclude_id: UUID | None = None,
    ) -> None:
        if await repository.get_active_by_slug(slug, exclude_id=exclude_id) is not None:
            raise cls._slug_conflict()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        seccion_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Seccion:
        seccion = await SeccionRepository(db_session).get_by_id(
            seccion_id,
            include_deleted=include_deleted,
            for_update=for_update,
        )
        if seccion is None:
            raise AppException(
                "Sección no encontrada.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return seccion

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        is_visible: bool | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[SeccionResponse]:
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

        secciones, total = await SeccionRepository(db_session).list(
            offset=(page - 1) * per_page,
            limit=per_page,
            is_visible=is_visible,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[SeccionResponse](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=secciones,
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: SeccionCreate,
        actor_id: UUID,
    ) -> Seccion:
        repository = SeccionRepository(db_session)
        slug = generate_slug(data.nombre)
        await cls._validate_unique_slug(repository, slug)

        seccion = Seccion(
            **data.model_dump(),
            slug=slug,
            created_by=actor_id,
            updated_by=actor_id,
        )
        repository.add(seccion)
        await cls._commit(db_session, seccion)

        logger.info("Sección creada: seccion_id=%s actor_id=%s", seccion.id, actor_id)
        return seccion

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        seccion_id: UUID,
        data: SeccionUpdate,
        actor_id: UUID,
    ) -> Seccion:
        """Actualiza una sección. Si cambia el nombre, se regenera el slug."""
        changes = data.model_dump(exclude_unset=True)
        seccion = await cls.get(db_session, seccion_id, for_update=bool(changes))
        if not changes:
            return seccion

        if "nombre" in changes:
            slug = generate_slug(changes["nombre"])
            await cls._validate_unique_slug(
                SeccionRepository(db_session),
                slug,
                exclude_id=seccion.id,
            )
            changes["slug"] = slug

        for field_name, value in changes.items():
            setattr(seccion, field_name, value)
        seccion.updated_at = utc_now()
        seccion.updated_by = actor_id
        await cls._commit(db_session, seccion)

        logger.info("Sección actualizada: seccion_id=%s actor_id=%s", seccion.id, actor_id)
        return seccion

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        seccion_id: UUID,
        actor_id: UUID,
    ) -> Seccion:
        """Eliminación lógica. Se rechaza si la sección tiene categorías o productos activos."""
        seccion = await cls.get(db_session, seccion_id, for_update=True)
        if await SeccionRepository(db_session).has_active_dependents(seccion.id):
            raise AppException(
                "No se puede eliminar una sección con categorías o productos activos.",
                409,
                ErrorCode.CONFLICT,
            )

        now = utc_now()
        seccion.is_deleted = True
        seccion.deleted_at = now
        seccion.deleted_by = actor_id
        seccion.updated_at = now
        seccion.updated_by = actor_id
        await cls._commit(db_session, seccion)

        logger.info("Sección eliminada: seccion_id=%s actor_id=%s", seccion.id, actor_id)
        return seccion
