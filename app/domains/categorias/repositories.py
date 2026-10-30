from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categorias.models import Categoria


class CategoriaRepository:
    """Acceso a datos de categorías. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        categoria_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> Categoria | None:
        """Con load_detail carga la sección y las subcategorías activas que necesita el Detail."""
        statement = select(Categoria).where(Categoria.id == categoria_id)
        if not include_deleted:
            statement = statement.where(Categoria.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()
        if load_detail:
            statement = statement.options(
                selectinload(Categoria.seccion),
                selectinload(
                    Categoria.subcategorias.and_(Categoria.is_deleted.is_(False))
                ).selectinload(Categoria.seccion),
            )

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_by_slug(
        self,
        seccion_id: UUID,
        slug: str,
        *,
        exclude_id: UUID | None = None,
    ) -> Categoria | None:
        statement = select(Categoria).where(
            Categoria.seccion_id == seccion_id,
            Categoria.slug == slug,
            Categoria.is_deleted.is_(False),
        )
        if exclude_id is not None:
            statement = statement.where(Categoria.id != exclude_id)

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_many_by_ids(self, categoria_ids: list[UUID]) -> list[Categoria]:
        """Categorías no eliminadas cuyos ids están en la lista; los ausentes se omiten."""
        if not categoria_ids:
            return []
        result = await self.db_session.execute(
            select(Categoria).where(
                Categoria.id.in_(categoria_ids),
                Categoria.is_deleted.is_(False),
            )
        )
        return list(result.scalars().all())

    async def list_for_tree(self, seccion_id: UUID | None = None) -> list[Categoria]:
        """Categorías activas sin paginar, planas, en orden de creación, para armar el árbol."""
        statement = select(Categoria).where(Categoria.is_deleted.is_(False))
        if seccion_id is not None:
            statement = statement.where(Categoria.seccion_id == seccion_id)

        result = await self.db_session.execute(
            statement.order_by(Categoria.created_at, Categoria.id)
        )
        return list(result.scalars().all())

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        seccion_id: UUID | None = None,
        parent_id: UUID | None = None,
        is_visible: bool | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[Categoria], int]:
        """Listado paginado con la sección cargada para el ListItem."""
        filters = []
        if not include_deleted:
            filters.append(Categoria.is_deleted.is_(False))
        if seccion_id is not None:
            filters.append(Categoria.seccion_id == seccion_id)
        if parent_id is not None:
            filters.append(Categoria.parent_id == parent_id)
        if is_visible is not None:
            filters.append(Categoria.is_visible.is_(is_visible))

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Categoria).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Categoria)
            .where(*filters)
            .options(selectinload(Categoria.seccion))
            .order_by(Categoria.created_at, Categoria.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def has_active_children(self, categoria_id: UUID) -> bool:
        result = await self.db_session.execute(
            select(
                exists().where(
                    Categoria.parent_id == categoria_id,
                    Categoria.is_deleted.is_(False),
                )
            )
        )
        return bool(result.scalar_one())

    async def has_active_products(self, categoria_id: UUID) -> bool:
        result = await self.db_session.execute(
            select(
                exists().where(
                    CategoriaProducto.categoria_id == categoria_id,
                    CategoriaProducto.is_deleted.is_(False),
                )
            )
        )
        return bool(result.scalar_one())

    def add(self, categoria: Categoria) -> None:
        self.db_session.add(categoria)
