from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domains.categorias.schemas import CategoriaResponse
from app.domains.categorias.services import CategoriaService
from app.domains.config.models import Config
from app.domains.config.services import ConfigService
from app.domains.productos.models import Producto
from app.domains.skus.models import Sku
from app.domains.skus.schemas import SkuPrecio
from app.domains.skus.services import SkuService
from app.domains.tienda.repositories import TiendaRepository
from app.domains.tienda.schemas import (
    TiendaCategoria,
    TiendaColor,
    TiendaFiltros,
    TiendaImagen,
    TiendaNavegacionSeccion,
    TiendaProductoCard,
    TiendaProductoColor,
    TiendaProductoDetalle,
    TiendaSeccion,
    TiendaSku,
    TiendaTalla,
)
from app.shared.enums import OrdenTienda
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.schemas.tree import TreeNodeResponse, TreeResponse
from app.shared.services.slug import generate_slug


@dataclass(frozen=True)
class _PrecioSku:
    """Lo que la tienda muestra del precio y el stock de un SKU, calculado para hoy."""

    normal: Decimal
    vigente: Decimal
    rebaja_hasta: date | None
    disponible: bool

    @property
    def en_rebaja(self) -> bool:
        # SkuPrecio garantiza que el rebajado es menor que el normal.
        return self.vigente < self.normal


@dataclass
class _Navegacion:
    """Árbol público y los índices que necesitan los filtros y la ficha."""

    secciones: list[TiendaNavegacionSeccion] = field(default_factory=list)
    seccion_ids: set[UUID] = field(default_factory=set)
    categorias: dict[UUID, TiendaCategoria] = field(default_factory=dict)
    # Cada categoría con ella misma y sus descendientes visibles.
    subarbol: dict[UUID, list[UUID]] = field(default_factory=dict)


def _not_found(message: str) -> AppException:
    return AppException(message, 404, ErrorCode.RESOURCE_NOT_FOUND)


def _slug_producto(nombre: str) -> str:
    return generate_slug(nombre) or "producto"


def _precio_sku(precio: dict[str, Any], stock: dict[str, Any], today: date) -> _PrecioSku:
    sku_precio = SkuPrecio.model_validate(precio)
    vigente = SkuService.precio_vigente(sku_precio, today)
    return _PrecioSku(
        normal=sku_precio.normal,
        vigente=vigente,
        rebaja_hasta=sku_precio.rebaja_hasta if vigente < sku_precio.normal else None,
        disponible=int(stock.get("cantidad", 0)) > 0,
    )


def _campos_comunes(producto: Producto, precios: list[_PrecioSku]) -> dict[str, Any]:
    """Campos de TiendaProductoBase. precios no puede estar vacío."""
    vigentes = [precio.vigente for precio in precios]
    normales = [precio.normal for precio in precios]
    return {
        "id": producto.id,
        "slug": _slug_producto(producto.nombre),
        "nombre": producto.nombre,
        "precio_desde": min(vigentes),
        "precio_hasta": max(vigentes),
        "precio_normal_desde": min(normales),
        "precio_normal_hasta": max(normales),
        "en_rebaja": any(precio.en_rebaja for precio in precios),
        "agotado": not any(precio.disponible for precio in precios),
    }


class TiendaService:
    """Lecturas de la tienda pública: solo lo visible, sin auditoría."""

    @staticmethod
    async def get_config(db_session: AsyncSession) -> Config:
        return await ConfigService.get(db_session)

    @staticmethod
    async def verificar_abierta(db_session: AsyncSession) -> None:
        """503 mientras la tienda esté en mantenimiento."""
        config = await ConfigService.get(db_session)
        if config.en_mantenimiento:
            raise AppException(
                "La tienda está en mantenimiento. Vuelve a intentarlo más tarde.",
                503,
                ErrorCode.MAINTENANCE,
            )

    @staticmethod
    async def _navegacion(
        db_session: AsyncSession,
        seccion_id: UUID | None = None,
    ) -> _Navegacion:
        """
        Árbol visible (por visibilidad efectiva, ver CategoriaService.arbol)
        convertido a los schemas públicos. El slug de cada categoría es el de
        su sección seguido del suyo: los de los ancestros no se añaden porque
        los nombres de las subcategorías suelen repetirlos.
        """
        navegacion = _Navegacion()

        def convertir(
            nodes: list[TreeNodeResponse[CategoriaResponse]],
            seccion_slug: str,
        ) -> tuple[list[TreeNodeResponse[TiendaCategoria]], list[UUID]]:
            convertidos: list[TreeNodeResponse[TiendaCategoria]] = []
            ids: list[UUID] = []
            for node in nodes:
                slug = f"{seccion_slug}-{node.data.slug}"
                children, descendientes = convertir(node.children, seccion_slug)
                categoria = TiendaCategoria(id=node.data.id, nombre=node.data.nombre, slug=slug)
                navegacion.categorias[categoria.id] = categoria
                navegacion.subarbol[categoria.id] = [categoria.id, *descendientes]
                convertidos.append(
                    TreeNodeResponse[TiendaCategoria](data=categoria, children=children)
                )
                ids.extend(navegacion.subarbol[categoria.id])
            return convertidos, ids

        arbol = await CategoriaService.arbol(db_session, seccion_id=seccion_id, is_visible=True)
        for item in arbol:
            nodes, ids = convertir(item.categorias.data, item.seccion.slug)
            navegacion.seccion_ids.add(item.seccion.id)
            navegacion.secciones.append(
                TiendaNavegacionSeccion(
                    id=item.seccion.id,
                    nombre=item.seccion.nombre,
                    slug=item.seccion.slug,
                    categorias=TreeResponse[TiendaCategoria](total=len(ids), data=nodes),
                )
            )
        return navegacion

    @classmethod
    async def navegacion(cls, db_session: AsyncSession) -> list[TiendaNavegacionSeccion]:
        return (await cls._navegacion(db_session)).secciones

    @classmethod
    async def _resolver_alcance(
        cls,
        db_session: AsyncSession,
        seccion_id: UUID | None,
        categoria_id: UUID | None,
    ) -> list[UUID] | None:
        """
        Comprueba que la sección y la categoría pedidas sean visibles (404 si no)
        y devuelve los ids de la categoría y sus subcategorías visibles.
        """
        if seccion_id is None and categoria_id is None:
            return None
        navegacion = await cls._navegacion(db_session)
        if seccion_id is not None and seccion_id not in navegacion.seccion_ids:
            raise _not_found("Sección no encontrada.")
        if categoria_id is None:
            return None
        if categoria_id not in navegacion.subarbol:
            raise _not_found("Categoría no encontrada.")
        return navegacion.subarbol[categoria_id]

    @classmethod
    async def listar_productos(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        *,
        page: int = 1,
        per_page: int = 24,
        orden: OrdenTienda = OrdenTienda.NOVEDADES,
        seccion_id: UUID | None = None,
        categoria_id: UUID | None = None,
        q: str | None = None,
        color_ids: list[UUID] | None = None,
        talla_ids: list[UUID] | None = None,
        disponible: bool | None = None,
        en_rebaja: bool | None = None,
        precio_min: Decimal | None = None,
        precio_max: Decimal | None = None,
    ) -> PaginatedResponse[TiendaProductoCard]:
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise AppException(
                "El precio mínimo no puede ser mayor que el máximo.",
                422,
                ErrorCode.VALIDATION_ERROR,
                {"precio_min": "El precio mínimo no puede ser mayor que el máximo."},
            )
        categoria_ids = await cls._resolver_alcance(db_session, seccion_id, categoria_id)
        today = SkuService.local_today(settings)
        repository = TiendaRepository(db_session)

        productos, total = await repository.find_productos(
            offset=(page - 1) * per_page,
            limit=per_page,
            today=today,
            orden=orden,
            seccion_id=seccion_id,
            categoria_ids=categoria_ids,
            q=q.strip() if q else None,
            color_ids=color_ids,
            talla_ids=talla_ids,
            disponible=disponible,
            en_rebaja=en_rebaja,
            precio_min=precio_min,
            precio_max=precio_max,
        )
        colores, skus, portadas = await repository.list_resumen_rows(
            [producto.id for producto in productos]
        )

        colores_por_producto: dict[UUID, list[TiendaColor]] = defaultdict(list)
        for producto_id, color_id, nombre, codigo_hex in colores:
            colores_por_producto[producto_id].append(
                TiendaColor(id=color_id, nombre=nombre, codigo_hex=codigo_hex)
            )
        precios: dict[UUID, list[_PrecioSku]] = defaultdict(list)
        for producto_id, precio, stock in skus:
            precios[producto_id].append(_precio_sku(precio, stock, today))
        portada_por_producto = dict(portadas)

        return PaginatedResponse[TiendaProductoCard](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=[
                TiendaProductoCard(
                    **_campos_comunes(producto, precios[producto.id]),
                    portada_url=portada_por_producto.get(producto.id),
                    colores=colores_por_producto[producto.id],
                )
                for producto in productos
                # Solo falta si sus SKUs se ocultaron entre las dos consultas.
                if precios[producto.id]
            ],
        )

    @staticmethod
    def _sku(sku: Sku, today: date) -> tuple[TiendaSku, _PrecioSku]:
        precio = _precio_sku(sku.precio, sku.stock, today)
        return (
            TiendaSku(
                id=sku.id,
                talla=TiendaTalla.model_validate(sku.talla),
                precio_normal=precio.normal,
                precio_vigente=precio.vigente,
                en_rebaja=precio.en_rebaja,
                rebaja_hasta=precio.rebaja_hasta,
                disponible=precio.disponible,
            ),
            precio,
        )

    @classmethod
    async def get_producto(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        producto_id: UUID,
    ) -> TiendaProductoDetalle:
        """
        Ficha pública. 404 si el producto, su sección o todos sus colores están
        ocultos, o si no tiene ninguna talla visible.
        """
        producto = await TiendaRepository(db_session).get_producto(producto_id)
        if producto is None:
            raise _not_found("Producto no encontrado.")
        today = SkuService.local_today(settings)

        colores: list[TiendaProductoColor] = []
        precios: list[_PrecioSku] = []
        for producto_color in producto.colores:
            if not producto_color.skus:
                continue
            skus = [cls._sku(sku, today) for sku in producto_color.skus]
            precios.extend(precio for _, precio in skus)
            colores.append(
                TiendaProductoColor(
                    id=producto_color.id,
                    color=TiendaColor.model_validate(producto_color.color),
                    agotado=not any(precio.disponible for _, precio in skus),
                    imagenes=[
                        TiendaImagen.model_validate(imagen) for imagen in producto_color.imagenes
                    ],
                    skus=[tienda_sku for tienda_sku, _ in skus],
                )
            )
        if not colores:
            raise _not_found("Producto no encontrado.")

        navegacion = await cls._navegacion(db_session, producto.seccion_id)
        return TiendaProductoDetalle(
            **_campos_comunes(producto, precios),
            descripcion=producto.descripcion,
            cuidados=producto.cuidados,
            composicion=producto.composicion,
            seccion=TiendaSeccion.model_validate(producto.seccion),
            categorias=[
                navegacion.categorias[categoria.id]
                for categoria in producto.categorias
                if categoria.id in navegacion.categorias
            ],
            colores=colores,
        )

    @classmethod
    async def filtros(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        *,
        seccion_id: UUID | None = None,
        categoria_id: UUID | None = None,
        q: str | None = None,
    ) -> TiendaFiltros:
        categoria_ids = await cls._resolver_alcance(db_session, seccion_id, categoria_id)
        colores, tallas, (precio_min, precio_max, hay_rebajas) = await TiendaRepository(
            db_session
        ).get_filtros(
            today=SkuService.local_today(settings),
            seccion_id=seccion_id,
            categoria_ids=categoria_ids,
            q=q.strip() if q else None,
        )
        return TiendaFiltros(
            colores=[
                TiendaColor(id=color_id, nombre=nombre, codigo_hex=codigo_hex)
                for color_id, nombre, codigo_hex in colores
            ],
            tallas=[TiendaTalla(id=talla_id, etiqueta=etiqueta) for talla_id, etiqueta in tallas],
            precio_min=precio_min,
            precio_max=precio_max,
            hay_rebajas=hay_rebajas,
        )
