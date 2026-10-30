from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.logging import get_logger


logger = get_logger(__name__)


def _get_database_url(settings: Settings) -> str:
    if settings.ENVIRONMENT == "production":
        database_url = settings.DATABASE_URL
        variable_name = "DATABASE_URL"
    else:
        database_url = settings.TEST_DATABASE_URL
        variable_name = "TEST_DATABASE_URL"

    if not database_url:
        raise ValueError(f"Debe configurarse {variable_name} para PostgreSQL")

    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError(f"{variable_name} debe usar el formato " "postgresql+asyncpg://usuario:contraseña@host:puerto/base")

    return database_url


def get_connect_args() -> dict[str, Any]:
    """Argumentos de asyncpg compatibles con PgBouncer en modo transacción."""
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Crea el engine asíncrono de PostgreSQL."""
    return create_async_engine(_get_database_url(settings),echo=settings.DEBUG,pool_pre_ping=True,connect_args=get_connect_args())


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Crea la fábrica de sesiones de base de datos."""
    return async_sessionmaker(bind=engine,class_=AsyncSession,expire_on_commit=False,autoflush=False)


def initialize_database(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Inicializa el engine y la fábrica de sesiones."""

    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    logger.info("Engine de PostgreSQL inicializado")

    return engine, session_factory


async def check_database_connection(engine: AsyncEngine) -> None:
    """Comprueba que PostgreSQL responda."""

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Proporciona una sesión por solicitud."""

    session_factory: async_sessionmaker[AsyncSession] | None = getattr(request.app.state,"db_session_factory",None)

    if session_factory is None:
        raise RuntimeError("La fábrica de sesiones no está inicializada")

    async with session_factory() as session:
        yield session


async def close_database(engine: AsyncEngine) -> None:
    """Cierra el pool de conexiones."""

    await engine.dispose()
