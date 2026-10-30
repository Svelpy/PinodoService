import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import MetaData, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.schema import BLANK_SCHEMA
from sqlmodel import SQLModel

from app.core.config import get_settings
from app.core.database import get_connect_args
import app.domains.model_registry  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


settings = get_settings()

database_url = (
    settings.DATABASE_URL
    if settings.ENVIRONMENT == "production"
    else settings.TEST_DATABASE_URL
)

if not database_url:
    raise ValueError("No existe una URL de PostgreSQL configurada para Alembic.")

config.set_main_option(
    "sqlalchemy.url",
    database_url.replace("%", "%%"),
)

target_metadata = MetaData()


def _default_public_schema(
    _table: object,
    _target_schema: str | None,
    _constraint: object,
    referred_schema: str | None,
) -> object:
    return BLANK_SCHEMA if referred_schema == "public" else referred_schema


for model_table in SQLModel.metadata.sorted_tables:
    migration_table = model_table.to_metadata(
        target_metadata,
        schema=None,
        referred_schema_fn=_default_public_schema,
    )
    model_indexes = {
        (tuple(column.name for column in index.columns), index.unique): index.name
        for index in model_table.indexes
    }
    for migration_index in migration_table.indexes:
        signature = (
            tuple(column.name for column in migration_index.columns),
            migration_index.unique,
        )
        if signature in model_indexes:
            migration_index.name = model_indexes[signature]


def include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    """Limita Alembic a las tablas de esta aplicación en el esquema public."""
    if type_ == "table":
        schema_name = parent_names.get("schema_name")
        if schema_name is not None or name is None:
            return False
        return name in target_metadata.tables

    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=False,
        include_name=include_name,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=False,
        include_name=include_name,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=get_connect_args(),
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
