from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.imagenes.models import Imagen
from app.domains.producto_colores.models import ProductoColor
from app.domains.skus.models import Sku


class ProductoColorRepository:
    """Acceso a datos de los colores de cada producto. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        producto_color_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> ProductoColor | None:
        """
        Con load_detail carga lo que embebe el Detail: el color y sus imágenes y
        SKUs activos, cada SKU con su talla.
        """
        statement = select(ProductoColor).where(ProductoColor.id == producto_color_id)
        if not include_deleted:
            statement = statement.where(ProductoColor.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()
        if load_detail:
            statement = statement.options(
                selectinload(ProductoColor.color),
                selectinload(ProductoColor.imagenes.and_(Imagen.is_deleted.is_(False))),
                selectinload(ProductoColor.skus.and_(Sku.is_deleted.is_(False))).selectinload(
                    Sku.talla
                ),
            )

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_by_producto_and_color(
        self,
        producto_id: UUID,
        color_id: UUID,
        *,
        exclude_id: UUID | None = None,
    ) -> ProductoColor | None:
        statement = select(ProductoColor).where(
            ProductoColor.producto_id == producto_id,
            ProductoColor.color_id == color_id,
            ProductoColor.is_deleted.is_(False),
        )
        if exclude_id is not None:
            statement = statement.where(ProductoColor.id != exclude_id)

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def list_active_ids_by_producto(self, producto_id: UUID) -> list[UUID]:
        result = await self.db_session.execute(
            select(ProductoColor.id).where(
                ProductoColor.producto_id == producto_id,
                ProductoColor.is_deleted.is_(False),
            )
        )
        return list(result.scalars().all())

    async def soft_delete_by_ids(
        self,
        producto_color_ids: Sequence[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> int:
        """Elimina lógicamente los colores de producto activos indicados. Devuelve cuántos marcó."""
        if not producto_color_ids:
            return 0
        result = await self.db_session.execute(
            update(ProductoColor)
            .where(
                ProductoColor.id.in_(producto_color_ids),
                ProductoColor.is_deleted.is_(False),
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
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
        is_visible: bool | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[ProductoColor], int]:
        """Listado paginado con el color cargado para el ListItem."""
        filters = []
        if not include_deleted:
            filters.append(ProductoColor.is_deleted.is_(False))
        if producto_id is not None:
            filters.append(ProductoColor.producto_id == producto_id)
        if color_id is not None:
            filters.append(ProductoColor.color_id == color_id)
        if is_visible is not None:
            filters.append(ProductoColor.is_visible.is_(is_visible))

        total_result = await self.db_session.execute(
            select(func.count()).select_from(ProductoColor).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(ProductoColor)
            .where(*filters)
            .options(selectinload(ProductoColor.color))
            .order_by(ProductoColor.created_at, ProductoColor.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    def add(self, producto_color: ProductoColor) -> None:
        self.db_session.add(producto_color)
