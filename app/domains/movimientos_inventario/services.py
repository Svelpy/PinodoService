from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.movimientos_inventario.repositories import (
    MovimientoInventarioRepository,
    MovimientoRow,
)
from app.domains.movimientos_inventario.schemas import (
    MovimientoInventarioResponse,
    MovimientoOrigen,
    SkuCosto,
    SkuResumen,
)
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.shared.enums import MotivoAjuste, TipoMovimiento
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)

CENTAVO = Decimal("0.01")


class MovimientoInventarioService:
    """
    Kardex: el stock de un SKU solo cambia mediante registrar(), que agrega el
    movimiento, actualiza stock.cantidad y recalcula el costo promedio. Lo
    usan los documentos que mueven stock: los ajustes y las ventas.

    No importa SkuService, VentaService ni AjusteInventarioService: todos lo
    usan para mover stock.
    """

    @staticmethod
    def _validation_error(field_name: str, message: str) -> AppException:
        return AppException(message, 422, ErrorCode.VALIDATION_ERROR, {field_name: message})

    @staticmethod
    def local_start(day: date, settings: Settings) -> datetime:
        """Inicio del día day en la zona horaria de la tienda (igual que VentaService)."""
        tz = timezone(timedelta(hours=settings.TIMEZONE_OFFSET_HOURS))
        return datetime.combine(day, time.min, tzinfo=tz)

    @classmethod
    def validate_page(cls, page: int, per_page: int) -> None:
        if page < 1:
            raise cls._validation_error("page", "La página debe ser mayor o igual a 1.")
        if per_page < 1 or per_page > 100:
            raise cls._validation_error("per_page", "La cantidad por página debe estar entre 1 y 100.")

    @classmethod
    def validate_rango(cls, desde: date | None, hasta: date | None) -> None:
        if desde is not None and hasta is not None and desde > hasta:
            raise cls._validation_error("desde", "La fecha desde no puede ser posterior a hasta.")

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
        ajuste_id: UUID | None = None,
        venta_id: UUID | None = None,
        field_name: str = "cantidad",
    ) -> MovimientoInventario:
        """
        Mueve el stock del SKU (que debe estar bloqueado) y agrega su
        movimiento, que apunta a su documento: ajuste_id en un AJUSTE,
        venta_id en una VENTA o ANULACION. No hace commit.

        Con costo_unitario, lo que entra recalcula el costo promedio: la carga
        INICIAL, una RECEPCION y una ANULACION (sin costo conocido, una
        ANULACION usa el promedio actual). Sin él, el movimiento usa el costo
        actual y no lo cambia. Responde 409 con stock_actual si el stock
        quedaría negativo.
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
            ajuste_id=ajuste_id,
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
    def item(row: MovimientoRow) -> MovimientoInventarioResponse:
        """Fila del kardex lista para mostrar, a partir de una fila del repository."""
        movimiento, codigo_barras, producto_id, producto_nombre, color_nombre, talla = row
        if movimiento.ajuste is not None:
            origen = MovimientoOrigen(
                tipo="AJUSTE",
                id=movimiento.ajuste.id,
                numero=movimiento.ajuste.numero,
                motivo=movimiento.ajuste.motivo,
            )
        else:
            origen = MovimientoOrigen(
                tipo="VENTA",
                id=movimiento.venta.id,
                numero=movimiento.venta.numero,
                motivo=None,
            )
        costo_unitario = Decimal(movimiento.costo_unitario)
        costo_promedio = Decimal(movimiento.costo_promedio)
        return MovimientoInventarioResponse(
            id=movimiento.id,
            tipo=movimiento.tipo,
            cantidad=movimiento.cantidad,
            saldo=movimiento.saldo,
            costo_unitario=costo_unitario,
            costo_total=costo_unitario * movimiento.cantidad,
            costo_promedio=costo_promedio,
            saldo_valor=costo_promedio * movimiento.saldo,
            created_at=movimiento.created_at,
            created_by=movimiento.created_by,
            sku=SkuResumen(
                id=movimiento.sku_id,
                codigo_barras=codigo_barras,
                producto_id=producto_id,
                producto_nombre=producto_nombre,
                color_nombre=color_nombre,
                talla_etiqueta=talla,
            ),
            origen=origen,
        )

    @classmethod
    async def get(cls, db_session: AsyncSession, movimiento_id: UUID) -> MovimientoInventarioResponse:
        row = await MovimientoInventarioRepository(db_session).get_by_id(movimiento_id)
        if row is None:
            raise AppException("Movimiento no encontrado.", 404, ErrorCode.RESOURCE_NOT_FOUND)
        return cls.item(row)

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
        ajuste_id: UUID | None = None,
        venta_id: UUID | None = None,
        created_by: UUID | None = None,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> PaginatedResponse[MovimientoInventarioResponse]:
        """desde y hasta son fechas de la tienda, ambas incluidas."""
        cls.validate_page(page, per_page)
        cls.validate_rango(desde, hasta)

        rows, total = await MovimientoInventarioRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            sku_id=sku_id,
            tipo=tipo,
            motivo=motivo,
            ajuste_id=ajuste_id,
            venta_id=venta_id,
            created_by=created_by,
            desde=cls.local_start(desde, settings) if desde is not None else None,
            hasta=cls.local_start(hasta + timedelta(days=1), settings) if hasta is not None else None,
        )
        return PaginatedResponse[MovimientoInventarioResponse](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=[cls.item(row) for row in rows],
        )

    @classmethod
    async def list_by_ajuste(cls, db_session: AsyncSession, ajuste_id: UUID) -> list[MovimientoInventarioResponse]:
        rows = await MovimientoInventarioRepository(db_session).list_by_ajuste(ajuste_id)
        return [cls.item(row) for row in rows]

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
        cls.validate_page(page, per_page)
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
