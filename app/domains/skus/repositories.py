from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.colores.models import Color
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.domains.skus.models import SKU_TALLA_ORDER, Sku
from app.domains.tallas.models import Talla


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

    async def list_active_by_producto_color(
        self,
        producto_color_id: UUID,
        *,
        for_update: bool = False,
    ) -> list[Sku]:
        """
        SKUs activos de un color, ordenados por id: el mismo orden con que las
        ventas bloquean SKUs, para que dos bloqueos no se esperen mutuamente.
        """
        statement = select(Sku).where(
            Sku.producto_color_id == producto_color_id,
            Sku.is_deleted.is_(False),
        )
        if for_update:
            statement = statement.with_for_update()

        result = await self.db_session.execute(statement.order_by(Sku.id))
        return list(result.scalars().all())

    async def soft_delete_by_ids(
        self,
        sku_ids: Sequence[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> int:
        """Elimina lógicamente los SKUs activos indicados. Devuelve cuántos marcó."""
        if not sku_ids:
            return 0
        result = await self.db_session.execute(
            update(Sku)
            .where(Sku.id.in_(sku_ids), Sku.is_deleted.is_(False))
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

    async def find_many(
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

    async def list_inventario(
        self,
        *,
        offset: int,
        limit: int,
        today: date,
        codigo_barras: str | None = None,
        nombre: str | None = None,
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
        talla_id: UUID | None = None,
        is_visible: bool | None = None,
        bajo_minimo: bool | None = None,
        sin_codigo_barras: bool | None = None,
        en_rebaja: bool | None = None,
    ) -> tuple[list[tuple[Sku, UUID, str, UUID, str, str, str]], int]:
        """
        SKUs activos de colores y productos activos, con el producto, el color y
        la talla de cada uno. Ordenados por producto, color y orden de talla.

        codigo_barras busca la coincidencia exacta; nombre, coincidencias
        parciales en el nombre del producto sin distinguir mayúsculas.
        en_rebaja usa today para decidir si la rebaja sigue vigente.
        """
        filters = [
            Sku.is_deleted.is_(False),
            ProductoColor.is_deleted.is_(False),
            Producto.is_deleted.is_(False),
        ]
        if codigo_barras is not None:
            filters.append(Sku.codigo_barras == codigo_barras)
        if nombre:
            filters.append(Producto.nombre.icontains(nombre, autoescape=True))
        if producto_id is not None:
            filters.append(Producto.id == producto_id)
        if color_id is not None:
            filters.append(Color.id == color_id)
        if talla_id is not None:
            filters.append(Sku.talla_id == talla_id)
        if is_visible is not None:
            filters.append(Sku.is_visible.is_(is_visible))
        if bajo_minimo is not None:
            cantidad = Sku.stock["cantidad"].as_integer()
            minimo = Sku.stock["minimo"].as_integer()
            filters.append(cantidad <= minimo if bajo_minimo else cantidad > minimo)
        if sin_codigo_barras is not None:
            filters.append(
                Sku.codigo_barras.is_(None) if sin_codigo_barras else Sku.codigo_barras.is_not(None)
            )
        if en_rebaja is not None:
            # JSONB guarda rebaja_hasta como texto ISO, que se ordena como fecha.
            rebaja_hasta = Sku.precio["rebaja_hasta"].astext
            vigente = and_(
                Sku.precio["rebajado"].astext.is_not(None),
                or_(rebaja_hasta.is_(None), rebaja_hasta >= today.isoformat()),
            )
            filters.append(vigente if en_rebaja else not_(vigente))

        def joined(statement: Select) -> Select:
            return (
                statement.join(ProductoColor, Sku.producto_color_id == ProductoColor.id)
                .join(Producto, ProductoColor.producto_id == Producto.id)
                .join(Color, ProductoColor.color_id == Color.id)
                .join(Talla, Sku.talla_id == Talla.id)
                .where(*filters)
            )

        total_result = await self.db_session.execute(
            joined(select(func.count()).select_from(Sku))
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            joined(
                select(
                    Sku,
                    Producto.id,
                    Producto.nombre,
                    Color.id,
                    Color.nombre,
                    Color.codigo_hex,
                    Talla.etiqueta,
                )
            )
            .order_by(Producto.nombre, Producto.id, Color.nombre, Talla.created_at, Sku.id)
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in result.all()], total

    def add(self, sku: Sku) -> None:
        self.db_session.add(sku)
