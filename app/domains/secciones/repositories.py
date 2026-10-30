from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.categorias.models import Categoria
from app.domains.productos.models import Producto
from app.domains.secciones.models import Seccion


class SeccionRepository:
    """Acceso a datos de secciones. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        seccion_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Seccion | None:
        statement = select(Seccion).where(Seccion.id == seccion_id)
        if not include_deleted:
            statement = statement.where(Seccion.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_by_slug(
        self,
        slug: str,
        *,
        exclude_id: UUID | None = None,
    ) -> Seccion | None:
        statement = select(Seccion).where(
            Seccion.slug == slug,
            Seccion.is_deleted.is_(False),
        )
        if exclude_id is not None:
            statement = statement.where(Seccion.id != exclude_id)

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Seccion]:
        """Todas las secciones no eliminadas, sin paginar, en orden de creación."""
        result = await self.db_session.execute(
            select(Seccion)
            .where(Seccion.is_deleted.is_(False))
            .order_by(Seccion.created_at, Seccion.id)
        )
        return list(result.scalars().all())

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        is_visible: bool | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[Seccion], int]:
        filters = []
        if not include_deleted:
            filters.append(Seccion.is_deleted.is_(False))
        if is_visible is not None:
            filters.append(Seccion.is_visible.is_(is_visible))

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Seccion).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Seccion)
            .where(*filters)
            .order_by(Seccion.created_at, Seccion.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def has_active_dependents(self, seccion_id: UUID) -> bool:
        """True si alguna categoría o producto no eliminado pertenece a la sección."""
        result = await self.db_session.execute(
            select(
                or_(
                    exists().where(
                        Categoria.seccion_id == seccion_id,
                        Categoria.is_deleted.is_(False),
                    ),
                    exists().where(
                        Producto.seccion_id == seccion_id,
                        Producto.is_deleted.is_(False),
                    ),
                )
            )
        )
        return bool(result.scalar_one())

    def add(self, seccion: Seccion) -> None:
        self.db_session.add(seccion)
