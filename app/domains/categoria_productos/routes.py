from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.categoria_productos.schemas import ProductoCategoriasUpdate
from app.domains.categoria_productos.services import CategoriaProductoService
from app.domains.categorias.schemas import CategoriaResponse
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse


# Tabla de enlace sin datos propios (AGENTS.md §9): no es un recurso con CRUD; la
# relación se reemplaza completa desde el producto.
router = APIRouter(prefix="/productos", tags=["Categorías de producto"])

ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.put(
    "/{producto_id}/categorias",
    response_model=list[CategoriaResponse],
    summary="Reemplazar las categorías de un producto",
    description=(
        "Deja al producto exactamente en las categorías enviadas: conserva las que "
        "ya tenía, quita las que faltan y añade las nuevas. [] quita todas. Cada "
        "categoría debe existir y pertenecer a la misma sección que el producto. "
        "Devuelve las categorías resultantes."
    ),
    responses=ERROR_RESPONSES,
)
async def replace_producto_categorias(
    producto_id: UUID,
    data: ProductoCategoriasUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CATEGORIA_PRODUCTO, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> list[CategoriaResponse]:
    return await CategoriaProductoService.replace_categorias(
        db_session,
        producto_id,
        data,
        current_user.id,
    )
