from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.colores.models import Color
from app.domains.producto_colores.models import ProductoColor


class ColorRepository:
    """Acceso a datos de colores. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        color_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Color | None:
        statement = select(Color).where(Color.id == color_id)
        if not include_deleted:
            statement = statement.where(Color.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_by_slug(
        self,
        slug: str,
        *,
        exclude_id: UUID | None = None,
    ) -> Color | None:
        statement = select(Color).where(
            Color.slug == slug,
            Color.is_deleted.is_(False),
        )
        if exclude_id is not None:
            statement = statement.where(Color.id != exclude_id)

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        include_deleted: bool = False,
    ) -> tuple[list[Color], int]:
        filters = []
        if not include_deleted:
            filters.append(Color.is_deleted.is_(False))

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Color).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Color)
            .where(*filters)
            .order_by(Color.nombre, Color.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def has_active_dependents(self, color_id: UUID) -> bool:
        """True si algún producto_color no eliminado usa el color."""
        result = await self.db_session.execute(
            select(
                exists().where(
                    ProductoColor.color_id == color_id,
                    ProductoColor.is_deleted.is_(False),
                )
            )
        )
        return bool(result.scalar_one())

    def add(self, color: Color) -> None:
        self.db_session.add(color)
