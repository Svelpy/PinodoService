from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categorias.models import Categoria


class CategoriaProductoRepository:
    """Acceso a los enlaces categoría-producto. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def list_active_by_producto(
        self,
        producto_id: UUID,
        *,
        for_update: bool = False,
    ) -> list[CategoriaProducto]:
        statement = select(CategoriaProducto).where(
            CategoriaProducto.producto_id == producto_id,
            CategoriaProducto.is_deleted.is_(False),
        )
        if for_update:
            statement = statement.with_for_update()

        result = await self.db_session.execute(
            statement.order_by(CategoriaProducto.created_at, CategoriaProducto.id)
        )
        return list(result.scalars().all())

    async def list_categorias_by_producto(self, producto_id: UUID) -> list[Categoria]:
        """Categorías activas de un producto, en el orden en que se le asignaron."""
        result = await self.db_session.execute(
            select(Categoria)
            .join(CategoriaProducto, CategoriaProducto.categoria_id == Categoria.id)
            .where(
                CategoriaProducto.producto_id == producto_id,
                CategoriaProducto.is_deleted.is_(False),
                Categoria.is_deleted.is_(False),
            )
            .order_by(CategoriaProducto.created_at, CategoriaProducto.id)
        )
        return list(result.scalars().all())

    async def soft_delete_by_producto(
        self,
        producto_id: UUID,
        actor_id: UUID,
        now: datetime,
    ) -> int:
        """Elimina lógicamente los enlaces activos de un producto. Devuelve cuántos marcó."""
        result = await self.db_session.execute(
            update(CategoriaProducto)
            .where(
                CategoriaProducto.producto_id == producto_id,
                CategoriaProducto.is_deleted.is_(False),
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

    async def soft_delete_by_categoria(
        self,
        categoria_id: UUID,
        actor_id: UUID,
        now: datetime,
    ) -> int:
        """Elimina lógicamente los enlaces activos de una categoría. Devuelve cuántos marcó."""
        result = await self.db_session.execute(
            update(CategoriaProducto)
            .where(
                CategoriaProducto.categoria_id == categoria_id,
                CategoriaProducto.is_deleted.is_(False),
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

    def add(self, categoria_producto: CategoriaProducto) -> None:
        self.db_session.add(categoria_producto)
