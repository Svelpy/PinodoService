from collections.abc import Awaitable, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.colores.repositories import ColorRepository
from app.domains.imagenes.models import Imagen
from app.domains.imagenes.repositories import ImagenRepository
from app.domains.imagenes.services import ImagenService
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.schemas import (
    ProductoColorCreate,
    ProductoColorDetail,
    ProductoColorDetailCreate,
    ProductoColorListItem,
    ProductoColorUpdate,
)
from app.domains.productos.repositories import ProductoRepository
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.domains.skus.services import SkuService
from app.integrations.cloudinary import CloudinaryService
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)


class ProductoColorService:
    """Reglas de negocio de los colores de cada producto."""

    @staticmethod
    def _duplicate_color() -> AppException:
        return AppException(
            "El producto ya tiene ese color.",
            409,
            ErrorCode.CONFLICT,
            {"color_id": "El producto ya tiene ese color."},
        )

    @staticmethod
    def _invalid_reference(field_name: str, message: str) -> AppException:
        return AppException(message, 422, ErrorCode.VALIDATION_ERROR, {field_name: message})

    @classmethod
    def _integrity_exception(cls, error: IntegrityError) -> AppException:
        original_error = error.orig
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "__cause__", None),
                "constraint_name",
                None,
            )

        if constraint_name == "uq_producto_colores_producto_color":
            return cls._duplicate_color()

        return AppException(
            "Los datos del color del producto entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        producto_color: ProductoColor | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        if producto_color is not None:
            await db_session.refresh(producto_color)

    @classmethod
    async def validate_color(cls, db_session: AsyncSession, color_id: UUID) -> None:
        if await ColorRepository(db_session).get_by_id(color_id) is None:
            raise cls._invalid_reference("color_id", "El color no existe.")

    @classmethod
    async def _validate_unique_color(
        cls,
        repository: ProductoColorRepository,
        producto_id: UUID,
        color_id: UUID,
        exclude_id: UUID | None = None,
    ) -> None:
        existing = await repository.get_active_by_producto_and_color(
            producto_id,
            color_id,
            exclude_id=exclude_id,
        )
        if existing is not None:
            raise cls._duplicate_color()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        producto_color_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> ProductoColor:
        producto_color = await ProductoColorRepository(db_session).get_by_id(
            producto_color_id,
            include_deleted=include_deleted,
            for_update=for_update,
            load_detail=load_detail,
        )
        if producto_color is None:
            raise AppException(
                "Color del producto no encontrado.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return producto_color

    @staticmethod
    def detail(producto_color: ProductoColor, settings: Settings) -> ProductoColorDetail:
        """
        ProductoColorDetail del color cargado con load_detail, con el precio
        vigente hoy de cada SKU. Lo usan GET /{id}, POST y PATCH.
        """
        return ProductoColorDetail.model_validate(
            producto_color,
            context=SkuService.detail_context(settings),
        )

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
        is_visible: bool | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[ProductoColorListItem]:
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

        producto_colores, total = await ProductoColorRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            producto_id=producto_id,
            color_id=color_id,
            is_visible=is_visible,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[ProductoColorListItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=producto_colores,
        )

    @staticmethod
    async def _at(path: str, check: Awaitable[None]) -> None:
        """Ejecuta una validación e indica en sus detalles la ruta dentro del árbol."""
        try:
            await check
        except AppException as error:
            if path:
                error.details = {
                    f"{path} -> {key}": message for key, message in error.details.items()
                }
            raise

    @classmethod
    async def validate_detail_create(
        cls,
        db_session: AsyncSession,
        data: ProductoColorDetailCreate,
        settings: Settings,
        *,
        path: str = "",
        valid_talla_ids: set[UUID] | None = None,
    ) -> None:
        """
        Valida un color con sus imágenes y SKUs con las mismas reglas que sus
        create individuales. La unicidad dentro del árbol ya la garantiza el
        schema; la del color en un producto existente la valida quien llama.

        path ubica los errores dentro de un árbol mayor (por ejemplo
        "colores -> 1"); valid_talla_ids evita validar dos veces la misma talla
        cuando se validan varios colores.
        """
        prefix = f"{path} -> " if path else ""
        valid_talla_ids = set() if valid_talla_ids is None else valid_talla_ids

        await cls._at(path, cls.validate_color(db_session, data.color_id))

        for imagen_index, imagen in enumerate(data.imagenes):
            await cls._at(
                f"{prefix}imagenes -> {imagen_index}",
                ImagenService.validate_upload_url(db_session, imagen.url, settings),
            )

        sku_repository = SkuRepository(db_session)
        for sku_index, sku in enumerate(data.skus):
            sku_path = f"{prefix}skus -> {sku_index}"
            if sku.talla_id not in valid_talla_ids:
                await cls._at(sku_path, SkuService.validate_talla(db_session, sku.talla_id))
                valid_talla_ids.add(sku.talla_id)
            if sku.codigo_barras is not None:
                await cls._at(
                    sku_path,
                    SkuService.validate_unique_codigo_barras(sku_repository, sku.codigo_barras),
                )

    @staticmethod
    def upload_destinations(
        producto_color: ProductoColor,
        data: ProductoColorDetailCreate,
    ) -> dict[str, str]:
        """Carpeta de Cloudinary a la que se mueve cada imagen del color al confirmarla."""
        folder = ImagenService.folder_for(producto_color.producto_id, producto_color.id)
        return {imagen.url: folder for imagen in data.imagenes}

    @staticmethod
    def add_detail_create(
        db_session: AsyncSession,
        producto_id: UUID,
        data: ProductoColorDetailCreate,
        actor_id: UUID,
    ) -> ProductoColor:
        """Añade a la sesión el color con sus imágenes y SKUs. No hace commit."""
        audit = {"created_by": actor_id, "updated_by": actor_id}
        producto_color = ProductoColor(
            producto_id=producto_id,
            color_id=data.color_id,
            is_visible=data.is_visible,
            **audit,
        )
        ProductoColorRepository(db_session).add(producto_color)

        imagen_repository = ImagenRepository(db_session)
        for imagen in data.imagenes:
            imagen_repository.add(
                Imagen(producto_color_id=producto_color.id, **imagen.model_dump(), **audit)
            )

        sku_repository = SkuRepository(db_session)
        for sku in data.skus:
            sku_repository.add(
                Sku(
                    producto_color_id=producto_color.id,
                    **sku.model_dump(exclude={"precio", "stock"}),
                    precio=SkuService.precio_json(sku.precio),
                    stock=SkuService.stock_json(sku.stock),
                    **audit,
                )
            )
        return producto_color

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: ProductoColorCreate,
        actor_id: UUID,
        settings: Settings,
    ) -> ProductoColor:
        """
        Añade a un producto existente un color con sus imágenes y SKUs, en una
        sola transacción. Todo se valida antes de insertar nada.

        Devuelve el color con su Detail cargado.
        """
        if await ProductoRepository(db_session).get_by_id(data.producto_id) is None:
            raise cls._invalid_reference("producto_id", "El producto no existe.")
        await cls._validate_unique_color(
            ProductoColorRepository(db_session), data.producto_id, data.color_id
        )
        await cls.validate_detail_create(db_session, data, settings)

        producto_color = cls.add_detail_create(db_session, data.producto_id, data, actor_id)
        await cls._commit(db_session)
        await CloudinaryService.confirm_pending_uploads(
            cls.upload_destinations(producto_color, data), settings
        )

        logger.info(
            "Color de producto creado: producto_color_id=%s imagenes=%s skus=%s actor_id=%s",
            producto_color.id,
            len(data.imagenes),
            len(data.skus),
            actor_id,
        )
        # Igual que en el create del producto: se expira para cargar el Detail
        # completo, tomando antes el id para no disparar una carga implícita.
        producto_color_id = producto_color.id
        db_session.expire_all()
        return await cls.get(db_session, producto_color_id, load_detail=True)

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        producto_color_id: UUID,
        data: ProductoColorUpdate,
        actor_id: UUID,
    ) -> ProductoColor:
        """Actualiza la visibilidad. El color y el producto dueño no cambian."""
        changes = data.model_dump(exclude_unset=True)
        producto_color = await cls.get(db_session, producto_color_id, for_update=bool(changes))
        if not changes:
            return await cls.get(db_session, producto_color_id, load_detail=True)

        for field_name, value in changes.items():
            setattr(producto_color, field_name, value)
        producto_color.updated_at = utc_now()
        producto_color.updated_by = actor_id
        await cls._commit(db_session, producto_color)

        logger.info(
            "Color de producto actualizado: producto_color_id=%s actor_id=%s",
            producto_color.id,
            actor_id,
        )
        # Responde lo mismo que GET /{id}: se recarga con su Detail.
        db_session.expire_all()
        return await cls.get(db_session, producto_color_id, load_detail=True)


    @staticmethod
    async def delete_children(
        db_session: AsyncSession,
        producto_color_ids: Sequence[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> None:
        """
        Elimina lógicamente en cascada las imágenes y SKUs de esos colores de
        producto (AGENTS.md §5). No hace commit: lo hace quien coordina el borrado.
        """
        imagenes = await ImagenRepository(db_session).soft_delete_by_producto_color_ids(
            producto_color_ids,
            actor_id,
            now,
        )
        skus = await SkuRepository(db_session).soft_delete_by_producto_color_ids(
            producto_color_ids,
            actor_id,
            now,
        )
        logger.info(
            "Cascada de colores de producto: producto_color_ids=%s imagenes=%s skus=%s",
            list(producto_color_ids),
            imagenes,
            skus,
        )

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        producto_color_id: UUID,
        actor_id: UUID,
    ) -> ProductoColor:
        """
        Eliminación lógica en cascada: también elimina sus imágenes y SKUs. Los
        archivos de las imágenes se conservan en Cloudinary.
        """
        producto_color = await cls.get(db_session, producto_color_id, for_update=True)

        now = utc_now()
        await cls.delete_children(db_session, [producto_color.id], actor_id, now)
        producto_color.is_deleted = True
        producto_color.deleted_at = now
        producto_color.deleted_by = actor_id
        producto_color.updated_at = now
        producto_color.updated_by = actor_id
        await cls._commit(db_session, producto_color)

        logger.info(
            "Color de producto eliminado: producto_color_id=%s actor_id=%s",
            producto_color.id,
            actor_id,
        )
        return producto_color
