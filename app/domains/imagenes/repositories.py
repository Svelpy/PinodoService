from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.colores.models import Color
from app.domains.imagenes.models import GALERIA_ORDER, Imagen
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.shared.enums import TipoImagen


class ImagenRepository:
    """Acceso a datos de imágenes. No hace commit ni llama a Cloudinary."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        imagen_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Imagen | None:
        statement = select(Imagen).where(Imagen.id == imagen_id)
        if not include_deleted:
            statement = statement.where(Imagen.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def soft_delete_by_producto_color_ids(
        self,
        producto_color_ids: Sequence[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> int:
        """Elimina lógicamente las imágenes activas de esos colores. Devuelve cuántas marcó."""
        if not producto_color_ids:
            return 0
        result = await self.db_session.execute(
            update(Imagen)
            .where(
                Imagen.producto_color_id.in_(producto_color_ids),
                Imagen.is_deleted.is_(False),
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
        tipo: TipoImagen | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[Imagen], int]:
        filters = []
        if not include_deleted:
            filters.append(Imagen.is_deleted.is_(False))
        if producto_color_id is not None:
            filters.append(Imagen.producto_color_id == producto_color_id)
        if tipo is not None:
            filters.append(Imagen.tipo == tipo)

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Imagen).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Imagen)
            .where(*filters)
            .order_by(*GALERIA_ORDER)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def list_biblioteca(
        self,
        *,
        offset: int,
        limit: int,
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
        tipo: TipoImagen | None = None,
        nombre: str | None = None,
    ) -> tuple[list[tuple[Imagen, UUID, str, UUID, str, str]], int]:
        """
        Imágenes activas de colores y productos activos, con el producto y el
        color de cada una, de la más reciente a la más antigua.

        nombre busca coincidencias parciales en el nombre del producto, sin
        distinguir mayúsculas.
        """
        filters = [
            Imagen.is_deleted.is_(False),
            ProductoColor.is_deleted.is_(False),
            Producto.is_deleted.is_(False),
        ]
        if producto_id is not None:
            filters.append(Producto.id == producto_id)
        if color_id is not None:
            filters.append(Color.id == color_id)
        if tipo is not None:
            filters.append(Imagen.tipo == tipo)
        if nombre:
            filters.append(Producto.nombre.icontains(nombre, autoescape=True))

        def joined(statement: Select) -> Select:
            return (
                statement.join(ProductoColor, Imagen.producto_color_id == ProductoColor.id)
                .join(Producto, ProductoColor.producto_id == Producto.id)
                .join(Color, ProductoColor.color_id == Color.id)
                .where(*filters)
            )

        total_result = await self.db_session.execute(
            joined(select(func.count()).select_from(Imagen))
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            joined(
                select(
                    Imagen,
                    Producto.id,
                    Producto.nombre,
                    Color.id,
                    Color.nombre,
                    Color.codigo_hex,
                )
            )
            .order_by(Imagen.created_at.desc(), Imagen.id)
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in result.all()], total

    async def get_active_by_url(self, url: str) -> Imagen | None:
        """Imagen activa que ya usa ese archivo, si existe."""
        result = await self.db_session.execute(
            select(Imagen).where(Imagen.url == url, Imagen.is_deleted.is_(False)).limit(1)
        )
        return result.scalar_one_or_none()

    def add(self, imagen: Imagen) -> None:
        self.db_session.add(imagen)
