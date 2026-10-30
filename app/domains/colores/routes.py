from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.colores.schemas import (
    ColorCreate,
    ColorResponse,
    ColorResponseAudit,
    ColorUpdate,
)
from app.domains.colores.services import ColorService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/colores", tags=["Colores"])

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
    response_model=PaginatedResponse[ColorResponse],
    summary="Listar colores",
    description="Ordenados alfabéticamente por nombre.",
    responses=_error_responses(401, 403, 422, 500),
)
async def list_colores(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.COLOR, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[ColorResponse]:
    return await ColorService.list(db_session, page=page, per_page=per_page)


@router.post(
    "/",
    response_model=ColorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear color",
    description=(
        "El nombre debe ser único: se compara su slug, que ignora mayúsculas, "
        "tildes, espacios y signos."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_color(
    data: ColorCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.COLOR, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ColorResponse:
    return await ColorService.create(db_session, data, current_user.id)


@router.get(
    "/{color_id}",
    response_model=ColorResponse,
    summary="Consultar color",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_color(
    color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.COLOR, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ColorResponse:
    return await ColorService.get(db_session, color_id)


@router.get(
    "/{color_id}/audit",
    response_model=ColorResponseAudit,
    summary="Consultar auditoría de color",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_color_audit(
    color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.COLOR, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ColorResponseAudit:
    return await ColorService.get(db_session, color_id)


@router.patch(
    "/{color_id}",
    response_model=ColorResponse,
    summary="Actualizar color",
    description="Si cambia el nombre, el slug se regenera.",
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_color(
    color_id: UUID,
    data: ColorUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.COLOR, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ColorResponse:
    return await ColorService.update(db_session, color_id, data, current_user.id)


@router.delete(
    "/{color_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar color",
    description=(
        "Eliminación lógica. Se rechaza con 409 si el color está asignado a "
        "productos activos."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def delete_color(
    color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.COLOR, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await ColorService.delete(db_session, color_id, current_user.id)
