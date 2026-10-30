from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.skus.schemas import (
    SkuCreate,
    SkuDetail,
    SkuListItem,
    SkuResponse,
    SkuResponseAudit,
    SkuUpdate,
)
from app.domains.skus.services import SkuService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/skus", tags=["SKUs"])

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
    response_model=PaginatedResponse[SkuListItem],
    summary="Listar SKUs",
    description=(
        "Ordenados por color y, dentro de cada color, por el orden de las tallas. "
        "bajo_minimo=true devuelve los SKUs con stock igual o menor a su mínimo."
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_skus(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    producto_color_id: Annotated[UUID | None, Query()] = None,
    talla_id: Annotated[UUID | None, Query()] = None,
    is_visible: Annotated[bool | None, Query()] = None,
    bajo_minimo: Annotated[bool | None, Query()] = None,
) -> PaginatedResponse[SkuListItem]:
    return await SkuService.list(
        db_session,
        page=page,
        per_page=per_page,
        producto_color_id=producto_color_id,
        talla_id=talla_id,
        is_visible=is_visible,
        bajo_minimo=bajo_minimo,
    )


@router.post(
    "/",
    response_model=SkuResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear SKU",
    description=(
        "Combinación de un color de producto con una talla, con su precio y stock. "
        "La combinación y el código de barras son únicos."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_sku(
    data: SkuCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SkuResponse:
    return await SkuService.create(db_session, data, current_user.id)


@router.get(
    "/{sku_id}",
    response_model=SkuDetail,
    summary="Consultar SKU",
    description="Incluye la talla.",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_sku(
    sku_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SkuDetail:
    return await SkuService.get(db_session, sku_id, load_detail=True)


@router.get(
    "/{sku_id}/audit",
    response_model=SkuResponseAudit,
    summary="Consultar auditoría de SKU",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_sku_audit(
    sku_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SkuResponseAudit:
    return await SkuService.get(db_session, sku_id)


@router.patch(
    "/{sku_id}",
    response_model=SkuResponse,
    summary="Actualizar SKU",
    description=(
        "precio y stock se reemplazan completos; al enviar stock se renueva su "
        "fecha de actualización. codigo_barras acepta null para quitarlo. El color "
        "del producto no se puede cambiar."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_sku(
    sku_id: UUID,
    data: SkuUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SkuResponse:
    return await SkuService.update(db_session, sku_id, data, current_user.id)


@router.delete(
    "/{sku_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar SKU",
    description="Eliminación lógica.",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def delete_sku(
    sku_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await SkuService.delete(db_session, sku_id, current_user.id)
