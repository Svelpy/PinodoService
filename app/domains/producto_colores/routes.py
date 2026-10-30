from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.producto_colores.schemas import (
    ProductoColorCreate,
    ProductoColorDetail,
    ProductoColorListItem,
    ProductoColorResponse,
    ProductoColorResponseAudit,
    ProductoColorUpdate,
)
from app.domains.producto_colores.services import ProductoColorService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/producto-colores", tags=["Colores de producto"])

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
    response_model=PaginatedResponse[ProductoColorListItem],
    summary="Listar colores de producto",
    description="Ordenados por fecha de creación; filtra por producto_id para ver los colores de un producto.",
    responses=_error_responses(401, 403, 422, 500),
)
async def list_producto_colores(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    producto_id: Annotated[UUID | None, Query()] = None,
    color_id: Annotated[UUID | None, Query()] = None,
    is_visible: Annotated[bool | None, Query()] = None,
) -> PaginatedResponse[ProductoColorListItem]:
    return await ProductoColorService.list(
        db_session,
        page=page,
        per_page=per_page,
        producto_id=producto_id,
        color_id=color_id,
        is_visible=is_visible,
    )


@router.post(
    "/",
    response_model=ProductoColorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Añadir color a un producto",
    description="Un producto no puede tener el mismo color dos veces.",
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_producto_color(
    data: ProductoColorCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoColorResponse:
    return await ProductoColorService.create(db_session, data, current_user.id)


@router.get(
    "/{producto_color_id}",
    response_model=ProductoColorDetail,
    summary="Consultar color de producto",
    description=(
        "Incluye el color, la galería de imágenes en orden (MODELO, PRENDA, "
        "DETALLE) y los SKUs ordenados por talla, cada uno con su talla."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_producto_color(
    producto_color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoColorDetail:
    return await ProductoColorService.get(db_session, producto_color_id, load_detail=True)


@router.get(
    "/{producto_color_id}/audit",
    response_model=ProductoColorResponseAudit,
    summary="Consultar auditoría de color de producto",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_producto_color_audit(
    producto_color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoColorResponseAudit:
    return await ProductoColorService.get(db_session, producto_color_id)


@router.patch(
    "/{producto_color_id}",
    response_model=ProductoColorResponse,
    summary="Actualizar color de producto",
    description=(
        "Permite corregir el color (conserva sus imágenes y SKUs) o cambiar su "
        "visibilidad. El producto no se puede cambiar."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_producto_color(
    producto_color_id: UUID,
    data: ProductoColorUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoColorResponse:
    return await ProductoColorService.update(
        db_session,
        producto_color_id,
        data,
        current_user.id,
    )


@router.delete(
    "/{producto_color_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar color de producto",
    description=(
        "Eliminación lógica en cascada: también elimina sus imágenes y SKUs. Los "
        "archivos de las imágenes se conservan en Cloudinary."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def delete_producto_color(
    producto_color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await ProductoColorService.delete(db_session, producto_color_id, current_user.id)
