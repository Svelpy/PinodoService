from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.skus.schemas import (
    CodigoBarrasSugerido,
    SkuCreate,
    SkuDetail,
    SkuInventarioItem,
    SkuResponseAudit,
    SkuStockUpdate,
)
from app.domains.skus.services import SkuService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/skus", tags=["SKUs"])

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
    response_model=SkuDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Crear SKU",
    description=(
        "Combinación de un color de producto con una talla, con su precio y stock. "
        "La combinación y el código de barras son únicos."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_sku(
    data: SkuCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SkuDetail:
    sku = await SkuService.create(db_session, data, current_user.id)
    return SkuService.detail(sku, settings)


@router.post(
    "/sugerir-codigo-barras",
    response_model=CodigoBarrasSugerido,
    summary="Sugerir código de barras",
    description=(
        "No recibe nada. Devuelve un EAN-13 de 13 dígitos para uso interno de la "
        "tienda (prefijo GS1 20, que no coincide con códigos de fabricante) que "
        "ningún SKU usa, ni siquiera uno eliminado. No crea nada ni lo reserva: "
        "se envía después como codigo_barras al crear o editar el SKU."
    ),
    responses=_error_responses(401, 403, 500),
)
async def sugerir_codigo_barras(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CodigoBarrasSugerido:
    return CodigoBarrasSugerido(codigo_barras=await SkuService.sugerir_codigo_barras(db_session))


@router.get(
    "/inventario",
    response_model=PaginatedResponse[SkuInventarioItem],
    summary="Inventario de SKUs",
    description=(
        "Todos los SKUs activos con su producto, color, talla y precio_vigente "
        "(el que se cobra hoy). Ordenados por producto, color y talla. "
        "codigo_barras busca la coincidencia exacta, por ejemplo desde un "
        "escáner; nombre busca coincidencias parciales en el nombre del producto. "
        "bajo_minimo=true devuelve los SKUs con stock igual o menor a su mínimo, "
        "sin_codigo_barras=true los que no tienen código y en_rebaja=true los que "
        "tienen una rebaja vigente hoy."
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_inventario(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    codigo_barras: Annotated[str | None, Query(max_length=50)] = None,
    nombre: Annotated[str | None, Query(max_length=200)] = None,
    producto_id: Annotated[UUID | None, Query()] = None,
    color_id: Annotated[UUID | None, Query()] = None,
    talla_id: Annotated[UUID | None, Query()] = None,
    is_visible: Annotated[bool | None, Query()] = None,
    bajo_minimo: Annotated[bool | None, Query()] = None,
    sin_codigo_barras: Annotated[bool | None, Query()] = None,
    en_rebaja: Annotated[bool | None, Query()] = None,
) -> PaginatedResponse[SkuInventarioItem]:
    return await SkuService.list_inventario(
        db_session,
        settings,
        page=page,
        per_page=per_page,
        codigo_barras=codigo_barras,
        nombre=nombre,
        producto_id=producto_id,
        color_id=color_id,
        talla_id=talla_id,
        is_visible=is_visible,
        bajo_minimo=bajo_minimo,
        sin_codigo_barras=sin_codigo_barras,
        en_rebaja=en_rebaja,
    )


@router.get(
    "/{sku_id}",
    response_model=SkuDetail,
    summary="Consultar SKU",
    description="Incluye la talla.",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_sku(
    sku_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SkuDetail:
    sku = await SkuService.get(db_session, sku_id, load_detail=True)
    return SkuService.detail(sku, settings)


@router.get(
    "/{sku_id}/audit",
    response_model=SkuResponseAudit,
    summary="Consultar auditoría de SKU",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_sku_audit(
    sku_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.AUDIT)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> SkuResponseAudit:
    return await SkuService.get(db_session, sku_id, include_deleted=True)


@router.patch(
    "/{sku_id}/stock",
    response_model=SkuDetail,
    summary="Cambiar stock mínimo de un SKU",
    description=(
        "minimo es el stock a partir del cual el SKU aparece como bajo mínimo. "
        "La cantidad no se cambia aquí: entra y sale con movimientos del kardex "
        "(POST /movimientos-inventario/). Responde el SKU, igual que GET /skus/{id}."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def update_sku_stock(
    sku_id: UUID,
    data: SkuStockUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SkuDetail:
    sku = await SkuService.update_stock(db_session, sku_id, data, current_user.id)
    return SkuService.detail(sku, settings)


@router.delete(
    "/{sku_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar SKU",
    description="Eliminación lógica.",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def delete_sku(
    sku_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.SKU, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await SkuService.delete(db_session, sku_id, current_user.id)
