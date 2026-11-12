from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.auth.schemas import CurrentUser
from app.domains.venta_pagos.models import VentaPago
from app.domains.venta_pagos.repositories import VentaPagoRepository, VentaPagoScope
from app.integrations.cloudinary import CloudinaryService
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.services.permissions import VENTA_GLOBAL_SCOPE_ROLES, VENTA_OWN_SCOPE_ROLES


logger = get_logger(__name__)

COMPROBANTES_FOLDER = "comprobantes"


class VentaPagoService:
    """
    Reglas de los pagos de venta.

    - Los pagos se registran con su venta, en VentaService.agregar_pagos: al
      crearla o al confirmarla, cubriendo exactamente su total.
    - Un pago no se anula ni cambia de monto o método: la devolución se hace
      cancelando la venta completa. Solo se sube o reemplaza su comprobante.
    - Se consulta desde su venta; get existe para la auditoría, la recarga
      tras escribir y el comprobante.
    - Su alcance es el de su venta.
    """

    @staticmethod
    def _scope_for(actor: CurrentUser) -> VentaPagoScope:
        if actor.rol in VENTA_GLOBAL_SCOPE_ROLES:
            return VentaPagoScope(all=True)
        if actor.rol in VENTA_OWN_SCOPE_ROLES:
            return VentaPagoScope(venta_created_by=actor.id)
        return VentaPagoScope()  # alcance vacío: no devuelve filas

    @staticmethod
    async def _commit(db_session: AsyncSession) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise AppException(
                "Los datos del pago entran en conflicto con un registro existente.",
                409,
                ErrorCode.CONFLICT,
            ) from error
        except Exception:
            await db_session.rollback()
            raise

    # ------------------------------------------------------------------ lectura

    @classmethod
    async def get(
        cls,
        db_session: AsyncSession,
        pago_id: UUID,
        actor: CurrentUser,
        *,
        for_update: bool = False,
    ) -> VentaPago:
        """Un pago fuera del alcance del actor responde 404, igual que uno inexistente."""
        pago = await VentaPagoRepository(db_session).get_by_id(
            pago_id,
            scope=cls._scope_for(actor),
            for_update=for_update,
        )
        if pago is None:
            raise AppException("Pago no encontrado.", 404, ErrorCode.RESOURCE_NOT_FOUND)
        return pago

    # ------------------------------------------------------------------ escritura

    @classmethod
    async def _reload(cls, db_session: AsyncSession, pago_id: UUID, actor: CurrentUser) -> VentaPago:
        db_session.expire_all()
        return await cls.get(db_session, pago_id, actor)

    @classmethod
    async def upload_comprobante(
        cls,
        db_session: AsyncSession,
        pago_id: UUID,
        file: UploadFile,
        actor: CurrentUser,
        settings: Settings,
    ) -> VentaPago:
        """
        Sube la imagen del comprobante y la guarda en el pago, reemplazando la
        anterior. Si el guardado falla, la imagen nueva se elimina; si se
        confirma, se elimina la anterior.
        """
        # Se comprueba antes de subir, para no dejar archivos huérfanos.
        await cls.get(db_session, pago_id, actor)

        uploaded = await CloudinaryService.upload_image(file, COMPROBANTES_FOLDER, settings)
        try:
            pago = await cls.get(db_session, pago_id, actor, for_update=True)
            anterior = pago.comprobante_url
            pago.comprobante_url = uploaded["url"]
            pago.updated_at = utc_now()
            pago.updated_by = actor.id
            await cls._commit(db_session)
        except Exception:
            await CloudinaryService.safe_delete_image(uploaded["url"])
            raise

        if anterior:
            await CloudinaryService.safe_delete_image(anterior)
        logger.info("Comprobante de pago subido: pago_id=%s actor_id=%s", pago_id, actor.id)
        return await cls._reload(db_session, pago_id, actor)
