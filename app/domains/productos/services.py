from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.categoria_productos.services import CategoriaProductoService
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.services import ProductoColorService
from app.domains.productos.models import Producto
from app.domains.productos.repositories import ProductoRepository
from app.domains.productos.schemas import (
    ProductoDetail,
    ProductoDetailCreate,
    ProductoListItem,
    ProductoResumen,
    ProductoResumenColor,
    ProductoUpdate,
)
from app.domains.secciones.repositories import SeccionRepository
from app.domains.skus.schemas import SkuPrecio
from app.domains.skus.services import SkuService
from app.integrations.cloudinary import CloudinaryService
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)


class _ConResumen:
    """
    Presenta un Producto con su resumen calculado, para construir el ListItem y
    el Detail desde atributos sin añadir campos al model.
    """

    def __init__(self, producto: Producto, resumen: ProductoResumen) -> None:
        self._producto = producto
        self.resumen = resumen

    def __getattr__(self, name: str) -> object:
        return getattr(self._producto, name)


class ProductoService:
    """Reglas de negocio del dominio de productos."""

    @staticmethod
    def _conflict() -> AppException:
        return AppException(
            "Los datos del producto entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        producto: Producto | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._conflict() from error
        except Exception:
            await db_session.rollback()
            raise
        if producto is not None:
            await db_session.refresh(producto)

    @staticmethod
    async def _validate_seccion(db_session: AsyncSession, seccion_id: UUID) -> None:
        if await SeccionRepository(db_session).get_by_id(seccion_id) is None:
            raise AppException(
                "La sección no existe.",
                422,
                ErrorCode.VALIDATION_ERROR,
                {"seccion_id": "La sección no existe."},
            )

    @staticmethod
    async def get(
        db_session: AsyncSession,
        producto_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> Producto:
        producto = await ProductoRepository(db_session).get_by_id(
            producto_id,
            include_deleted=include_deleted,
            for_update=for_update,
            load_detail=load_detail,
        )
        if producto is None:
            raise AppException(
                "Producto no encontrado.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return producto

    @staticmethod
    async def _resumenes(
        db_session: AsyncSession,
        producto_ids: list[UUID],
        settings: Settings,
    ) -> dict[UUID, ProductoResumen]:
        """Resumen de cada producto, con los precios vigentes hoy en la tienda."""
        if not producto_ids:
            return {}
        colores, skus, portadas = await ProductoRepository(db_session).list_resumen_rows(
            producto_ids
        )
        today = SkuService.local_today(settings)

        colores_por_producto: dict[UUID, list[ProductoResumenColor]] = defaultdict(list)
        for producto_id, nombre, codigo_hex in colores:
            colores_por_producto[producto_id].append(
                ProductoResumenColor(nombre=nombre, codigo_hex=codigo_hex)
            )
        precios: dict[UUID, list[Decimal]] = defaultdict(list)
        stock_total: dict[UUID, int] = defaultdict(int)
        for producto_id, precio, stock in skus:
            precios[producto_id].append(
                SkuService.precio_vigente(SkuPrecio.model_validate(precio), today)
            )
            stock_total[producto_id] += int(stock.get("cantidad", 0))
        portada_por_producto = dict(portadas)

        return {
            producto_id: ProductoResumen(
                portada_url=portada_por_producto.get(producto_id),
                precio_desde=min(precios[producto_id], default=None),
                precio_hasta=max(precios[producto_id], default=None),
                stock_total=stock_total[producto_id],
                colores=colores_por_producto[producto_id],
            )
            for producto_id in producto_ids
        }

    @classmethod
    async def get_detail(
        cls,
        db_session: AsyncSession,
        producto_id: UUID,
        settings: Settings,
    ) -> ProductoDetail:
        """Ficha completa del producto, con su resumen."""
        producto = await cls.get(db_session, producto_id, load_detail=True)
        resumenes = await cls._resumenes(db_session, [producto.id], settings)
        return ProductoDetail.model_validate(
            _ConResumen(producto, resumenes[producto.id]),
            context=SkuService.detail_context(settings),
        )

    @classmethod
    async def list(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        *,
        page: int = 1,
        per_page: int = 20,
        seccion_id: UUID | None = None,
        categoria_id: UUID | None = None,
        is_visible: bool | None = None,
        nombre: str | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[ProductoListItem]:
        if page < 1:
            raise AppException(
                "La página debe ser mayor o igual a 1.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )
        if per_page < 1 or per_page > 100:
            raise AppException(
                "La cantidad por página debe estar entre 1 y 100.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )

        productos, total = await ProductoRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            seccion_id=seccion_id,
            categoria_id=categoria_id,
            is_visible=is_visible,
            nombre=nombre.strip() if nombre else None,
            include_deleted=include_deleted,
        )
        resumenes = await cls._resumenes(
            db_session, [producto.id for producto in productos], settings
        )
        return PaginatedResponse[ProductoListItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=[
                ProductoListItem.model_validate(_ConResumen(producto, resumenes[producto.id]))
                for producto in productos
            ],
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: ProductoDetailCreate,
        actor_id: UUID,
        settings: Settings,
    ) -> ProductoDetail:
        """
        Crea el producto y, en la misma transacción, sus categorías y sus
        colores con sus imágenes y SKUs (create en un solo paso). Todo se valida
        antes de insertar nada; sin colecciones equivale al create simple.

        Devuelve la ficha completa, igual que GET /productos/{id}.
        """
        await cls._validate_seccion(db_session, data.seccion_id)
        await CategoriaProductoService.validate_categorias(
            db_session, data.categoria_ids, data.seccion_id
        )
        valid_talla_ids: set[UUID] = set()
        for color_index, color in enumerate(data.colores):
            await ProductoColorService.validate_detail_create(
                db_session,
                color,
                settings,
                path=f"colores -> {color_index}",
                valid_talla_ids=valid_talla_ids,
            )

        audit = {"created_by": actor_id, "updated_by": actor_id}
        producto = Producto(**data.model_dump(exclude={"categoria_ids", "colores"}), **audit)
        producto_repository = ProductoRepository(db_session)
        producto_repository.add(producto)
        try:
            await producto_repository.flush()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._conflict() from error
        except Exception:
            await db_session.rollback()
            raise

        categoria_producto_repository = CategoriaProductoRepository(db_session)
        for categoria_id in data.categoria_ids:
            categoria_producto_repository.add(
                CategoriaProducto(categoria_id=categoria_id, producto_id=producto.id, **audit)
            )

        upload_destinations: dict[str, str] = {}
        for color in data.colores:
            producto_color = ProductoColorService.add_detail_create(
                db_session, producto.id, color, actor_id
            )
            upload_destinations |= ProductoColorService.upload_destinations(producto_color, color)

        await cls._commit(db_session)
        await CloudinaryService.confirm_pending_uploads(upload_destinations, settings)

        logger.info(
            "Producto creado: producto_id=%s colores=%s actor_id=%s",
            producto.id,
            len(data.colores),
            actor_id,
        )
        # Los objetos recién creados no tienen sus relaciones cargadas; se
        # expiran para que la consulta del Detail los cargue completos. El id se
        # toma antes: leer un atributo expirado dispararía una carga implícita.
        producto_id = producto.id
        db_session.expire_all()
        return await cls.get_detail(db_session, producto_id, settings)

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        producto_id: UUID,
        data: ProductoUpdate,
        actor_id: UUID,
        settings: Settings,
    ) -> ProductoDetail:
        """
        Actualiza un producto y, si llega categoria_ids, reemplaza sus
        categorías en la misma transacción, validadas contra la sección
        resultante. Al cambiar de sección sin enviar categoria_ids se quitan
        todas, porque pertenecen a la sección anterior.

        Cambiar solo las categorías modifica los enlaces, no el producto; si son
        las mismas, no hay commit.
        """
        changes = data.model_dump(exclude_unset=True)
        categoria_ids: list[UUID] | None = changes.pop("categoria_ids", None)
        producto = await cls.get(
            db_session,
            producto_id,
            for_update=bool(changes) or categoria_ids is not None,
        )
        if not changes and categoria_ids is None:
            return await cls.get_detail(db_session, producto_id, settings)

        now = utc_now()
        seccion_id = changes.get("seccion_id", producto.seccion_id)
        if seccion_id != producto.seccion_id:
            await cls._validate_seccion(db_session, seccion_id)

        categorias_anadidas = categorias_quitadas = 0
        if categoria_ids is not None:
            categorias_anadidas, categorias_quitadas = await CategoriaProductoService.apply_categorias(
                db_session, producto.id, seccion_id, categoria_ids, actor_id, now
            )
        elif seccion_id != producto.seccion_id:
            categorias_quitadas = await CategoriaProductoRepository(
                db_session
            ).soft_delete_by_producto(producto.id, actor_id, now)

        if not changes and not (categorias_anadidas or categorias_quitadas):
            return await cls.get_detail(db_session, producto_id, settings)

        if changes:
            for field_name, value in changes.items():
                setattr(producto, field_name, value)
            producto.updated_at = now
            producto.updated_by = actor_id
        try:
            await cls._commit(db_session, producto)
        except AppException as error:
            # Con categorías, el único conflicto posible es otro cambio simultáneo de ellas.
            if categoria_ids is not None:
                raise CategoriaProductoService.concurrent_change() from error
            raise

        logger.info(
            "Producto actualizado: producto_id=%s categorias_anadidas=%s categorias_quitadas=%s actor_id=%s",
            producto.id,
            categorias_anadidas,
            categorias_quitadas,
            actor_id,
        )
        # Responde lo mismo que GET /{id}: se recarga con su Detail.
        db_session.expire_all()
        return await cls.get_detail(db_session, producto_id, settings)


    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        producto_id: UUID,
        actor_id: UUID,
    ) -> Producto:
        """
        Eliminación lógica en cascada (AGENTS.md §5): elimina sus colores con sus
        imágenes y SKUs, y lo quita de sus categorías.
        """
        producto = await cls.get(db_session, producto_id, for_update=True)

        now = utc_now()
        producto_color_repository = ProductoColorRepository(db_session)
        producto_color_ids = await producto_color_repository.list_active_ids_by_producto(
            producto.id
        )
        await ProductoColorService.delete_children(db_session, producto_color_ids, actor_id, now)
        await producto_color_repository.soft_delete_by_ids(producto_color_ids, actor_id, now)
        enlaces = await CategoriaProductoRepository(db_session).soft_delete_by_producto(
            producto.id,
            actor_id,
            now,
        )

        producto.is_deleted = True
        producto.deleted_at = now
        producto.deleted_by = actor_id
        producto.updated_at = now
        producto.updated_by = actor_id
        await cls._commit(db_session, producto)

        logger.info(
            "Producto eliminado: producto_id=%s colores=%s enlaces=%s actor_id=%s",
            producto.id,
            len(producto_color_ids),
            enlaces,
            actor_id,
        )
        return producto
