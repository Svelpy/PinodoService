from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.config.models import Config
from app.domains.config.repositories import ConfigRepository
from app.domains.config.schemas import ConfigUpdate
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException


logger = get_logger(__name__)


class ConfigService:
    """Reglas de negocio de la configuración de la tienda (fila única id = 1)."""

    @staticmethod
    async def _commit(db_session: AsyncSession, config: Config) -> None:
        try:
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise
        await db_session.refresh(config)

    @staticmethod
    async def get(db_session: AsyncSession, *, for_update: bool = False) -> Config:
        config = await ConfigRepository(db_session).get(for_update=for_update)
        if config is None:
            raise AppException(
                "La configuración de la tienda no existe.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return config

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        data: ConfigUpdate,
        actor_id: UUID,
    ) -> Config:
        changes = data.model_dump(exclude_unset=True)
        config = await cls.get(db_session, for_update=bool(changes))
        if not changes:
            return config

        for field_name, value in changes.items():
            setattr(config, field_name, value)
        config.updated_at = utc_now()
        config.updated_by = actor_id
        await cls._commit(db_session, config)

        logger.info("Configuración actualizada: actor_id=%s", actor_id)
        return config
