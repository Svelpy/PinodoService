from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.config.schemas import (
    ConfigResponse,
    ConfigResponseAudit,
    ConfigUpdate,
)
from app.domains.config.services import ConfigService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse


# La fila única (id = 1) se crea con el seed seeds/config.py; la API solo la lee y la edita.
router = APIRouter(prefix="/config", tags=["Config"])

ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


def _error_responses(*status_codes: int) -> dict[int, dict[str, object]]:
    return {status_code: ERROR_RESPONSES[status_code] for status_code in status_codes}


@router.get(
    "/",
    response_model=ConfigResponse,
    summary="Consultar configuración de la tienda",
    responses=_error_responses(401, 403, 404, 500),
)
async def get_config(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CONFIG, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigResponse:
    return await ConfigService.get(db_session)


@router.get(
    "/audit",
    response_model=ConfigResponseAudit,
    summary="Consultar auditoría de la configuración",
    responses=_error_responses(401, 403, 404, 500),
)
async def get_config_audit(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CONFIG, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigResponseAudit:
    return await ConfigService.get(db_session)


@router.patch(
    "/",
    response_model=ConfigResponse,
    summary="Actualizar configuración de la tienda",
    description=(
        "horario y redes_sociales se reemplazan completos; envía {} para "
        "vaciarlos. Los campos opcionales aceptan null para borrarlos."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def update_config(
    data: ConfigUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CONFIG, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigResponse:
    return await ConfigService.update(db_session, data, current_user.id)
