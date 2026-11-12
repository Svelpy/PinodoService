from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, false, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.venta_pagos.models import VentaPago
from app.domains.ventas.models import Venta


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

    def add(self, pago: VentaPago) -> None:
        self.db_session.add(pago)
