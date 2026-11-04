from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categorias.models import Categoria
from app.domains.colores.models import Color
from app.domains.imagenes.models import GALERIA_ORDER, Imagen
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.domains.skus.models import Sku


class ProductoRepository:
    """Acceso a datos de productos. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        producto_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> Producto | None:
        """
        Con load_detail carga lo que embebe el Detail: la sección, las categorías
        activas y los colores activos, cada uno con su color, sus imágenes y sus
        SKUs activos, y cada SKU con su talla.
        """
        statement = select(Producto).where(Producto.id == producto_id)
        if not include_deleted:
            statement = statement.where(Producto.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()
        if load_detail:
            statement = statement.options(
                selectinload(Producto.seccion),
                selectinload(Producto.categorias.and_(Categoria.is_deleted.is_(False))),
                selectinload(
                    Producto.colores.and_(ProductoColor.is_deleted.is_(False))
                ).options(
                    selectinload(ProductoColor.color),
                    selectinload(ProductoColor.imagenes.and_(Imagen.is_deleted.is_(False))),
                    selectinload(ProductoColor.skus.and_(Sku.is_deleted.is_(False))).selectinload(
                        Sku.talla
                    ),
                ),
            )

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        seccion_id: UUID | None = None,
        categoria_id: UUID | None = None,
        is_visible: bool | None = None,
        nombre: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[Producto], int]:
        """
        Listado paginado con la sección cargada para el ListItem. categoria_id
        filtra por enlace activo con esa categoría;
        nombre busca coincidencias parciales sin distinguir mayúsculas.
        """
        filters = []
        if not include_deleted:
            filters.append(Producto.is_deleted.is_(False))
        if seccion_id is not None:
            filters.append(Producto.seccion_id == seccion_id)
        if categoria_id is not None:
            filters.append(
                exists().where(
                    CategoriaProducto.producto_id == Producto.id,
                    CategoriaProducto.categoria_id == categoria_id,
                    CategoriaProducto.is_deleted.is_(False),
                )
            )
        if is_visible is not None:
            filters.append(Producto.is_visible.is_(is_visible))
        if nombre:
            filters.append(Producto.nombre.icontains(nombre, autoescape=True))

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Producto).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Producto)
            .where(*filters)
            .options(selectinload(Producto.seccion))
            .order_by(Producto.created_at.desc(), Producto.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def list_resumen_rows(
        self,
        producto_ids: list[UUID],
    ) -> tuple[
        list[tuple[UUID, str, str]],
        list[tuple[UUID, dict[str, Any], dict[str, Any]]],
        list[tuple[UUID, str]],
    ]:
        """
        Datos para el resumen de esos productos, en tres consultas, sin importar
        cuántos sean. Solo cuenta hijos activos de colores activos.

        Devuelve:
        - colores (producto_id, nombre, codigo_hex), en el orden del Detail;
        - SKUs (producto_id, precio, stock);
        - portadas (producto_id, url): la primera imagen, en orden de galería,
          del primer color que tenga imágenes.
        """
        if not producto_ids:
            return [], [], []

        color_activo = (
            ProductoColor.producto_id.in_(producto_ids),
            ProductoColor.is_deleted.is_(False),
        )

        colores = await self.db_session.execute(
            select(ProductoColor.producto_id, Color.nombre, Color.codigo_hex)
            .join(Color, ProductoColor.color_id == Color.id)
            .where(*color_activo)
            .order_by(ProductoColor.producto_id, ProductoColor.created_at, ProductoColor.id)
        )
        skus = await self.db_session.execute(
            select(ProductoColor.producto_id, Sku.precio, Sku.stock)
            .join(ProductoColor, Sku.producto_color_id == ProductoColor.id)
            .where(*color_activo, Sku.is_deleted.is_(False))
        )
        portadas = await self.db_session.execute(
            select(ProductoColor.producto_id, Imagen.url)
            .join(ProductoColor, Imagen.producto_color_id == ProductoColor.id)
            .where(*color_activo, Imagen.is_deleted.is_(False))
            .distinct(ProductoColor.producto_id)
            .order_by(
                ProductoColor.producto_id,
                ProductoColor.created_at,
                ProductoColor.id,
                *GALERIA_ORDER,
            )
        )
        return (
            [tuple(row) for row in colores.all()],
            [tuple(row) for row in skus.all()],
            [tuple(row) for row in portadas.all()],
        )

    def add(self, producto: Producto) -> None:
        self.db_session.add(producto)

    async def flush(self) -> None:
        """
        Envía a la base los inserts pendientes sin confirmar la transacción.

        Necesario antes de crear los enlaces de categoria_productos: no tienen
        una relación declarada hacia Producto, así que la unidad de trabajo no
        garantiza insertar el producto antes que ellos.
        """
        await self.db_session.flush()
