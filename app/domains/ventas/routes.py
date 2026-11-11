from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.ventas.schemas import (
    VentaCreate,
    VentaDetail,
    VentaEstadoUpdate,
    VentaItemsUpdate,
    VentaPaginatedResponse,
    VentaResponseAudit,
)
from app.domains.ventas.services import VentaService
from app.shared.enums import Action, CanalVenta, EstadoVenta, MetodoPago, Module
from app.shared.schemas.errors import ErrorResponse


router = APIRouter(prefix="/ventas", tags=["Ventas"])

ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}

SCOPE_DESCRIPTION = " Un CAJERO solo accede a las ventas que registró; las demás responden 404."


def _error_responses(*status_codes: int) -> dict[int, dict[str, object]]:
    return {status_code: ERROR_RESPONSES[status_code] for status_code in status_codes}


@router.post(
    "/",
    response_model=VentaDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar venta",
    description=(
        "Crea la venta con sus ítems y sus pagos. Los precios y los datos del "
        "producto, color, talla y código de barras se copian del SKU (snapshot), "
        "con la rebaja vigente hoy. estado es PENDIENTE por defecto (pedido sin "
        "cobrar; sus pagos son anticipos); CONFIRMADA la cobra en la misma "
        "petición y descuenta el stock, por ejemplo en una venta de mostrador: "
        "sus pagos, que pueden ser mixtos, deben sumar el total. Responde 409 si "
        "no hay stock suficiente, si los pagos superan el total o si una venta "
        "confirmada no queda pagada completa."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_venta(
    data: VentaCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VentaDetail:
    return await VentaService.create(db_session, data, current_user, settings)


@router.get(
    "/",
    response_model=VentaPaginatedResponse,
    summary="Listar ventas",
    description=(
        "De la más reciente a la más antigua. desde y hasta son fechas de la "
        "tienda, ambas incluidas. metodo_pago filtra las ventas con algún pago "
        "por ese método. resumen suma todas las ventas filtradas, no solo las de "
        "la página: lo cobrado en las confirmadas por método de pago (y su "
        "total), el total de las pendientes y sus anticipos, y el de las "
        "canceladas. Ignora los filtros estado y metodo_pago para mostrar siempre "
        "el desglose completo."
        + SCOPE_DESCRIPTION
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_ventas(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    estado: Annotated[EstadoVenta | None, Query()] = None,
    canal: Annotated[CanalVenta | None, Query()] = None,
    metodo_pago: Annotated[MetodoPago | None, Query()] = None,
    created_by: Annotated[UUID | None, Query()] = None,
    numero: Annotated[int | None, Query(ge=1)] = None,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> VentaPaginatedResponse:
    return await VentaService.list(
        db_session,
        current_user,
        settings,
        page=page,
        per_page=per_page,
        estado=estado,
        canal=canal,
        metodo_pago=metodo_pago,
        created_by=created_by,
        numero=numero,
        desde=desde,
        hasta=hasta,
    )


@router.get(
    "/{venta_id}",
    response_model=VentaDetail,
    summary="Consultar venta",
    description="Incluye sus ítems y sus pagos." + SCOPE_DESCRIPTION,
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_venta(
    venta_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> VentaDetail:
    return await VentaService.get(db_session, venta_id, current_user, load_detail=True)


@router.get(
    "/{venta_id}/audit",
    response_model=VentaResponseAudit,
    summary="Consultar auditoría de venta",
    description="Añade quién hizo el último cambio (updated_by).",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_venta_audit(
    venta_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA, Action.AUDIT)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> VentaResponseAudit:
    return await VentaService.get(db_session, venta_id, current_user)


@router.put(
    "/{venta_id}/items",
    response_model=VentaDetail,
    summary="Reemplazar ítems de venta",
    description=(
        "Solo para ventas PENDIENTE. items reemplaza la lista completa: los SKUs "
        "que siguen se actualizan, los que faltan se eliminan y los nuevos se "
        "crean. Por defecto la venta se trata como una proforma: los ítems que ya "
        "estaban conservan el precio y los nombres con que se ofrecieron y solo "
        "cambian su cantidad y su descuento; los nuevos entran con el precio del "
        "día. Con recalcular_precios=true todos los ítems toman los precios y "
        "nombres del día (422 si un descuento ya no cabe). Los totales siempre se "
        "recalculan; 409 si el nuevo total queda por debajo de lo ya pagado. "
        "canal, descuento, referencia, cliente_telefono y nota solo cambian si se "
        "envían. Un SKU eliminado del catálogo responde 422 hasta quitarlo."
        + SCOPE_DESCRIPTION
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def replace_venta_items(
    venta_id: UUID,
    data: VentaItemsUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VentaDetail:
    return await VentaService.replace_items(db_session, venta_id, data, current_user, settings)


@router.patch(
    "/{venta_id}/estado",
    response_model=VentaDetail,
    summary="Confirmar o cancelar venta",
    description=(
        "CONFIRMADA cobra una venta pendiente, descuenta el stock y fija "
        "confirmada_at. Por defecto la cobra como una proforma, tal como se "
        "ofreció. Con recalcular_precios: true antes la actualiza con los precios "
        "y nombres del día (conserva cantidades y descuentos); 422 si un "
        "descuento ya no cabe en el precio nuevo. 409 si no alcanza el stock o "
        "algún SKU fue eliminado. pagos cobra el saldo en la misma petición: "
        "junto con los anticipos deben sumar exactamente el total (no hay fiado); "
        "si no, 409. recalcular_precios y pagos solo se envían al confirmar. "
        "CANCELADA anula la venta y fija cancelada_at; todos sus pagos se "
        "devuelven y total_pagado queda como lo devuelto. Si estaba confirmada, "
        "devuelve el stock y exige permiso para anular ventas cobradas (un "
        "CAJERO solo cancela pendientes). Una venta cancelada no cambia más."
        + SCOPE_DESCRIPTION
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def change_venta_estado(
    venta_id: UUID,
    data: VentaEstadoUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.VENTA, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VentaDetail:
    return await VentaService.change_estado(db_session, venta_id, data, current_user, settings)
