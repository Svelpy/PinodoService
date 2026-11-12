from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, exists, false, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.venta_items.models import VentaItem
from app.domains.venta_pagos.models import VentaPago
from app.domains.ventas.models import Venta
from app.shared.enums import CanalVenta, EstadoVenta, MetodoPago


@dataclass(frozen=True)
class VentaScope:
    """
    Filas que puede ver o modificar un actor (AGENTS.md §14). La resolución por
    rol vive en el service; aquí solo se traduce a WHERE. Vacío = ninguna fila.
    """

    all: bool = False
    created_by: UUID | None = None

    def condition(self) -> ColumnElement[bool]:
        if self.all:
            return true()
        if self.created_by is not None:
            return Venta.created_by == self.created_by
        return false()


class VentaRepository:
    """Acceso a datos de ventas. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        venta_id: UUID,
        *,
        scope: VentaScope,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> Venta | None:
        """Con load_detail carga los ítems y pagos activos que embebe el Detail."""
        statement = select(Venta).where(
            Venta.id == venta_id,
            Venta.is_deleted.is_(False),
            scope.condition(),
        )
        if for_update:
            statement = statement.with_for_update(of=Venta)
        if load_detail:
            statement = statement.options(
                selectinload(Venta.items.and_(VentaItem.is_deleted.is_(False))),
                selectinload(Venta.pagos.and_(VentaPago.is_deleted.is_(False))),
            )

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    def _list_filters(
        *,
        scope: VentaScope,
        estado: EstadoVenta | None = None,
        canal: CanalVenta | None = None,
        metodo_pago: MetodoPago | None = None,
        created_by: UUID | None = None,
        numero: int | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[ColumnElement[bool]]:
        filters = [Venta.is_deleted.is_(False), scope.condition()]
        if estado is not None:
            filters.append(Venta.estado == estado)
        if canal is not None:
            filters.append(Venta.canal == canal)
        if metodo_pago is not None:
            # Ventas con al menos un pago por ese método (pueden tener pagos mixtos).
            filters.append(
                exists().where(
                    VentaPago.venta_id == Venta.id,
                    VentaPago.metodo == metodo_pago,
                    VentaPago.is_deleted.is_(False),
                )
            )
        if created_by is not None:
            filters.append(Venta.created_by == created_by)
        if numero is not None:
            filters.append(Venta.numero == numero)
        if desde is not None:
            filters.append(Venta.created_at >= desde)
        if hasta is not None:
            filters.append(Venta.created_at < hasta)
        return filters

    async def find_many(
        self,
        *,
        offset: int,
        limit: int,
        scope: VentaScope,
        estado: EstadoVenta | None = None,
        canal: CanalVenta | None = None,
        metodo_pago: MetodoPago | None = None,
        created_by: UUID | None = None,
        numero: int | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> tuple[list[Venta], int]:
        """
        Listado paginado, de la venta más reciente a la más antigua. desde es
        inclusivo y hasta exclusivo, ambos sobre created_at.
        """
        filters = self._list_filters(
            scope=scope,
            estado=estado,
            canal=canal,
            metodo_pago=metodo_pago,
            created_by=created_by,
            numero=numero,
            desde=desde,
            hasta=hasta,
        )

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Venta).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Venta)
            .where(*filters)
            .order_by(Venta.numero.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def sum_totales_by_estado(
        self,
        *,
        scope: VentaScope,
        canal: CanalVenta | None = None,
        created_by: UUID | None = None,
        numero: int | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> dict[EstadoVenta, Decimal]:
        """
        Suma de total de TODAS las ventas filtradas (sin offset ni limit), por
        estado. Los estados sin ventas no aparecen.
        """
        filters = self._list_filters(
            scope=scope,
            canal=canal,
            created_by=created_by,
            numero=numero,
            desde=desde,
            hasta=hasta,
        )
        result = await self.db_session.execute(
            select(Venta.estado, func.sum(Venta.total))
            .where(*filters)
            .group_by(Venta.estado)
        )
        return {EstadoVenta(estado): Decimal(total) for estado, total in result.all()}

    async def sum_pagos_by_metodo(
        self,
        *,
        scope: VentaScope,
        estado: EstadoVenta,
        canal: CanalVenta | None = None,
        created_by: UUID | None = None,
        numero: int | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> dict[MetodoPago, Decimal]:
        """
        Suma de los pagos activos de las ventas filtradas en ese estado, por
        método. Los filtros se aplican a la venta, no al pago. Los métodos sin
        pagos no aparecen.
        """
        filters = self._list_filters(
            scope=scope,
            estado=estado,
            canal=canal,
            created_by=created_by,
            numero=numero,
            desde=desde,
            hasta=hasta,
        )
        result = await self.db_session.execute(
            select(VentaPago.metodo, func.sum(VentaPago.monto))
            .join(Venta, VentaPago.venta_id == Venta.id)
            .where(*filters, VentaPago.is_deleted.is_(False))
            .group_by(VentaPago.metodo)
        )
        return {MetodoPago(metodo): Decimal(suma) for metodo, suma in result.all()}

    def add(self, venta: Venta) -> None:
        self.db_session.add(venta)
