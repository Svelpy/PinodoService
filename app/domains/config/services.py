from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.config.models import Config
from app.domains.config.repositories import ConfigRepository
from app.domains.config.schemas import ConfigMantenimientoUpdate, ConfigUpdate
from app.integrations.cloudinary import CloudinaryService
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
        settings: Settings,
        *,
        logo: UploadFile | None = None,
        favicon: UploadFile | None = None,
        eliminar_logo: bool = False,
        eliminar_favicon: bool = False,
    ) -> Config:
        """
        Actualiza los campos enviados y, si llegan archivos, los sube a
        Cloudinary y guarda su URL en logo_url o favicon_url.

        Si la actualización falla, los archivos recién subidos se eliminan.
        Si se confirma, se eliminan los archivos anteriores que se reemplazaron
        o quitaron.
        """
        if logo is not None and eliminar_logo:
            raise AppException(
                "No se puede subir y eliminar el logo a la vez.",
                422,
                ErrorCode.VALIDATION_ERROR,
                {"logo": "No se puede subir y eliminar el logo a la vez."},
            )
        if favicon is not None and eliminar_favicon:
            raise AppException(
                "No se puede subir y eliminar el favicon a la vez.",
                422,
                ErrorCode.VALIDATION_ERROR,
                {"favicon": "No se puede subir y eliminar el favicon a la vez."},
            )

        changes = data.model_dump(exclude_unset=True)
        if eliminar_logo:
            changes["logo_url"] = None
        if eliminar_favicon:
            changes["favicon_url"] = None

        # Se comprueba que exista antes de subir, para no dejar archivos huérfanos.
        config = await cls.get(db_session)
        if not changes and logo is None and favicon is None:
            return config

        uploaded_urls: list[str] = []
        try:
            for field_name, file in (("logo_url", logo), ("favicon_url", favicon)):
                if file is not None:
                    uploaded = await CloudinaryService.upload_image(file, "config", settings)
                    uploaded_urls.append(uploaded["url"])
                    changes[field_name] = uploaded["url"]

            config = await cls.get(db_session, for_update=True)
            replaced_urls = [
                previous_url
                for field_name in ("logo_url", "favicon_url")
                if field_name in changes
                and (previous_url := getattr(config, field_name))
                and previous_url != changes[field_name]
            ]

            for field_name, value in changes.items():
                setattr(config, field_name, value)
            config.updated_at = utc_now()
            config.updated_by = actor_id
            await cls._commit(db_session, config)
        except Exception:
            for url in uploaded_urls:
                await CloudinaryService.safe_delete_image(url)
            raise

        for url in replaced_urls:
            await CloudinaryService.safe_delete_image(url)

        logger.info("Configuración actualizada: actor_id=%s", actor_id)
        return config

    @classmethod
    async def set_mantenimiento(
        cls,
        db_session: AsyncSession,
        data: ConfigMantenimientoUpdate,
        actor_id: UUID,
    ) -> Config:
        """Activa o desactiva el modo mantenimiento de la tienda pública."""
        config = await cls.get(db_session, for_update=True)
        if config.en_mantenimiento == data.en_mantenimiento:
            return config

        config.en_mantenimiento = data.en_mantenimiento
        config.updated_at = utc_now()
        config.updated_by = actor_id
        await cls._commit(db_session, config)

        logger.info(
            "Modo mantenimiento=%s: actor_id=%s",
            data.en_mantenimiento,
            actor_id,
        )
        return config
