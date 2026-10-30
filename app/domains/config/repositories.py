from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.config.models import Config


CONFIG_ID = 1


class ConfigRepository:
    """Acceso a la fila única de configuración. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get(self, *, for_update: bool = False) -> Config | None:
        statement = select(Config).where(Config.id == CONFIG_ID)
        if for_update:
            statement = statement.with_for_update()

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    def add(self, config: Config) -> None:
        self.db_session.add(config)
