from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.categorias.repositories import CategoriaRepository
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException


class CategoriaProductoService:
    """
    Categorías de un producto (tabla de enlace N:M). No tiene rutas propias: el
    conjunto completo se reemplaza desde POST y PATCH /productos con
    categoria_ids, que validan y aplican con este service.
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
    async def validate_categorias(
        cls,
        db_session: AsyncSession,
        categoria_ids: list[UUID],
        seccion_id: UUID,
    ) -> None:
        """
        Cada categoría debe existir, pertenecer a la sección del producto y ser
        una hoja: los productos se asignan a la categoría más específica, y las
        categorías padre los muestran a través de sus subcategorías.
        """
        repository = CategoriaRepository(db_session)
        categorias = await repository.get_many_by_ids(categoria_ids)
        found_ids = {categoria.id for categoria in categorias}
        missing_ids = [categoria_id for categoria_id in categoria_ids if categoria_id not in found_ids]
        if missing_ids:
            raise cls._invalid_categorias("Categorías inexistentes", missing_ids)

        other_section_ids = [
            categoria.id for categoria in categorias if categoria.seccion_id != seccion_id
        ]
        if other_section_ids:
            raise cls._invalid_categorias(
                "Categorías de otra sección que el producto",
                other_section_ids,
            )

        con_subcategorias = await repository.list_ids_with_active_children(categoria_ids)
        if con_subcategorias:
            raise cls._invalid_categorias(
                "Categorías con subcategorías; asigna una de sus subcategorías",
                [categoria_id for categoria_id in categoria_ids if categoria_id in con_subcategorias],
            )

    @classmethod
    async def apply_categorias(
        cls,
        db_session: AsyncSession,
        producto_id: UUID,
        seccion_id: UUID,
        categoria_ids: list[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> tuple[int, int]:
        """
        Deja al producto exactamente en categoria_ids, validadas contra
        seccion_id: conserva los enlaces que siguen, elimina lógicamente los que
        sobran y crea los nuevos. No hace commit: lo hace quien coordina, con el
        producto ya bloqueado. Devuelve (añadidas, quitadas).

        Lo usan POST y PATCH /productos/{id}.
        """
        await cls.validate_categorias(db_session, categoria_ids, seccion_id)

        repository = CategoriaProductoRepository(db_session)
        current_links = await repository.list_active_by_producto(producto_id, for_update=True)
        current_ids = {link.categoria_id for link in current_links}
        target_ids = set(categoria_ids)

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
        for categoria_id in categoria_ids:
            if categoria_id not in current_ids:
                repository.add(
                    CategoriaProducto(
                        categoria_id=categoria_id,
                        producto_id=producto_id,
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
                added += 1

        return added, removed

    @staticmethod
    def concurrent_change() -> AppException:
        return AppException(
            "Las categorías del producto cambiaron al mismo tiempo; vuelve a intentarlo.",
            409,
            ErrorCode.CONFLICT,
        )
