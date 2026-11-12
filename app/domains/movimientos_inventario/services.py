from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.movimientos_inventario.repositories import MovimientoInventarioRepository
from app.domains.movimientos_inventario.schemas import (
    AjusteInventarioCreate,
    AjusteInventarioResultado,
    MovimientoInventarioListItem,
    SkuCosto,
)
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.shared.enums import MotivoAjuste, TipoMovimiento
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)

CENTAVO = Decimal("0.01")
# Motivos cuya cantidad son unidades que salen: el cliente las envía positivas.
MOTIVOS_DE_SALIDA = frozenset({MotivoAjuste.MERMA, MotivoAjuste.ROBO_PERDIDA})


class MovimientoInventarioService:
    """
    Kardex: el stock de un SKU solo cambia mediante registrar(), que agrega el
    movimiento, actualiza stock.cantidad y recalcula el costo promedio.

    No importa SkuService ni VentaService: ambos lo usan para mover stock.
    """

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
                "El movimiento entra en conflicto con el stock actual del SKU.",
                409,
                ErrorCode.CONFLICT,
            ) from error
        except Exception:
            await db_session.rollback()
            raise

    @staticmethod
    def _local_start(day: date, settings: Settings) -> datetime:
        """Inicio del día day en la zona horaria de la tienda (igual que VentaService)."""
        tz = timezone(timedelta(hours=settings.TIMEZONE_OFFSET_HOURS))
        return datetime.combine(day, time.min, tzinfo=tz)

    # ------------------------------------------------------------------ stock

    @staticmethod
    def costo_promedio(stock: int, costo: Decimal, cantidad: int, costo_unitario: Decimal) -> Decimal:
        """
        Costo promedio ponderado tras entrar cantidad unidades a costo_unitario.
        Sin stock previo, el promedio es el costo de lo que entra.
        """
        if stock <= 0:
            return costo_unitario
        total = Decimal(stock) * costo + Decimal(cantidad) * costo_unitario
        return (total / Decimal(stock + cantidad)).quantize(CENTAVO, rounding=ROUND_HALF_UP)

    @classmethod
    def registrar(
        cls,
        db_session: AsyncSession,
        sku: Sku,
        tipo: TipoMovimiento,
        cantidad: int,
        actor_id: UUID,
        now: datetime,
        *,
        costo_unitario: Decimal | None = None,
        motivo: MotivoAjuste | None = None,
        nota: str | None = None,
        venta_id: UUID | None = None,
        field_name: str = "cantidad",
    ) -> MovimientoInventario:
        """
        Mueve el stock del SKU (que debe estar bloqueado) y agrega su
        movimiento. No hace commit.

        Con costo_unitario, lo que entra recalcula el costo promedio: INICIAL,
        una RECEPCION y una ANULACION (sin costo conocido, una ANULACION usa el
        promedio actual). Sin él, el movimiento usa el costo actual y no lo
        cambia.
        Responde 409 con stock_actual si el stock quedaría negativo.
        """
        actual = int(sku.stock.get("cantidad", 0))
        saldo = actual + cantidad
        if saldo < 0:
            message = f"El stock quedaría en {saldo}: hay {actual} y el movimiento es {cantidad}."
            raise AppException(
                message,
                409,
                ErrorCode.CONFLICT,
                {field_name: message, "stock_actual": actual},
            )

        costo_actual = Decimal(sku.costo)
        if costo_unitario is not None and cantidad > 0:
            costo = costo_unitario
            sku.costo = cls.costo_promedio(actual, costo_actual, cantidad, costo_unitario)
        else:
            costo = costo_actual

        sku.stock = {**sku.stock, "cantidad": saldo, "actualizado": now.isoformat()}
        sku.updated_at = now
        sku.updated_by = actor_id

        movimiento = MovimientoInventario(
            sku_id=sku.id,
            tipo=tipo,
            cantidad=cantidad,
            saldo=saldo,
            costo_unitario=costo,
            costo_promedio=sku.costo,
            motivo=motivo,
            nota=nota,
            venta_id=venta_id,
            created_at=now,
            created_by=actor_id,
            updated_at=now,
            updated_by=actor_id,
        )
        MovimientoInventarioRepository(db_session).add(movimiento)
        return movimiento

    # ------------------------------------------------------------------ lectura

    @staticmethod
    async def get(
        db_session: AsyncSession,
        movimiento_id: UUID,
        *,
        load_detail: bool = False,
    ) -> MovimientoInventario:
        movimiento = await MovimientoInventarioRepository(db_session).get_by_id(
            movimiento_id,
            load_detail=load_detail,
        )
        if movimiento is None:
            raise AppException("Movimiento no encontrado.", 404, ErrorCode.RESOURCE_NOT_FOUND)
        return movimiento

    @classmethod
    def _validate_page(cls, page: int, per_page: int) -> None:
        if page < 1:
            raise cls._validation_error("page", "La página debe ser mayor o igual a 1.")
        if per_page < 1 or per_page > 100:
            raise cls._validation_error("per_page", "La cantidad por página debe estar entre 1 y 100.")

    @classmethod
    async def list(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        *,
        page: int = 1,
        per_page: int = 20,
        sku_id: UUID | None = None,
        tipo: TipoMovimiento | None = None,
        motivo: MotivoAjuste | None = None,
        venta_id: UUID | None = None,
        created_by: UUID | None = None,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> PaginatedResponse[MovimientoInventario]:
        """desde y hasta son fechas de la tienda, ambas incluidas."""
        cls._validate_page(page, per_page)
        if desde is not None and hasta is not None and desde > hasta:
            raise cls._validation_error("desde", "La fecha desde no puede ser posterior a hasta.")

        movimientos, total = await MovimientoInventarioRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            sku_id=sku_id,
            tipo=tipo,
            motivo=motivo,
            venta_id=venta_id,
            created_by=created_by,
            desde=cls._local_start(desde, settings) if desde is not None else None,
            hasta=cls._local_start(hasta + timedelta(days=1), settings) if hasta is not None else None,
        )
        return PaginatedResponse[MovimientoInventario](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=movimientos,
        )

    @classmethod
    async def list_costos(
        cls,
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        nombre: str | None = None,
        codigo_barras: str | None = None,
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
    ) -> PaginatedResponse[SkuCosto]:
        """Stock, costo y valor de los SKUs activos, en el orden del inventario."""
        cls._validate_page(page, per_page)
        rows, total = await SkuRepository(db_session).list_inventario(
            offset=(page - 1) * per_page,
            limit=per_page,
            # Solo decide si una rebaja sigue vigente, y aquí no se filtra por rebaja.
            today=utc_now().date(),
            nombre=nombre,
            codigo_barras=codigo_barras,
            producto_id=producto_id,
            color_id=color_id,
        )
        items = []
        for sku, producto_id_row, producto_nombre, _, color_nombre, _, talla in rows:
            cantidad = int(sku.stock.get("cantidad", 0))
            costo = Decimal(sku.costo)
            items.append(
                SkuCosto(
                    sku_id=sku.id,
                    producto_id=producto_id_row,
                    producto_nombre=producto_nombre,
                    color_nombre=color_nombre,
                    talla_etiqueta=talla,
                    codigo_barras=sku.codigo_barras,
                    cantidad=cantidad,
                    costo=costo,
                    valor=costo * cantidad,
                )
            )
        return PaginatedResponse[SkuCosto](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=items,
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
    async def ajustar(
        cls,
        db_session: AsyncSession,
        data: AjusteInventarioCreate,
        actor_id: UUID,
    ) -> AjusteInventarioResultado:
        """
        Aplica un ajuste manual a todos sus SKUs o a ninguno. Los SKUs se
        bloquean en orden de id, para no pisar lo que mueven las ventas al
        mismo tiempo. Un SKU inexistente o eliminado responde 422; si algún
        stock quedaría negativo, 409 con stock_actual y no se guarda nada. En
        un CONTEO, los SKUs cuyo stock ya coincide no dejan movimiento.
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
        movimiento_ids: list[UUID] = []
        sin_diferencia: list[UUID] = []
        for index, item in enumerate(data.items):
            sku = skus[item.sku_id]
            cantidad = cls._cantidad(data, index, int(sku.stock.get("cantidad", 0)))
            if cantidad == 0:
                sin_diferencia.append(sku.id)
                continue
            movimiento = cls.registrar(
                db_session,
                sku,
                TipoMovimiento.AJUSTE,
                cantidad,
                actor_id,
                now,
                costo_unitario=item.costo_unitario,
                motivo=data.motivo,
                nota=data.nota,
                field_name=f"items -> {index}",
            )
            movimiento_ids.append(movimiento.id)

        if movimiento_ids:
            await cls._commit(db_session)
        logger.info(
            "Ajuste de inventario: motivo=%s movimientos=%s sin_diferencia=%s actor_id=%s",
            data.motivo,
            len(movimiento_ids),
            len(sin_diferencia),
            actor_id,
        )
        db_session.expire_all()
        movimientos = await MovimientoInventarioRepository(db_session).list_by_ids(movimiento_ids)
        return AjusteInventarioResultado(
            motivo=data.motivo,
            movimientos=[MovimientoInventarioListItem.model_validate(m) for m in movimientos],
            sin_diferencia=sin_diferencia,
        )
