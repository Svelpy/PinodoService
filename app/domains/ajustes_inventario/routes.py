from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.ajustes_inventario.schemas import (
    AjusteInventarioCreate,
    AjusteInventarioDetail,
    AjusteInventarioResponse,
    AjusteInventarioResultado,
)
from app.domains.ajustes_inventario.services import AjusteInventarioService
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.shared.enums import Action, Module, MotivoAjuste
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/ajustes-inventario", tags=["Kardex"])

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


@router.post(
    "/",
    response_model=AjusteInventarioResultado,
    status_code=status.HTTP_201_CREATED,
    summary="Ajustar stock",
    description=(
        "Crea un documento de ajuste (Ajuste #N) para uno o varios SKUs con un "
        "mismo motivo, en una sola transacción: se aplica a todos o a ninguno. "
        "Por motivo, cada ítem envía: RECEPCION, cantidad (> 0) y "
        "costo_unitario, y recalcula el costo promedio; CONTEO, cantidad_contada "
        "(lo que hay en el estante) y se registra la diferencia; MERMA y "
        "ROBO_PERDIDA, cantidad (> 0, las unidades que salen); CORRECCION, "
        "cantidad positiva o negativa, con nota obligatoria. INICIAL no se "
        "acepta: lo registra el sistema al crear SKUs con stock. Un ajuste no se "
        "edita ni se elimina; un error se corrige con otra CORRECCION. En un "
        "CONTEO, los SKUs que ya cuadran vuelven en sin_diferencia, y si ninguno "
        "cambia no se crea documento (ajuste null). 422 si un SKU no existe; 409 "
        "con stock_actual en details si algún stock quedaría negativo."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_ajuste_inventario(
    data: AjusteInventarioCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.MOVIMIENTO_INVENTARIO, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> AjusteInventarioResultado:
    return await AjusteInventarioService.create(db_session, data, current_user.id)


@router.get(
    "/",
    response_model=PaginatedResponse[AjusteInventarioResponse],
    summary="Listar ajustes de inventario",
    description=(
        "Documentos de ajuste del más reciente al más antiguo, con sus totales: "
        "items (SKUs), unidades y valor (cantidad × costo_unitario). Incluye la "
        "carga INICIAL que generan los SKUs nuevos. desde y hasta son fechas de "
        "la tienda, ambas incluidas."
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_ajustes_inventario(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.MOVIMIENTO_INVENTARIO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    motivo: Annotated[MotivoAjuste | None, Query()] = None,
    created_by: Annotated[UUID | None, Query()] = None,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> PaginatedResponse[AjusteInventarioResponse]:
    return await AjusteInventarioService.list(
        db_session,
        settings,
        page=page,
        per_page=per_page,
        motivo=motivo,
        created_by=created_by,
        desde=desde,
        hasta=hasta,
    )


@router.get(
    "/{ajuste_id}",
    response_model=AjusteInventarioDetail,
    summary="Consultar ajuste de inventario",
    description="El documento con sus totales y sus líneas: los movimientos del kardex que registró.",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_ajuste_inventario(
    ajuste_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.MOVIMIENTO_INVENTARIO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> AjusteInventarioDetail:
    return await AjusteInventarioService.get(db_session, ajuste_id)
