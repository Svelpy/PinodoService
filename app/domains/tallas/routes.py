from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.tallas.schemas import (
    TallaCreate,
    TallaResponse,
    TallaResponseAudit,
    TallaUpdate,
)
from app.domains.tallas.services import TallaService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/tallas", tags=["Tallas"])

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
    response_model=PaginatedResponse[TallaResponse],
    summary="Listar tallas",
    description="Ordenadas por fecha de creación.",
    responses=_error_responses(401, 403, 422, 500),
)
async def list_tallas(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.TALLA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[TallaResponse]:
    return await TallaService.list(db_session, page=page, per_page=per_page)


@router.post(
    "/",
    response_model=TallaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear talla",
    description="La etiqueta debe ser única sin distinguir mayúsculas.",
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_talla(
    data: TallaCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.TALLA, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> TallaResponse:
    return await TallaService.create(db_session, data, current_user.id)


@router.get(
    "/{talla_id}",
    response_model=TallaResponse,
    summary="Consultar talla",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_talla(
    talla_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.TALLA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> TallaResponse:
    return await TallaService.get(db_session, talla_id)


@router.get(
    "/{talla_id}/audit",
    response_model=TallaResponseAudit,
    summary="Consultar auditoría de talla",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_talla_audit(
    talla_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.TALLA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> TallaResponseAudit:
    return await TallaService.get(db_session, talla_id)


@router.patch(
    "/{talla_id}",
    response_model=TallaResponse,
    summary="Actualizar talla",
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_talla(
    talla_id: UUID,
    data: TallaUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.TALLA, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> TallaResponse:
    return await TallaService.update(db_session, talla_id, data, current_user.id)


@router.delete(
    "/{talla_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar talla",
    description=(
        "Eliminación lógica. Se rechaza con 409 si la talla está asignada a "
        "SKUs activos."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def delete_talla(
    talla_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.TALLA, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await TallaService.delete(db_session, talla_id, current_user.id)
