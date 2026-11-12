from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.venta_pagos.schemas import (
    VentaPagoDetail,
    VentaPagoResponseAudit,
)
from app.domains.venta_pagos.services import VentaPagoService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse


# Los pagos se registran con su venta (POST /ventas/ o POST
# /ventas/{id}/confirmar) y se consultan desde ella (GET /ventas/{id}). Aquí
# solo se sube su comprobante y se consulta su auditoría; un pago no se edita
# ni se anula: para devolverlo se anula la venta.
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
