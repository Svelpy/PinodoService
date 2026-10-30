from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.services import ProductoColorService
from app.domains.productos.models import Producto
from app.domains.productos.repositories import ProductoRepository
from app.domains.productos.schemas import ProductoCreate, ProductoListItem, ProductoUpdate
from app.domains.secciones.repositories import SeccionRepository
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)


class ProductoService:
    """Reglas de negocio del dominio de productos."""

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
            raise AppException(
                "Los datos del producto entran en conflicto con un registro existente.",
                409,
                ErrorCode.CONFLICT,
            ) from error
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
    async def list(
        db_session: AsyncSession,
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
        return PaginatedResponse[ProductoListItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=productos,
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: ProductoCreate,
        actor_id: UUID,
    ) -> Producto:
        await cls._validate_seccion(db_session, data.seccion_id)

        producto = Producto(
            **data.model_dump(),
            created_by=actor_id,
            updated_by=actor_id,
        )
        ProductoRepository(db_session).add(producto)
        await cls._commit(db_session, producto)

        logger.info("Producto creado: producto_id=%s actor_id=%s", producto.id, actor_id)
        return producto

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        producto_id: UUID,
        data: ProductoUpdate,
        actor_id: UUID,
    ) -> Producto:
        """
        Actualiza un producto. No cambia de sección mientras esté asignado a
        categorías, porque esas categorías pertenecen a la sección anterior.
        """
        changes = data.model_dump(exclude_unset=True)
        producto = await cls.get(db_session, producto_id, for_update=bool(changes))
        if not changes:
            return producto

        if changes.get("seccion_id", producto.seccion_id) != producto.seccion_id:
            await cls._validate_seccion(db_session, changes["seccion_id"])
            if await ProductoRepository(db_session).has_active_categorias(producto.id):
                raise AppException(
                    "No se puede cambiar de sección un producto asignado a categorías.",
                    409,
                    ErrorCode.CONFLICT,
                    {"seccion_id": "Quita antes el producto de sus categorías."},
                )

        for field_name, value in changes.items():
            setattr(producto, field_name, value)
        producto.updated_at = utc_now()
        producto.updated_by = actor_id
        await cls._commit(db_session, producto)

        logger.info("Producto actualizado: producto_id=%s actor_id=%s", producto.id, actor_id)
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
