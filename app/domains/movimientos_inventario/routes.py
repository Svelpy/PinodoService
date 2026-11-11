from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.movimientos_inventario.schemas import (
    MovimientoInventarioCreate,
    MovimientoInventarioDetail,
    MovimientoInventarioListItem,
    MovimientoInventarioResponseAudit,
    SkuCosto,
)
from app.domains.movimientos_inventario.services import MovimientoInventarioService
from app.shared.enums import Action, Module, TipoMovimiento
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/movimientos-inventario", tags=["Kardex"])

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
    response_model=MovimientoInventarioDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar ingreso o ajuste de stock",
    description=(
        "INGRESO: entra mercadería; cantidad positiva y costo_unitario "
        "obligatorio; recalcula el costo promedio del SKU. AJUSTE: merma, "
        "conteo físico o regalo; cantidad positiva o negativa y motivo "
        "obligatorio; no cambia el costo. Un movimiento no se edita ni se "
        "elimina: un error se corrige con otro AJUSTE. 409 con stock_actual en "
        "details si el stock quedaría negativo. Las ventas pendientes no "
        "reservan stock."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_movimiento_inventario(
    data: MovimientoInventarioCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.MOVIMIENTO_INVENTARIO, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> MovimientoInventarioDetail:
    return await MovimientoInventarioService.create(db_session, data, current_user.id)


@router.get(
    "/",
    response_model=PaginatedResponse[MovimientoInventarioListItem],
    summary="Listar movimientos de inventario (kardex)",
    description=(
        "Del más reciente al más antiguo. Con sku_id es el kardex de ese SKU: "
        "saldo es el stock que dejó cada movimiento. desde y hasta son fechas "
        "de la tienda, ambas incluidas."
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_movimientos_inventario(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.MOVIMIENTO_INVENTARIO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    sku_id: Annotated[UUID | None, Query()] = None,
    tipo: Annotated[TipoMovimiento | None, Query()] = None,
    venta_id: Annotated[UUID | None, Query()] = None,
    created_by: Annotated[UUID | None, Query()] = None,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> PaginatedResponse[MovimientoInventarioListItem]:
    return await MovimientoInventarioService.list(
        db_session,
        settings,
        page=page,
        per_page=per_page,
        sku_id=sku_id,
        tipo=tipo,
        venta_id=venta_id,
        created_by=created_by,
        desde=desde,
        hasta=hasta,
    )


@router.get(
    "/costos",
    response_model=PaginatedResponse[SkuCosto],
    summary="Consultar costo y valor del stock",
    description=(
        "Stock, costo promedio y valor (cantidad × costo) de cada SKU activo, "
        "con su producto, color y talla. nombre busca coincidencias parciales "
        "en el nombre del producto; codigo_barras, la coincidencia exacta. El "
        "costo se corrige editando el SKU."
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_costos(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.MOVIMIENTO_INVENTARIO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    nombre: Annotated[str | None, Query(max_length=200)] = None,
    codigo_barras: Annotated[str | None, Query(max_length=50)] = None,
    producto_id: Annotated[UUID | None, Query()] = None,
    color_id: Annotated[UUID | None, Query()] = None,
) -> PaginatedResponse[SkuCosto]:
    return await MovimientoInventarioService.list_costos(
        db_session,
        page=page,
        per_page=per_page,
        nombre=nombre,
        codigo_barras=codigo_barras,
        producto_id=producto_id,
        color_id=color_id,
    )


@router.get(
    "/{movimiento_id}",
    response_model=MovimientoInventarioDetail,
    summary="Consultar movimiento de inventario",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_movimiento_inventario(
    movimiento_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.MOVIMIENTO_INVENTARIO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> MovimientoInventarioDetail:
    return await MovimientoInventarioService.get(db_session, movimiento_id, load_detail=True)


@router.get(
    "/{movimiento_id}/audit",
    response_model=MovimientoInventarioResponseAudit,
    summary="Consultar auditoría de movimiento de inventario",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_movimiento_inventario_audit(
    movimiento_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.MOVIMIENTO_INVENTARIO, Action.AUDIT)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> MovimientoInventarioResponseAudit:
    return await MovimientoInventarioService.get(db_session, movimiento_id)
