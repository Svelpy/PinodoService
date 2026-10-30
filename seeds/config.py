import asyncio

from app.core.config import Settings, get_settings
from app.core.database import (
    check_database_connection,
    close_database,
    initialize_database,
)
from app.core.logging import get_logger, setup_logging
import app.domains.model_registry  # noqa: F401
from app.domains.config.models import Config
from app.domains.config.repositories import CONFIG_ID, ConfigRepository
from app.domains.config.schemas import ConfigCreate


logger = get_logger(__name__)

SEED_CONFIG = ConfigCreate(nombre_tienda="PINODO")


async def seed_config(settings: Settings) -> None:
    """Crea la fila única de configuración si no existe; nunca sobrescribe la existente."""
    engine, session_factory = initialize_database(settings)

    try:
        await check_database_connection(engine)

        async with session_factory() as db_session:
            repository = ConfigRepository(db_session)
            if await repository.get() is not None:
                logger.info("Seed finalizado: la configuración ya existe; no se modificó.")
                return

            repository.add(Config(**SEED_CONFIG.model_dump(), id=CONFIG_ID))
            await db_session.commit()

            logger.info(
                "Seed finalizado: configuración creada con nombre_tienda=%s.",
                SEED_CONFIG.nombre_tienda,
            )
    except Exception:
        logger.exception("Error durante la ejecución del seed de configuración")
        raise
    finally:
        await close_database(engine)


if __name__ == "__main__":
    app_settings = get_settings()
    setup_logging(app_settings)
    asyncio.run(seed_config(app_settings))
