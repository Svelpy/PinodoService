from datetime import date, timedelta
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
from app.domains.venta_pagos.schemas import VentaPagoCreate, VentaPagoUpdate
from app.domains.ventas.services import VentaService
from app.integrations.cloudinary import CloudinaryService
from app.shared.enums import EstadoVenta, MetodoPago
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.services.permissions import VENTA_GLOBAL_SCOPE_ROLES, VENTA_OWN_SCOPE_ROLES


logger = get_logger(__name__)

COMPROBANTES_FOLDER = "comprobantes"


class VentaPagoService:
    """
    Reglas de los pagos de venta.

    - Un pago se registra en una venta PENDIENTE y no supera su saldo; las
      reglas de importe las comparte con VentaService.agregar_pagos.
    - Un pago no se anula ni cambia de monto o método: la devolución se hace
      cancelando la venta completa. Solo se editan la referencia y el
      comprobante.
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
    def _validation_error(field_name: str, message: str) -> AppException:
        return AppException(message, 422, ErrorCode.VALIDATION_ERROR, {field_name: message})

    @staticmethod
    def _conflict(message: str, field_name: str) -> AppException:
        return AppException(message, 409, ErrorCode.CONFLICT, {field_name: message})

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

    @classmethod
    async def list(
        cls,
        db_session: AsyncSession,
        actor: CurrentUser,
        settings: Settings,
        *,
        page: int = 1,
        per_page: int = 20,
        venta_id: UUID | None = None,
        metodo: MetodoPago | None = None,
        created_by: UUID | None = None,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> PaginatedResponse[VentaPago]:
        """desde y hasta son fechas de la tienda sobre la fecha del pago, ambas incluidas."""
        if page < 1:
            raise cls._validation_error("page", "La página debe ser mayor o igual a 1.")
        if per_page < 1 or per_page > 100:
            raise cls._validation_error("per_page", "La cantidad por página debe estar entre 1 y 100.")
        if desde is not None and hasta is not None and desde > hasta:
            raise cls._validation_error("desde", "La fecha desde no puede ser posterior a hasta.")

        pagos, total = await VentaPagoRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            scope=cls._scope_for(actor),
            venta_id=venta_id,
            metodo=metodo,
            created_by=created_by,
            desde=VentaService._local_start(desde, settings) if desde is not None else None,
            hasta=(
                VentaService._local_start(hasta + timedelta(days=1), settings)
                if hasta is not None
                else None
            ),
        )
        return PaginatedResponse[VentaPago](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=pagos,
        )

    # ------------------------------------------------------------------ escritura

    @classmethod
    async def _reload(cls, db_session: AsyncSession, pago_id: UUID, actor: CurrentUser) -> VentaPago:
        # Responde lo mismo que GET /{id}.
        db_session.expire_all()
        return await cls.get(db_session, pago_id, actor)

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: VentaPagoCreate,
        actor: CurrentUser,
    ) -> VentaPago:
        """
        Registra un pago de una venta PENDIENTE: un anticipo o parte de su
        cobro. La venta se bloquea para que dos pagos simultáneos no superen
        su saldo. Una venta fuera del alcance del actor responde 404.
        """
        venta = await VentaService.get(db_session, data.venta_id, actor, for_update=True)
        if venta.estado != EstadoVenta.PENDIENTE:
            raise cls._conflict(
                "Solo se registran pagos en ventas pendientes; una venta confirmada ya está "
                "pagada y una cancelada no admite más pagos.",
                "venta_id",
            )

        now = utc_now()
        [pago] = VentaService.agregar_pagos(
            db_session,
            venta,
            [data],
            actor,
            now,
            field_name="monto",
        )
        venta.updated_at = now
        venta.updated_by = actor.id
        await cls._commit(db_session)

        logger.info(
            "Pago registrado: pago_id=%s venta_id=%s metodo=%s monto=%s actor_id=%s",
            pago.id,
            venta.id,
            pago.metodo,
            pago.monto,
            actor.id,
        )
        return await cls._reload(db_session, pago.id, actor)

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        pago_id: UUID,
        data: VentaPagoUpdate,
        actor: CurrentUser,
    ) -> VentaPago:
        """Solo cambia la referencia; sin cambios responde el pago tal como está."""
        pago = await cls.get(db_session, pago_id, actor, for_update=True)
        cambios = {
            key: value
            for key, value in data.model_dump(exclude_unset=True).items()
            if getattr(pago, key) != value
        }
        if cambios:
            for key, value in cambios.items():
                setattr(pago, key, value)
            pago.updated_at = utc_now()
            pago.updated_by = actor.id
            await cls._commit(db_session)
            logger.info("Pago actualizado: pago_id=%s actor_id=%s", pago_id, actor.id)
        return await cls._reload(db_session, pago_id, actor)

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
