from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.categoria_productos.schemas import ProductoCategoriasUpdate
from app.domains.categorias.models import Categoria
from app.domains.categorias.repositories import CategoriaRepository
from app.domains.productos.repositories import ProductoRepository
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException


logger = get_logger(__name__)


class CategoriaProductoService:
    """
    Gestión de las categorías de un producto (AGENTS.md §9, tablas de enlace).

    El enlace no es un recurso: el conjunto completo se reemplaza desde el producto.
    """

    @staticmethod
    def _invalid_categorias(message: str, categoria_ids: list[UUID]) -> AppException:
        detail = f"{message}: {', '.join(str(categoria_id) for categoria_id in categoria_ids)}."
        return AppException(
            message + ".",
            422,
            ErrorCode.VALIDATION_ERROR,
            {"categoria_ids": detail},
        )

    @classmethod
    async def replace_categorias(
        cls,
        db_session: AsyncSession,
        producto_id: UUID,
        data: ProductoCategoriasUpdate,
        actor_id: UUID,
    ) -> list[Categoria]:
        """
        Deja al producto exactamente en las categorías recibidas.

        Los enlaces que se mantienen no se tocan, los que sobran se eliminan
        lógicamente y los nuevos se crean, todo en una transacción. Cada
        categoría debe existir y pertenecer a la sección del producto.
        """
        producto = await ProductoRepository(db_session).get_by_id(producto_id, for_update=True)
        if producto is None:
            raise AppException(
                "Producto no encontrado.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )

        categorias = await CategoriaRepository(db_session).get_many_by_ids(data.categoria_ids)
        found_ids = {categoria.id for categoria in categorias}
        missing_ids = [
            categoria_id for categoria_id in data.categoria_ids if categoria_id not in found_ids
        ]
        if missing_ids:
            raise cls._invalid_categorias("Categorías inexistentes", missing_ids)

        other_section_ids = [
            categoria.id for categoria in categorias if categoria.seccion_id != producto.seccion_id
        ]
        if other_section_ids:
            raise cls._invalid_categorias(
                "Categorías de otra sección que el producto",
                other_section_ids,
            )

        repository = CategoriaProductoRepository(db_session)
        current_links = await repository.list_active_by_producto(producto.id, for_update=True)
        current_ids = {link.categoria_id for link in current_links}
        target_ids = set(data.categoria_ids)

        now = utc_now()
        removed = 0
        for link in current_links:
            if link.categoria_id not in target_ids:
                link.is_deleted = True
                link.deleted_at = now
                link.deleted_by = actor_id
                link.updated_at = now
                link.updated_by = actor_id
                removed += 1

        added = 0
        for categoria_id in data.categoria_ids:
            if categoria_id not in current_ids:
                repository.add(
                    CategoriaProducto(
                        categoria_id=categoria_id,
                        producto_id=producto.id,
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
                added += 1

        if removed or added:
            try:
                await db_session.commit()
            except IntegrityError as error:
                await db_session.rollback()
                raise AppException(
                    "Las categorías del producto cambiaron al mismo tiempo; vuelve a intentarlo.",
                    409,
                    ErrorCode.CONFLICT,
                ) from error
            except Exception:
                await db_session.rollback()
                raise

            logger.info(
                "Categorías de producto reemplazadas: producto_id=%s añadidas=%s quitadas=%s actor_id=%s",
                producto.id,
                added,
                removed,
                actor_id,
            )

        return await repository.list_categorias_by_producto(producto.id)
