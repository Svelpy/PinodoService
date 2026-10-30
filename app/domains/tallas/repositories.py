from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.skus.models import Sku
from app.domains.tallas.models import Talla


class TallaRepository:
    """Acceso a datos de tallas. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        talla_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Talla | None:
        statement = select(Talla).where(Talla.id == talla_id)
        if not include_deleted:
            statement = statement.where(Talla.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_by_etiqueta(
        self,
        etiqueta: str,
        *,
        exclude_id: UUID | None = None,
    ) -> Talla | None:
        """Busca una talla no eliminada con la misma etiqueta, sin distinguir mayúsculas."""
        statement = select(Talla).where(
            func.lower(Talla.etiqueta) == etiqueta.lower(),
            Talla.is_deleted.is_(False),
        )
        if exclude_id is not None:
            statement = statement.where(Talla.id != exclude_id)

        result = await self.db_session.execute(statement)
        return result.scalars().first()

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        include_deleted: bool = False,
    ) -> tuple[list[Talla], int]:
        filters = []
        if not include_deleted:
            filters.append(Talla.is_deleted.is_(False))

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Talla).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Talla)
            .where(*filters)
            .order_by(Talla.created_at, Talla.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def has_active_dependents(self, talla_id: UUID) -> bool:
        """True si algún SKU no eliminado usa la talla."""
        result = await self.db_session.execute(
            select(
                exists().where(
                    Sku.talla_id == talla_id,
                    Sku.is_deleted.is_(False),
                )
            )
        )
        return bool(result.scalar_one())

    def add(self, talla: Talla) -> None:
        self.db_session.add(talla)
