from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.skus.models import Sku
from app.domains.ventas.models import Venta
from app.shared.enums import MotivoAjuste, TipoMovimiento


class MovimientoInventarioRepository:
    """
    Acceso a datos del kardex. Los movimientos solo se agregan: no hay
    operaciones de edición ni de eliminación. No hace commit.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    @staticmethod
    def _with_embebidos(statement: Select) -> Select:
        """Carga el SKU y la venta del ListItem y el Detail, sin los eliminados."""
        return statement.options(
            selectinload(MovimientoInventario.sku.and_(Sku.is_deleted.is_(False))),
            selectinload(MovimientoInventario.venta.and_(Venta.is_deleted.is_(False))),
        )

    async def get_by_id(
        self,
        movimiento_id: UUID,
        *,
        load_detail: bool = False,
    ) -> MovimientoInventario | None:
        statement = select(MovimientoInventario).where(
            MovimientoInventario.id == movimiento_id,
            MovimientoInventario.is_deleted.is_(False),
        )
        if load_detail:
            statement = self._with_embebidos(statement)
        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def find_many(
        self,
        *,
        offset: int,
        limit: int,
        sku_id: UUID | None = None,
        tipo: TipoMovimiento | None = None,
        motivo: MotivoAjuste | None = None,
        venta_id: UUID | None = None,
        created_by: UUID | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> tuple[list[MovimientoInventario], int]:
        """
        Listado paginado, del movimiento más reciente al más antiguo, con sus
        embebidos. desde es inclusivo y hasta exclusivo, sobre created_at.
        """
        filters: list[ColumnElement[bool]] = [MovimientoInventario.is_deleted.is_(False)]
        if sku_id is not None:
            filters.append(MovimientoInventario.sku_id == sku_id)
        if tipo is not None:
            filters.append(MovimientoInventario.tipo == tipo)
        if motivo is not None:
            filters.append(MovimientoInventario.motivo == motivo)
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
            self._with_embebidos(
                select(MovimientoInventario)
                .where(*filters)
                .order_by(MovimientoInventario.created_at.desc(), MovimientoInventario.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        return list(result.scalars().all()), total

    async def list_by_ids(self, movimiento_ids: list[UUID]) -> list[MovimientoInventario]:
        """Movimientos con sus embebidos, en el orden de movimiento_ids."""
        if not movimiento_ids:
            return []
        result = await self.db_session.execute(
            self._with_embebidos(
                select(MovimientoInventario).where(
                    MovimientoInventario.id.in_(movimiento_ids),
                    MovimientoInventario.is_deleted.is_(False),
                )
            )
        )
        por_id = {movimiento.id: movimiento for movimiento in result.scalars().all()}
        return [por_id[movimiento_id] for movimiento_id in movimiento_ids if movimiento_id in por_id]

    def add(self, movimiento: MovimientoInventario) -> None:
        self.db_session.add(movimiento)
