from collections import defaultdict
from collections.abc import Awaitable
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
from app.domains.imagenes.models import Imagen
from app.domains.imagenes.repositories import ImagenRepository
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.schemas import ProductoColorDetailCreate
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
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
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
        return ProductoDetail.model_validate(_ConResumen(producto, resumenes[producto.id]))

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

        productos, total = await ProductoRepository(db_session).list(
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

    @staticmethod
    async def _at(path: str, check: Awaitable[None]) -> None:
        """Ejecuta una validación e indica en sus detalles la ruta dentro del árbol."""
        try:
            await check
        except AppException as error:
            error.details = {f"{path} -> {key}": message for key, message in error.details.items()}
            raise

    @classmethod
    async def _validate_colores(
        cls,
        db_session: AsyncSession,
        colores: list[ProductoColorDetailCreate],
        settings: Settings,
    ) -> None:
        """
        Aplica a cada color, imagen y SKU las mismas reglas que su create
        individual. La unicidad dentro del árbol ya la garantiza el schema.
        """
        sku_repository = SkuRepository(db_session)
        valid_talla_ids: set[UUID] = set()
        for color_index, color in enumerate(colores):
            color_path = f"colores -> {color_index}"
            await cls._at(color_path, ProductoColorService.validate_color(db_session, color.color_id))

            for imagen_index, imagen in enumerate(color.imagenes):
                if not CloudinaryService.is_pending_upload_url(imagen.url, settings):
                    message = "La imagen debe subirse antes con POST /imagenes/uploads."
                    raise AppException(
                        message,
                        422,
                        ErrorCode.VALIDATION_ERROR,
                        {f"{color_path} -> imagenes -> {imagen_index} -> url": message},
                    )

            for sku_index, sku in enumerate(color.skus):
                sku_path = f"{color_path} -> skus -> {sku_index}"
                if sku.talla_id not in valid_talla_ids:
                    await cls._at(sku_path, SkuService.validate_talla(db_session, sku.talla_id))
                    valid_talla_ids.add(sku.talla_id)
                if sku.codigo_barras is not None:
                    await cls._at(
                        sku_path,
                        SkuService.validate_unique_codigo_barras(sku_repository, sku.codigo_barras),
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
        await cls._validate_colores(db_session, data.colores, settings)

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

        producto_color_repository = ProductoColorRepository(db_session)
        imagen_repository = ImagenRepository(db_session)
        sku_repository = SkuRepository(db_session)
        for color in data.colores:
            producto_color = ProductoColor(
                producto_id=producto.id,
                color_id=color.color_id,
                is_visible=color.is_visible,
                **audit,
            )
            producto_color_repository.add(producto_color)
            for imagen in color.imagenes:
                imagen_repository.add(
                    Imagen(producto_color_id=producto_color.id, **imagen.model_dump(), **audit)
                )
            for sku in color.skus:
                sku_repository.add(
                    Sku(
                        producto_color_id=producto_color.id,
                        **sku.model_dump(exclude={"precio", "stock"}),
                        precio=SkuService.precio_json(sku.precio),
                        stock=SkuService.stock_json(sku.stock),
                        **audit,
                    )
                )

        await cls._commit(db_session)
        await CloudinaryService.confirm_pending_uploads(
            [imagen.url for color in data.colores for imagen in color.imagenes]
        )

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
    ) -> Producto:
        """
        Actualiza un producto. Al cambiar de sección se quitan todas sus
        categorías, en la misma transacción, porque pertenecen a la sección
        anterior.
        """
        changes = data.model_dump(exclude_unset=True)
        producto = await cls.get(db_session, producto_id, for_update=bool(changes))
        if not changes:
            return producto

        now = utc_now()
        categorias_quitadas = 0
        if changes.get("seccion_id", producto.seccion_id) != producto.seccion_id:
            await cls._validate_seccion(db_session, changes["seccion_id"])
            categorias_quitadas = await CategoriaProductoRepository(
                db_session
            ).soft_delete_by_producto(producto.id, actor_id, now)

        for field_name, value in changes.items():
            setattr(producto, field_name, value)
        producto.updated_at = now
        producto.updated_by = actor_id
        await cls._commit(db_session, producto)

        logger.info(
            "Producto actualizado: producto_id=%s categorias_quitadas=%s actor_id=%s",
            producto.id,
            categorias_quitadas,
            actor_id,
        )
        return producto

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
