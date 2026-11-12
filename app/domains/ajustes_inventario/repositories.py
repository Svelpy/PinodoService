from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ajustes_inventario.models import AjusteInventario
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.shared.enums import MotivoAjuste

# (ajuste, items, unidades, valor)
AjusteRow = tuple[AjusteInventario, int, int, Decimal]


class AjusteInventarioRepository:
    """
    Acceso a datos de los documentos de ajuste. Solo se agregan: no hay
    edición ni eliminación. No hace commit. Las lecturas devuelven cada
    documento con los totales de sus líneas.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    @staticmethod
    def _select() -> Select:
        totales = (
            select(
                MovimientoInventario.ajuste_id.label("ajuste_id"),
                func.count().label("lineas"),
                func.sum(MovimientoInventario.cantidad).label("unidades"),
                func.sum(MovimientoInventario.cantidad * MovimientoInventario.costo_unitario).label("valor"),
            )
            .where(
                MovimientoInventario.ajuste_id.is_not(None),
                MovimientoInventario.is_deleted.is_(False),
            )
            .group_by(MovimientoInventario.ajuste_id)
            .subquery()
        )
        return (
            select(
                AjusteInventario,
                func.coalesce(totales.c.lineas, 0),
                func.coalesce(totales.c.unidades, 0),
                func.coalesce(totales.c.valor, 0),
            )
            .outerjoin(totales, totales.c.ajuste_id == AjusteInventario.id)
            .where(AjusteInventario.is_deleted.is_(False))
        )

    async def get_by_id(self, ajuste_id: UUID) -> AjusteRow | None:
        result = await self.db_session.execute(self._select().where(AjusteInventario.id == ajuste_id))
        row = result.first()
        return tuple(row) if row is not None else None

    async def find_many(
        self,
        *,
        offset: int,
        limit: int,
        motivo: MotivoAjuste | None = None,
        created_by: UUID | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> tuple[list[AjusteRow], int]:
        """Del documento más reciente al más antiguo. desde es inclusivo y hasta exclusivo."""
        filters: list[ColumnElement[bool]] = [AjusteInventario.is_deleted.is_(False)]
        if motivo is not None:
            filters.append(AjusteInventario.motivo == motivo)
        if created_by is not None:
            filters.append(AjusteInventario.created_by == created_by)
        if desde is not None:
            filters.append(AjusteInventario.created_at >= desde)
        if hasta is not None:
            filters.append(AjusteInventario.created_at < hasta)

        total_result = await self.db_session.execute(
            select(func.count()).select_from(AjusteInventario).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            self._select()
            .where(*filters)
            .order_by(AjusteInventario.created_at.desc(), AjusteInventario.numero.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in result.all()], total

    def add(self, ajuste: AjusteInventario) -> None:
        self.db_session.add(ajuste)
