from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.ajustes_inventario.models import AjusteInventario
from app.domains.colores.models import Color
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.domains.skus.models import Sku
from app.domains.tallas.models import Talla
from app.shared.enums import MotivoAjuste, TipoMovimiento

# Fila del kardex: (movimiento, codigo_barras, producto_id, producto_nombre, color_nombre, talla_etiqueta)
MovimientoRow = tuple[Any, ...]


class MovimientoInventarioRepository:
    """
    Acceso a datos del kardex. Los movimientos solo se agregan: no hay
    operaciones de edición ni de eliminación. No hace commit.

    Las lecturas devuelven cada movimiento con los nombres de su prenda y su
    documento de origen cargado. Los nombres no filtran eliminados: la
    historia del kardex se conserva aunque la prenda ya no esté en el catálogo.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    @staticmethod
    def _select() -> Select:
        return (
            select(
                MovimientoInventario,
                Sku.codigo_barras,
                Producto.id,
                Producto.nombre,
                Color.nombre,
                Talla.etiqueta,
            )
            .join(Sku, MovimientoInventario.sku_id == Sku.id)
            .join(ProductoColor, Sku.producto_color_id == ProductoColor.id)
            .join(Producto, ProductoColor.producto_id == Producto.id)
            .join(Color, ProductoColor.color_id == Color.id)
            .join(Talla, Sku.talla_id == Talla.id)
            .options(
                selectinload(MovimientoInventario.ajuste),
                selectinload(MovimientoInventario.venta),
            )
            .where(MovimientoInventario.is_deleted.is_(False))
        )

    async def get_by_id(self, movimiento_id: UUID) -> MovimientoRow | None:
        result = await self.db_session.execute(
            self._select().where(MovimientoInventario.id == movimiento_id)
        )
        row = result.first()
        return tuple(row) if row is not None else None

    async def find_many(
        self,
        *,
        offset: int,
        limit: int,
        sku_id: UUID | None = None,
        tipo: TipoMovimiento | None = None,
        motivo: MotivoAjuste | None = None,
        ajuste_id: UUID | None = None,
        venta_id: UUID | None = None,
        created_by: UUID | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> tuple[list[MovimientoRow], int]:
        """
        Listado paginado, del movimiento más reciente al más antiguo. desde es
        inclusivo y hasta exclusivo, sobre created_at. motivo filtra por el
        motivo del documento de ajuste.
        """
        filters: list[ColumnElement[bool]] = [MovimientoInventario.is_deleted.is_(False)]
        if sku_id is not None:
            filters.append(MovimientoInventario.sku_id == sku_id)
        if tipo is not None:
            filters.append(MovimientoInventario.tipo == tipo)
        if motivo is not None:
            filters.append(
                MovimientoInventario.ajuste_id.in_(
                    select(AjusteInventario.id).where(AjusteInventario.motivo == motivo)
                )
            )
        if ajuste_id is not None:
            filters.append(MovimientoInventario.ajuste_id == ajuste_id)
        if venta_id is not None:
            filters.append(MovimientoInventario.venta_id == venta_id)
        if created_by is not None:
            filters.append(MovimientoInventario.created_by == created_by)
        if desde is not None:
            filters.append(MovimientoInventario.created_at >= desde)
        if hasta is not None:
            filters.append(MovimientoInventario.created_at < hasta)

        total_result = await self.db_session.execute(
            select(func.count()).select_from(MovimientoInventario).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            self._select()
            .where(*filters)
            .order_by(MovimientoInventario.created_at.desc(), MovimientoInventario.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in result.all()], total

    async def list_by_ajuste(self, ajuste_id: UUID) -> list[MovimientoRow]:
        """Líneas de un documento de ajuste, ordenadas por producto, color y talla."""
        result = await self.db_session.execute(
            self._select()
            .where(MovimientoInventario.ajuste_id == ajuste_id)
            .order_by(Producto.nombre, Color.nombre, Talla.created_at, Sku.id)
        )
        return [tuple(row) for row in result.all()]

    def add(self, movimiento: MovimientoInventario) -> None:
        self.db_session.add(movimiento)
