from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.ajustes_inventario.models import AjusteInventario
from app.domains.ajustes_inventario.repositories import AjusteInventarioRepository, AjusteRow
from app.domains.ajustes_inventario.schemas import (
    AjusteInventarioCreate,
    AjusteInventarioDetail,
    AjusteInventarioResponse,
    AjusteInventarioResultado,
)
from app.domains.movimientos_inventario.services import MovimientoInventarioService
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.shared.enums import MotivoAjuste, TipoMovimiento
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)

# Motivos cuya cantidad son unidades que salen: el cliente las envía positivas.
MOTIVOS_DE_SALIDA = frozenset({MotivoAjuste.MERMA, MotivoAjuste.ROBO_PERDIDA})


def nuevo_documento(
    db_session: AsyncSession,
    motivo: MotivoAjuste,
    actor_id: UUID | None,
    now: datetime,
    *,
    nota: str | None = None,
) -> AjusteInventario:
    """Añade a la sesión un documento de ajuste. Su número lo asigna la base de datos."""
    ajuste = AjusteInventario(
        motivo=motivo,
        nota=nota,
        created_at=now,
        created_by=actor_id,
        updated_at=now,
        updated_by=actor_id,
    )
    AjusteInventarioRepository(db_session).add(ajuste)
    return ajuste


class CargaInicial:
    """
    Documento INICIAL de una petición que crea SKUs (producto, color o SKU
    suelto). Se crea con el primer SKU que trae stock, así una petición genera
    un solo documento con todas sus líneas, o ninguno si nada trae stock.
    """

    def __init__(self, db_session: AsyncSession, actor_id: UUID, now: datetime) -> None:
        self.db_session = db_session
        self.actor_id = actor_id
        self.now = now
        self.ajuste: AjusteInventario | None = None

    def registrar(self, sku: Sku, cantidad: int, costo: Decimal) -> None:
        """Sube el stock del SKU nuevo a cantidad, a su costo. No hace commit."""
        if self.ajuste is None:
            self.ajuste = nuevo_documento(self.db_session, MotivoAjuste.INICIAL, self.actor_id, self.now)
        MovimientoInventarioService.registrar(
            self.db_session,
            sku,
            TipoMovimiento.AJUSTE,
            cantidad,
            self.actor_id,
            self.now,
            costo_unitario=costo,
            ajuste_id=self.ajuste.id,
        )


class AjusteInventarioService:
    """Documentos de ajuste: crean movimientos AJUSTE en el kardex y se consultan."""

    @staticmethod
    def _validation_error(field_name: str, message: str) -> AppException:
        return AppException(message, 422, ErrorCode.VALIDATION_ERROR, {field_name: message})

    @staticmethod
    async def _commit(db_session: AsyncSession) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise AppException(
                "El ajuste entra en conflicto con el stock actual de un SKU.",
                409,
                ErrorCode.CONFLICT,
            ) from error
        except Exception:
            await db_session.rollback()
            raise

    @staticmethod
    def _response(row: AjusteRow) -> AjusteInventarioResponse:
        ajuste, items, unidades, valor = row
        return AjusteInventarioResponse(
            id=ajuste.id,
            numero=ajuste.numero,
            motivo=ajuste.motivo,
            nota=ajuste.nota,
            items=int(items),
            unidades=int(unidades),
            valor=Decimal(valor),
            created_at=ajuste.created_at,
            created_by=ajuste.created_by,
        )

    # ------------------------------------------------------------------ lectura

    @classmethod
    async def get(cls, db_session: AsyncSession, ajuste_id: UUID) -> AjusteInventarioDetail:
        row = await AjusteInventarioRepository(db_session).get_by_id(ajuste_id)
        if row is None:
            raise AppException("Ajuste no encontrado.", 404, ErrorCode.RESOURCE_NOT_FOUND)
        return AjusteInventarioDetail(
            **cls._response(row).model_dump(),
            movimientos=await MovimientoInventarioService.list_by_ajuste(db_session, ajuste_id),
        )

    @classmethod
    async def list(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        *,
        page: int = 1,
        per_page: int = 20,
        motivo: MotivoAjuste | None = None,
        created_by: UUID | None = None,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> PaginatedResponse[AjusteInventarioResponse]:
        """desde y hasta son fechas de la tienda, ambas incluidas."""
        MovimientoInventarioService.validate_page(page, per_page)
        MovimientoInventarioService.validate_rango(desde, hasta)
        local_start = MovimientoInventarioService.local_start

        rows, total = await AjusteInventarioRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            motivo=motivo,
            created_by=created_by,
            desde=local_start(desde, settings) if desde is not None else None,
            hasta=local_start(hasta + timedelta(days=1), settings) if hasta is not None else None,
        )
        return PaginatedResponse[AjusteInventarioResponse](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=[cls._response(row) for row in rows],
        )

    # ------------------------------------------------------------------ escritura

    @staticmethod
    def _cantidad(data: AjusteInventarioCreate, index: int, actual: int) -> int:
        """Cantidad firmada del movimiento: + entra, − sale; 0 si no cambia."""
        item = data.items[index]
        if data.motivo == MotivoAjuste.CONTEO:
            return item.cantidad_contada - actual
        if data.motivo in MOTIVOS_DE_SALIDA:
            return -item.cantidad
        return item.cantidad

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: AjusteInventarioCreate,
        actor_id: UUID,
    ) -> AjusteInventarioResultado:
        """
        Crea el documento y aplica el ajuste a todos sus SKUs o a ninguno. Los
        SKUs se bloquean en orden de id, para no pisar lo que mueven las
        ventas al mismo tiempo. Un SKU inexistente o eliminado responde 422;
        si algún stock quedaría negativo, 409 con stock_actual y no se guarda
        nada. En un CONTEO, los SKUs cuyo stock ya coincide no dejan línea, y
        si ninguno cambia no se crea el documento.
        """
        skus = {
            sku.id: sku
            for sku in await SkuRepository(db_session).list_active_by_ids(
                [item.sku_id for item in data.items],
                for_update=True,
            )
        }
        for index, item in enumerate(data.items):
            if item.sku_id not in skus:
                raise cls._validation_error(f"items -> {index} -> sku_id", "El SKU no existe.")

        now = utc_now()
        cambios: list[tuple[int, Sku, int]] = []
        sin_diferencia: list[UUID] = []
        for index, item in enumerate(data.items):
            sku = skus[item.sku_id]
            cantidad = cls._cantidad(data, index, int(sku.stock.get("cantidad", 0)))
            if cantidad == 0:
                sin_diferencia.append(sku.id)
            else:
                cambios.append((index, sku, cantidad))

        if not cambios:
            logger.info("Conteo sin diferencias: skus=%s actor_id=%s", len(sin_diferencia), actor_id)
            return AjusteInventarioResultado(ajuste=None, sin_diferencia=sin_diferencia)

        ajuste = nuevo_documento(db_session, data.motivo, actor_id, now, nota=data.nota)
        for index, sku, cantidad in cambios:
            MovimientoInventarioService.registrar(
                db_session,
                sku,
                TipoMovimiento.AJUSTE,
                cantidad,
                actor_id,
                now,
                costo_unitario=data.items[index].costo_unitario,
                ajuste_id=ajuste.id,
                field_name=f"items -> {index}",
            )
        await cls._commit(db_session)

        ajuste_id = ajuste.id
        logger.info(
            "Ajuste de inventario: ajuste_id=%s motivo=%s lineas=%s sin_diferencia=%s actor_id=%s",
            ajuste_id,
            data.motivo,
            len(cambios),
            len(sin_diferencia),
            actor_id,
        )
        db_session.expire_all()
        return AjusteInventarioResultado(
            ajuste=await cls.get(db_session, ajuste_id),
            sin_diferencia=sin_diferencia,
        )
