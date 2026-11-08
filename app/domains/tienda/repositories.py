from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Numeric, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categorias.models import Categoria
from app.domains.colores.models import Color
from app.domains.imagenes.models import GALERIA_ORDER, Imagen
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.domains.secciones.models import Seccion
from app.domains.skus.models import Sku
from app.domains.tallas.models import Talla
from app.shared.enums import OrdenTienda


# Visibilidad pública en cascada:
# - un SKU es público si está activo y visible, y su color también;
# - un color es público si está activo, visible y tiene algún SKU público;
# - un producto es público si está activo y visible, su sección también, y
#   tiene algún SKU público (así nunca aparece una tarjeta sin tallas).
SKU_PUBLICO = (
    Sku.is_deleted.is_(False),
    Sku.is_visible.is_(True),
    ProductoColor.is_deleted.is_(False),
    ProductoColor.is_visible.is_(True),
)

PRODUCTO_PUBLICO = (
    Producto.is_deleted.is_(False),
    Producto.is_visible.is_(True),
    select(Seccion.id)
    .where(
        Seccion.id == Producto.seccion_id,
        Seccion.is_deleted.is_(False),
        Seccion.is_visible.is_(True),
    )
    .exists(),
)


def rebaja_vigente(today: date) -> ColumnElement[bool]:
    """True si el SKU tiene rebaja vigente en today (rebaja_hasta incluido o sin fecha)."""
    # JSONB guarda rebaja_hasta como texto ISO, que se ordena como fecha.
    rebaja_hasta = Sku.precio["rebaja_hasta"].astext
    return and_(
        Sku.precio["rebajado"].astext.is_not(None),
        or_(rebaja_hasta.is_(None), rebaja_hasta >= today.isoformat()),
    )


def precio_vigente(today: date) -> ColumnElement[Decimal]:
    """Precio que se cobra en today: el rebajado con rebaja vigente y, si no, el normal."""
    return case(
        (rebaja_vigente(today), Sku.precio["rebajado"].astext.cast(Numeric)),
        else_=Sku.precio["normal"].astext.cast(Numeric),
    )


def _sku_publico_de_color() -> ColumnElement[bool]:
    """EXISTS de un SKU público del ProductoColor de la consulta exterior."""
    return (
        select(Sku.id)
        .where(
            Sku.producto_color_id == ProductoColor.id,
            Sku.is_deleted.is_(False),
            Sku.is_visible.is_(True),
        )
        .exists()
    )


class TiendaRepository:
    """
    Lecturas de la tienda pública. Aplica siempre la visibilidad en cascada y
    nunca devuelve registros eliminados. No hace commit: solo lee.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    @staticmethod
    def _producto_filters(
        *,
        seccion_id: UUID | None,
        categoria_ids: list[UUID] | None,
        q: str | None,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = [*PRODUCTO_PUBLICO]
        if seccion_id is not None:
            filters.append(Producto.seccion_id == seccion_id)
        if categoria_ids is not None:
            filters.append(
                select(CategoriaProducto.id)
                .where(
                    CategoriaProducto.producto_id == Producto.id,
                    CategoriaProducto.categoria_id.in_(categoria_ids),
                    CategoriaProducto.is_deleted.is_(False),
                )
                .exists()
            )
        if q:
            filters.append(Producto.nombre.icontains(q, autoescape=True))
        return filters

    async def find_productos(
        self,
        *,
        offset: int,
        limit: int,
        today: date,
        orden: OrdenTienda,
        seccion_id: UUID | None = None,
        categoria_ids: list[UUID] | None = None,
        q: str | None = None,
        color_ids: list[UUID] | None = None,
        talla_ids: list[UUID] | None = None,
        disponible: bool | None = None,
        en_rebaja: bool | None = None,
        precio_min: Decimal | None = None,
        precio_max: Decimal | None = None,
    ) -> tuple[list[Producto], int]:
        """
        Productos públicos paginados.

        categoria_ids: el producto debe estar asignado a alguna de ellas.
        Los filtros de SKU (color, talla, disponibilidad, rebaja y precio) se
        cumplen en un mismo SKU público: "negro en talla M con stock" exige que
        exista ese SKU, no un negro y una M por separado.
        """
        filters = self._producto_filters(seccion_id=seccion_id, categoria_ids=categoria_ids, q=q)

        sku_filters: list[ColumnElement[bool]] = [
            *SKU_PUBLICO,
            ProductoColor.producto_id == Producto.id,
        ]
        if color_ids:
            sku_filters.append(ProductoColor.color_id.in_(color_ids))
        if talla_ids:
            sku_filters.append(Sku.talla_id.in_(talla_ids))
        if disponible is not None:
            cantidad = Sku.stock["cantidad"].as_integer()
            sku_filters.append(cantidad > 0 if disponible else cantidad <= 0)
        if en_rebaja is not None:
            vigente = rebaja_vigente(today)
            sku_filters.append(vigente if en_rebaja else ~vigente)
        if precio_min is not None:
            sku_filters.append(precio_vigente(today) >= precio_min)
        if precio_max is not None:
            sku_filters.append(precio_vigente(today) <= precio_max)
        filters.append(
            select(Sku.id)
            .join(ProductoColor, Sku.producto_color_id == ProductoColor.id)
            .where(*sku_filters)
            .exists()
        )

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Producto).where(*filters)
        )
        total = int(total_result.scalar_one())

        if orden == OrdenTienda.NOVEDADES:
            order_by: list[Any] = [Producto.created_at.desc(), Producto.id]
        else:
            # El precio desde del producto, el mismo que muestra su tarjeta.
            precio_desde = (
                select(func.min(precio_vigente(today)))
                .select_from(Sku)
                .join(ProductoColor, Sku.producto_color_id == ProductoColor.id)
                .where(*SKU_PUBLICO, ProductoColor.producto_id == Producto.id)
                .scalar_subquery()
            )
            direction = precio_desde.asc() if orden == OrdenTienda.PRECIO_ASC else precio_desde.desc()
            order_by = [direction, Producto.created_at.desc(), Producto.id]

        result = await self.db_session.execute(
            select(Producto).where(*filters).order_by(*order_by).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def list_resumen_rows(
        self,
        producto_ids: list[UUID],
    ) -> tuple[
        list[tuple[UUID, UUID, str, str]],
        list[tuple[UUID, dict[str, Any], dict[str, Any]]],
        list[tuple[UUID, str]],
    ]:
        """
        Datos públicos para las tarjetas de esos productos, en tres consultas.

        Devuelve:
        - colores públicos (producto_id, color_id, nombre, codigo_hex), en el
          orden de la ficha;
        - SKUs públicos (producto_id, precio, stock);
        - portadas (producto_id, url): la primera imagen, en orden de galería,
          del primer color público que tenga imágenes.
        """
        if not producto_ids:
            return [], [], []

        color_publico = (
            ProductoColor.producto_id.in_(producto_ids),
            ProductoColor.is_deleted.is_(False),
            ProductoColor.is_visible.is_(True),
            _sku_publico_de_color(),
        )

        colores = await self.db_session.execute(
            select(ProductoColor.producto_id, Color.id, Color.nombre, Color.codigo_hex)
            .join(Color, ProductoColor.color_id == Color.id)
            .where(*color_publico)
            .order_by(ProductoColor.producto_id, ProductoColor.created_at, ProductoColor.id)
        )
        skus = await self.db_session.execute(
            select(ProductoColor.producto_id, Sku.precio, Sku.stock)
            .join(ProductoColor, Sku.producto_color_id == ProductoColor.id)
            .where(ProductoColor.producto_id.in_(producto_ids), *SKU_PUBLICO)
        )
        portadas = await self.db_session.execute(
            select(ProductoColor.producto_id, Imagen.url)
            .join(ProductoColor, Imagen.producto_color_id == ProductoColor.id)
            .where(*color_publico, Imagen.is_deleted.is_(False))
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

    async def get_producto(self, producto_id: UUID) -> Producto | None:
        """
        Producto público con lo que embebe su ficha: la sección, las categorías
        activas y los colores activos y visibles, cada uno con su color, sus
        imágenes activas y sus SKUs activos y visibles con su talla.

        No descarta los colores sin SKUs públicos ni comprueba que el producto
        tenga alguno: lo decide el service con lo cargado.
        """
        result = await self.db_session.execute(
            select(Producto)
            .where(Producto.id == producto_id, *PRODUCTO_PUBLICO)
            .options(
                selectinload(Producto.seccion),
                selectinload(Producto.categorias.and_(Categoria.is_deleted.is_(False))),
                selectinload(
                    Producto.colores.and_(
                        ProductoColor.is_deleted.is_(False),
                        ProductoColor.is_visible.is_(True),
                    )
                ).options(
                    selectinload(ProductoColor.color),
                    selectinload(ProductoColor.imagenes.and_(Imagen.is_deleted.is_(False))),
                    selectinload(
                        ProductoColor.skus.and_(
                            Sku.is_deleted.is_(False),
                            Sku.is_visible.is_(True),
                        )
                    ).selectinload(Sku.talla),
                ),
            )
        )
        return result.scalar_one_or_none()

    async def get_filtros(
        self,
        *,
        today: date,
        seccion_id: UUID | None = None,
        categoria_ids: list[UUID] | None = None,
        q: str | None = None,
    ) -> tuple[
        list[tuple[UUID, str, str]],
        list[tuple[UUID, str]],
        tuple[Decimal | None, Decimal | None, bool],
    ]:
        """
        Colores, tallas, rango de precios vigentes y si hay rebajas entre los
        SKUs públicos de los productos públicos del alcance pedido.
        """
        filters = [
            *SKU_PUBLICO,
            *self._producto_filters(seccion_id=seccion_id, categoria_ids=categoria_ids, q=q),
        ]

        def joined(*columns: Any) -> Any:
            return (
                select(*columns)
                .select_from(Sku)
                .join(ProductoColor, Sku.producto_color_id == ProductoColor.id)
                .join(Producto, ProductoColor.producto_id == Producto.id)
                .where(*filters)
            )

        colores = await self.db_session.execute(
            joined(Color.id, Color.nombre, Color.codigo_hex)
            .join(Color, ProductoColor.color_id == Color.id)
            .distinct()
            .order_by(Color.nombre, Color.id)
        )
        tallas = await self.db_session.execute(
            joined(Talla.id, Talla.etiqueta, Talla.created_at)
            .join(Talla, Sku.talla_id == Talla.id)
            .distinct()
            .order_by(Talla.created_at, Talla.id)
        )
        precios = await self.db_session.execute(
            joined(
                func.min(precio_vigente(today)),
                func.max(precio_vigente(today)),
                func.coalesce(func.bool_or(rebaja_vigente(today)), False),
            )
        )
        precio_min, precio_max, hay_rebajas = precios.one()
        return (
            [tuple(row) for row in colores.all()],
            [(talla_id, etiqueta) for talla_id, etiqueta, _ in tallas.all()],
            (precio_min, precio_max, bool(hay_rebajas)),
        )
