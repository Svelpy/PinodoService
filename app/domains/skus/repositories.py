from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.skus.models import SKU_TALLA_ORDER, Sku


class SkuRepository:
    """Acceso a datos de SKUs. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        sku_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> Sku | None:
        """Con load_detail carga la talla que embebe el Detail."""
        statement = select(Sku).where(Sku.id == sku_id)
        if not include_deleted:
            statement = statement.where(Sku.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()
        if load_detail:
            statement = statement.options(selectinload(Sku.talla))

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_by_color_and_talla(
        self,
        producto_color_id: UUID,
        talla_id: UUID,
        *,
        exclude_id: UUID | None = None,
    ) -> Sku | None:
        statement = select(Sku).where(
            Sku.producto_color_id == producto_color_id,
            Sku.talla_id == talla_id,
            Sku.is_deleted.is_(False),
        )
        if exclude_id is not None:
            statement = statement.where(Sku.id != exclude_id)

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_by_codigo_barras(
        self,
        codigo_barras: str,
        *,
        exclude_id: UUID | None = None,
    ) -> Sku | None:
        statement = select(Sku).where(
            Sku.codigo_barras == codigo_barras,
            Sku.is_deleted.is_(False),
        )
        if exclude_id is not None:
            statement = statement.where(Sku.id != exclude_id)

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def soft_delete_by_producto_color_ids(
        self,
        producto_color_ids: Sequence[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> int:
        """Elimina lógicamente los SKUs activos de esos colores. Devuelve cuántos marcó."""
        if not producto_color_ids:
            return 0
        result = await self.db_session.execute(
            update(Sku)
            .where(
                Sku.producto_color_id.in_(producto_color_ids),
                Sku.is_deleted.is_(False),
            )
            .values(
                is_deleted=True,
                deleted_at=now,
                deleted_by=actor_id,
                updated_at=now,
                updated_by=actor_id,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        producto_color_id: UUID | None = None,
        talla_id: UUID | None = None,
        is_visible: bool | None = None,
        bajo_minimo: bool | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[Sku], int]:
        """
        Listado paginado con la talla cargada para el ListItem, ordenado por color
        y, dentro de cada color, por el orden de las tallas. bajo_minimo filtra
        los SKUs con stock igual o menor al mínimo.
        """
        filters = []
        if not include_deleted:
            filters.append(Sku.is_deleted.is_(False))
        if producto_color_id is not None:
            filters.append(Sku.producto_color_id == producto_color_id)
        if talla_id is not None:
            filters.append(Sku.talla_id == talla_id)
        if is_visible is not None:
            filters.append(Sku.is_visible.is_(is_visible))
        if bajo_minimo is not None:
            cantidad = Sku.stock["cantidad"].as_integer()
            minimo = Sku.stock["minimo"].as_integer()
            filters.append(cantidad <= minimo if bajo_minimo else cantidad > minimo)

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Sku).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Sku)
            .where(*filters)
            .options(selectinload(Sku.talla))
            .order_by(Sku.producto_color_id, *SKU_TALLA_ORDER)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    def add(self, sku: Sku) -> None:
        self.db_session.add(sku)
