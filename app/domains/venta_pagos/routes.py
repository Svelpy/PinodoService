from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.venta_pagos.schemas import (
    VentaPagoCreate,
    VentaPagoDetail,
    VentaPagoListItem,
    VentaPagoResponseAudit,
    VentaPagoUpdate,
)
from app.domains.venta_pagos.services import VentaPagoService
from app.shared.enums import Action, MetodoPago, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/venta-pagos", tags=["Pagos de venta"])

ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}

SCOPE_DESCRIPTION = " Un CAJERO solo accede a los pagos de las ventas que registró; los demás responden 404."


def _error_responses(*status_codes: int) -> dict[int, dict[str, object]]:
    return {status_code: ERROR_RESPONSES[status_code] for status_code in status_codes}


@router.post(
    "/",
    response_model=VentaPagoDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar pago de venta",
    description=(
        "Registra un pago de una venta PENDIENTE: un anticipo o parte de su "
        "cobro. monto es lo aplicado a la venta, sin el vuelto. 409 si la venta "
        "no está pendiente o si el pago supera su saldo por cobrar. Un pago no "
        "se anula: para devolverlo se cancela la venta completa."
        + SCOPE_DESCRIPTION
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def create_venta_pago(
    data: VentaPagoCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA_PAGO, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> VentaPagoDetail:
    return await VentaPagoService.create(db_session, data, current_user)


@router.get(
    "/",
    response_model=PaginatedResponse[VentaPagoListItem],
    summary="Listar pagos de venta",
    description=(
        "Del más reciente al más antiguo, para conciliar cobros por método. "
        "desde y hasta son fechas de la tienda sobre la fecha del pago, ambas "
        "incluidas. Incluye los pagos de ventas canceladas, que se devolvieron "
        "en su cancelada_at." + SCOPE_DESCRIPTION
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_venta_pagos(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA_PAGO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    venta_id: Annotated[UUID | None, Query()] = None,
    metodo: Annotated[MetodoPago | None, Query()] = None,
    created_by: Annotated[UUID | None, Query()] = None,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> PaginatedResponse[VentaPagoListItem]:
    return await VentaPagoService.list(
        db_session,
        current_user,
        settings,
        page=page,
        per_page=per_page,
        venta_id=venta_id,
        metodo=metodo,
        created_by=created_by,
        desde=desde,
        hasta=hasta,
    )


@router.get(
    "/{pago_id}",
    response_model=VentaPagoDetail,
    summary="Consultar pago de venta",
    responses=_error_responses(401, 403, 404, 422, 500),
    description="Pago de venta." + SCOPE_DESCRIPTION,
)
async def get_venta_pago(
    pago_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA_PAGO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> VentaPagoDetail:
    return await VentaPagoService.get(db_session, pago_id, current_user)


@router.get(
    "/{pago_id}/audit",
    response_model=VentaPagoResponseAudit,
    summary="Consultar auditoría de pago de venta",
    description="Añade quién hizo el último cambio (updated_by).",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_venta_pago_audit(
    pago_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA_PAGO, Action.AUDIT)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> VentaPagoResponseAudit:
    return await VentaPagoService.get(db_session, pago_id, current_user)


@router.patch(
    "/{pago_id}",
    response_model=VentaPagoDetail,
    summary="Actualizar referencia de pago",
    description=(
        "Solo cambia la referencia (número de operación); null la quita. El "
        "monto y el método no se corrigen." + SCOPE_DESCRIPTION
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def update_venta_pago(
    pago_id: UUID,
    data: VentaPagoUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA_PAGO, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> VentaPagoDetail:
    return await VentaPagoService.update(db_session, pago_id, data, current_user)


@router.post(
    "/{pago_id}/comprobante",
    response_model=VentaPagoDetail,
    summary="Subir comprobante de pago",
    description=(
        "multipart/form-data con la imagen del comprobante (captura del QR o de "
        "la transferencia). Reemplaza la anterior. No se admiten SVG ni archivos "
        "de más de 5 MB." + SCOPE_DESCRIPTION
    ),
    responses=_error_responses(400, 401, 403, 404, 422, 500),
)
async def upload_venta_pago_comprobante(
    pago_id: UUID,
    file: Annotated[UploadFile, File(description="Imagen del comprobante.")],
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA_PAGO, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VentaPagoDetail:
    return await VentaPagoService.upload_comprobante(db_session, pago_id, file, current_user, settings)
