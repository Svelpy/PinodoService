import asyncio

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings
from app.core.database import (
    check_database_connection,
    close_database,
    initialize_database,
)
from app.core.logging import get_logger, setup_logging
from app.core.security import hash_password
import app.domains.model_registry  # noqa: F401
from app.domains.usuarios.models import Usuario
from app.domains.usuarios.repositories import UsuarioRepository
from app.domains.usuarios.schemas import UsuarioCreate
from app.shared.enums import Role


logger = get_logger(__name__)


def build_seed_admins(settings: Settings) -> list[UsuarioCreate]:
    """Valida y normaliza la configuración de los tres SUPERADMIN con las reglas de la API."""
    admins: list[UsuarioCreate] = []

    for position in (1, 2, 3):
        password = getattr(settings, f"SEED_ADMIN_PASSWORD_{position}")
        try:
            admin = UsuarioCreate(
                email=getattr(settings, f"SEED_ADMIN_EMAIL_{position}"),
                password=password.get_secret_value() if password is not None else None,
                nombre=getattr(settings, f"SEED_ADMIN_NAME_{position}"),
                apellidos=getattr(settings, f"SEED_ADMIN_LASTNAME_{position}"),
                rol=Role.SUPERADMIN,
            )
        except ValidationError as error:
            raise ValueError(
                f"Configuración inválida para SEED_ADMIN_*_{position}: {error}"
            ) from error

        admins.append(admin)

    emails = [str(admin.email) for admin in admins]
    if len(set(emails)) != len(emails):
        raise ValueError("Los emails configurados para los SUPERADMIN deben ser únicos.")

    return admins


async def seed_users(settings: Settings) -> None:
    """Crea los tres SUPERADMIN faltantes sin sobrescribir los existentes."""
    admins = build_seed_admins(settings)
    engine, session_factory = initialize_database(settings)

    try:
        await check_database_connection(engine)

        async with session_factory() as db_session:
            repository = UsuarioRepository(db_session)
            created_count = 0

            for position, admin_data in enumerate(admins, start=1):
                existing_user = await repository.get_active_by_email(str(admin_data.email))

                if existing_user is not None:
                    if existing_user.rol != Role.SUPERADMIN:
                        raise ValueError(
                            f"SEED_ADMIN_*_{position} ya existe con otro rol."
                        )

                    logger.info(
                        "SUPERADMIN %s existente; no se sobrescribió su contraseña.",
                        position,
                    )
                    continue

                password_hash = await asyncio.to_thread(
                    hash_password,
                    admin_data.password,
                )
                user = Usuario(
                    email=str(admin_data.email),
                    password_hash=password_hash,
                    nombre=admin_data.nombre,
                    apellidos=admin_data.apellidos,
                    telefono=admin_data.telefono,
                    rol=Role.SUPERADMIN,
                )
                user.created_by = user.id
                user.updated_by = user.id
                repository.add(user)
                created_count += 1

            try:
                await db_session.commit()
            except IntegrityError as error:
                await db_session.rollback()
                raise ValueError(
                    "No se pudieron crear los SUPERADMIN por un conflicto de integridad."
                ) from error

            logger.info(
                "Seed finalizado: %s SUPERADMIN nuevos; %s existentes conservados.",
                created_count,
                len(admins) - created_count,
            )
    except Exception:
        logger.exception("Error durante la ejecución del seed de usuarios")
        raise
    finally:
        await close_database(engine)


if __name__ == "__main__":
    app_settings = get_settings()
    setup_logging(app_settings)
    asyncio.run(seed_users(app_settings))
