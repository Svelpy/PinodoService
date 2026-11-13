from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.movimientos_inventario.schemas import MovimientoInventarioResponse, SkuCosto
from app.domains.movimientos_inventario.services import MovimientoInventarioService
from app.shared.enums import Action, Module, MotivoAjuste, TipoMovimiento
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


@router.get(
    "/",
    response_model=PaginatedResponse[MovimientoInventarioResponse],
    summary="Listar movimientos de inventario (kardex)",
    description=(
        "Libro de movimientos de stock, del más reciente al más antiguo. Cada "
        "fila trae la prenda resumida (sku), el documento que la causó (origen: "
        "Ajuste #N con su motivo o Venta #N) y el usuario responsable, con costo_total = cantidad × "
        "costo_unitario y saldo_valor = saldo × costo_promedio. Con sku_id es el "
        "kardex de esa prenda. motivo filtra por el motivo del ajuste; ajuste_id "
        "y venta_id, por documento; user_id, por usuario responsable. desde y hasta son fechas de la tienda, ambas "
        "incluidas. Los movimientos se registran con los ajustes "
        "(POST /ajustes-inventario/) y las ventas; no se crean ni se editan aquí."
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
    motivo: Annotated[MotivoAjuste | None, Query()] = None,
    ajuste_id: Annotated[UUID | None, Query()] = None,
    venta_id: Annotated[UUID | None, Query()] = None,
    user_id: Annotated[UUID | None, Query()] = None,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> PaginatedResponse[MovimientoInventarioResponse]:
    return await MovimientoInventarioService.list(
        db_session,
        settings,
        page=page,
        per_page=per_page,
        sku_id=sku_id,
        tipo=tipo,
        motivo=motivo,
        ajuste_id=ajuste_id,
        venta_id=venta_id,
        user_id=user_id,
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
    response_model=MovimientoInventarioResponse,
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
) -> MovimientoInventarioResponse:
    return await MovimientoInventarioService.get(db_session, movimiento_id)
