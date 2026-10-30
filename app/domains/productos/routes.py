from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.productos.schemas import (
    ProductoCreate,
    ProductoDetail,
    ProductoListItem,
    ProductoResponse,
    ProductoResponseAudit,
    ProductoUpdate,
)
from app.domains.productos.services import ProductoService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/productos", tags=["Productos"])

ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


def _error_responses(*status_codes: int) -> dict[int, dict[str, object]]:
    return {status_code: ERROR_RESPONSES[status_code] for status_code in status_codes}


@router.get(
    "/",
    response_model=PaginatedResponse[ProductoListItem],
    summary="Listar productos",
    description=(
        "Ordenados del más reciente al más antiguo. categoria_id devuelve los "
        "productos asignados a esa categoría; nombre busca coincidencias parciales."
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_productos(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    seccion_id: Annotated[UUID | None, Query()] = None,
    categoria_id: Annotated[UUID | None, Query()] = None,
    is_visible: Annotated[bool | None, Query()] = None,
    nombre: Annotated[str | None, Query(max_length=200)] = None,
) -> PaginatedResponse[ProductoListItem]:
    return await ProductoService.list(
        db_session,
        page=page,
        per_page=per_page,
        seccion_id=seccion_id,
        categoria_id=categoria_id,
        is_visible=is_visible,
        nombre=nombre,
    )


@router.post(
    "/",
    response_model=ProductoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear producto",
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_producto(
    data: ProductoCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoResponse:
    return await ProductoService.create(db_session, data, current_user.id)


@router.get(
    "/{producto_id}",
    response_model=ProductoDetail,
    summary="Consultar producto",
    description=(
        "Ficha completa: sección, categorías en el orden en que se asignaron y "
        "colores con su galería de imágenes y sus SKUs ordenados por talla."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_producto(
    producto_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoDetail:
    return await ProductoService.get(db_session, producto_id, load_detail=True)


@router.get(
    "/{producto_id}/audit",
    response_model=ProductoResponseAudit,
    summary="Consultar auditoría de producto",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_producto_audit(
    producto_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoResponseAudit:
    return await ProductoService.get(db_session, producto_id)


@router.patch(
    "/{producto_id}",
    response_model=ProductoResponse,
    summary="Actualizar producto",
    description=(
        "Los textos opcionales aceptan null para borrarlos. Un producto asignado "
        "a categorías no puede cambiar de sección."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_producto(
    producto_id: UUID,
    data: ProductoUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoResponse:
    return await ProductoService.update(db_session, producto_id, data, current_user.id)


@router.delete(
    "/{producto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar producto",
    description=(
        "Eliminación lógica en cascada: también elimina sus colores con sus "
        "imágenes y SKUs, y lo quita de sus categorías."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def delete_producto(
    producto_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await ProductoService.delete(db_session, producto_id, current_user.id)
