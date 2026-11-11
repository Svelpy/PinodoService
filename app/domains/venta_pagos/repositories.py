from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, false, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.venta_pagos.models import VentaPago
from app.domains.ventas.models import Venta
from app.shared.enums import MetodoPago


@dataclass(frozen=True)
class VentaPagoScope:
    """
    Pagos que puede ver o modificar un actor: los de las ventas de su alcance
    (AGENTS.md §14). La resolución por rol vive en el service. Vacío = ninguno.
    """

    all: bool = False
    venta_created_by: UUID | None = None

    def condition(self) -> ColumnElement[bool]:
        if self.all:
            return true()
        if self.venta_created_by is not None:
            return Venta.created_by == self.venta_created_by
        return false()


class VentaPagoRepository:
    """Acceso a datos de los pagos de venta. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        pago_id: UUID,
        *,
        scope: VentaPagoScope,
        for_update: bool = False,
    ) -> VentaPago | None:
        statement = (
            select(VentaPago)
            .join(Venta, VentaPago.venta_id == Venta.id)
            .where(
                VentaPago.id == pago_id,
                VentaPago.is_deleted.is_(False),
                Venta.is_deleted.is_(False),
                scope.condition(),
            )
        )
        if for_update:
            statement = statement.with_for_update(of=VentaPago)

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def find_many(
        self,
        *,
        offset: int,
        limit: int,
        scope: VentaPagoScope,
        venta_id: UUID | None = None,
        metodo: MetodoPago | None = None,
        created_by: UUID | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> tuple[list[VentaPago], int]:
        """
        Listado paginado, del pago más reciente al más antiguo. desde es
        inclusivo y hasta exclusivo, ambos sobre created_at del pago.
        """
        filters: list[ColumnElement[bool]] = [
            VentaPago.is_deleted.is_(False),
            Venta.is_deleted.is_(False),
            scope.condition(),
        ]
        if venta_id is not None:
            filters.append(VentaPago.venta_id == venta_id)
        if metodo is not None:
            filters.append(VentaPago.metodo == metodo)
        if created_by is not None:
            filters.append(VentaPago.created_by == created_by)
        if desde is not None:
            filters.append(VentaPago.created_at >= desde)
        if hasta is not None:
            filters.append(VentaPago.created_at < hasta)

        total_result = await self.db_session.execute(
            select(func.count())
            .select_from(VentaPago)
            .join(Venta, VentaPago.venta_id == Venta.id)
            .where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(VentaPago)
            .join(Venta, VentaPago.venta_id == Venta.id)
            .where(*filters)
            .order_by(VentaPago.created_at.desc(), VentaPago.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    def add(self, pago: VentaPago) -> None:
        self.db_session.add(pago)
