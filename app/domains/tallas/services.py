from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.tallas.models import Talla
from app.domains.tallas.repositories import TallaRepository
from app.domains.tallas.schemas import TallaCreate, TallaResponse, TallaUpdate
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)


class TallaService:
    """Reglas de negocio del dominio de tallas."""

    @staticmethod
    def _etiqueta_conflict() -> AppException:
        return AppException(
            "Ya existe una talla con esa etiqueta.",
            409,
            ErrorCode.CONFLICT,
            {"etiqueta": "Ya existe una talla con esa etiqueta."},
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

        if constraint_name == "uq_tallas_etiqueta":
            return cls._etiqueta_conflict()

        return AppException(
            "Los datos de la talla entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        talla: Talla | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        if talla is not None:
            await db_session.refresh(talla)

    @classmethod
    async def _validate_unique_etiqueta(
        cls,
        repository: TallaRepository,
        etiqueta: str,
        exclude_id: UUID | None = None,
    ) -> None:
        if await repository.get_active_by_etiqueta(etiqueta, exclude_id=exclude_id) is not None:
            raise cls._etiqueta_conflict()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        talla_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Talla:
        talla = await TallaRepository(db_session).get_by_id(
            talla_id,
            include_deleted=include_deleted,
            for_update=for_update,
        )
        if talla is None:
            raise AppException(
                "Talla no encontrada.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return talla

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        include_deleted: bool = False,
    ) -> PaginatedResponse[TallaResponse]:
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

        tallas, total = await TallaRepository(db_session).list(
            offset=(page - 1) * per_page,
            limit=per_page,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[TallaResponse](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=tallas,
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: TallaCreate,
        actor_id: UUID,
    ) -> Talla:
        repository = TallaRepository(db_session)
        await cls._validate_unique_etiqueta(repository, data.etiqueta)

        talla = Talla(
            **data.model_dump(),
            created_by=actor_id,
            updated_by=actor_id,
        )
        repository.add(talla)
        await cls._commit(db_session, talla)

        logger.info("Talla creada: talla_id=%s actor_id=%s", talla.id, actor_id)
        return talla

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        talla_id: UUID,
        data: TallaUpdate,
        actor_id: UUID,
    ) -> Talla:
        changes = data.model_dump(exclude_unset=True)
        talla = await cls.get(db_session, talla_id, for_update=bool(changes))
        if not changes:
            return talla

        if "etiqueta" in changes:
            await cls._validate_unique_etiqueta(
                TallaRepository(db_session),
                changes["etiqueta"],
                exclude_id=talla.id,
            )

        for field_name, value in changes.items():
            setattr(talla, field_name, value)
        talla.updated_at = utc_now()
        talla.updated_by = actor_id
        await cls._commit(db_session, talla)

        logger.info("Talla actualizada: talla_id=%s actor_id=%s", talla.id, actor_id)
        return talla

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        talla_id: UUID,
        actor_id: UUID,
    ) -> Talla:
        """Eliminación lógica. Se rechaza si algún SKU activo usa la talla."""
        talla = await cls.get(db_session, talla_id, for_update=True)
        if await TallaRepository(db_session).has_active_dependents(talla.id):
            raise AppException(
                "No se puede eliminar una talla asignada a SKUs activos.",
                409,
                ErrorCode.CONFLICT,
            )

        now = utc_now()
        talla.is_deleted = True
        talla.deleted_at = now
        talla.deleted_by = actor_id
        talla.updated_at = now
        talla.updated_by = actor_id
        await cls._commit(db_session, talla)

        logger.info("Talla eliminada: talla_id=%s actor_id=%s", talla.id, actor_id)
        return talla
