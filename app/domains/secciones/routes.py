from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.secciones.schemas import (
    SeccionCreate,
    SeccionResponse,
    SeccionResponseAudit,
    SeccionUpdate,
)
from app.domains.secciones.services import SeccionService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/secciones", tags=["Secciones"])

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
    response_model=PaginatedResponse[SeccionResponse],
    summary="Listar secciones",
    responses=_error_responses(401, 403, 422, 500),
)
async def list_secciones(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SECCION, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    is_visible: Annotated[bool | None, Query()] = None,
) -> PaginatedResponse[SeccionResponse]:
    return await SeccionService.list(
        db_session,
        page=page,
        per_page=per_page,
        is_visible=is_visible,
    )


@router.post(
    "/",
    response_model=SeccionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear sección",
    description="El slug se genera a partir del nombre y debe ser único.",
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_seccion(
    data: SeccionCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SECCION, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SeccionResponse:
    return await SeccionService.create(db_session, data, current_user.id)


@router.get(
    "/{seccion_id}",
    response_model=SeccionResponse,
    summary="Consultar sección",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_seccion(
    seccion_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SECCION, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SeccionResponse:
    return await SeccionService.get(db_session, seccion_id)


@router.get(
    "/{seccion_id}/audit",
    response_model=SeccionResponseAudit,
    summary="Consultar auditoría de sección",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_seccion_audit(
    seccion_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SECCION, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SeccionResponseAudit:
    return await SeccionService.get(db_session, seccion_id)


@router.patch(
    "/{seccion_id}",
    response_model=SeccionResponse,
    summary="Actualizar sección",
    description="Si cambia el nombre, el slug se regenera.",
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_seccion(
    seccion_id: UUID,
    data: SeccionUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SECCION, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SeccionResponse:
    return await SeccionService.update(db_session, seccion_id, data, current_user.id)


@router.delete(
    "/{seccion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar sección",
    description=(
        "Eliminación lógica. Se rechaza con 409 si la sección tiene "
        "categorías o productos activos."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def delete_seccion(
    seccion_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SECCION, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await SeccionService.delete(db_session, seccion_id, current_user.id)
