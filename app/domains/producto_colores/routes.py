from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.producto_colores.schemas import (
    ProductoColorCreate,
    ProductoColorDetail,
    ProductoColorResponseAudit,
    ProductoColorUpdate,
)
from app.domains.producto_colores.services import ProductoColorService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse


router = APIRouter(prefix="/producto-colores", tags=["Colores de producto"])

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
    response_model=ProductoColorDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Añadir color a un producto",
    description=(
        "Añade a un producto existente un color con sus imágenes y SKUs, en la "
        "misma transacción. Si falla cualquier parte, no se guarda nada. Las "
        "imágenes se suben antes con POST /imagenes/uploads y aquí se envía su "
        "url. Sin imagenes ni skus añade solo el color. Un producto no puede "
        "tener el mismo color dos veces. Responde la ficha del color, igual que "
        "GET /producto-colores/{id}."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_producto_color(
    data: ProductoColorCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProductoColorDetail:
    producto_color = await ProductoColorService.create(db_session, data, current_user.id, settings)
    return ProductoColorService.detail(producto_color, settings)


@router.get(
    "/{producto_color_id}",
    response_model=ProductoColorDetail,
    summary="Consultar color de producto",
    description=(
        "Incluye el color, la galería de imágenes en orden (MODELO, PRENDA, "
        "DETALLE) y los SKUs ordenados por talla, cada uno con su talla."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_producto_color(
    producto_color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProductoColorDetail:
    producto_color = await ProductoColorService.get(db_session, producto_color_id, load_detail=True)
    return ProductoColorService.detail(producto_color, settings)


@router.get(
    "/{producto_color_id}/audit",
    response_model=ProductoColorResponseAudit,
    summary="Consultar auditoría de color de producto",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_producto_color_audit(
    producto_color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.AUDIT)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductoColorResponseAudit:
    return await ProductoColorService.get(db_session, producto_color_id, include_deleted=True)


@router.patch(
    "/{producto_color_id}",
    response_model=ProductoColorDetail,
    summary="Actualizar color de producto",
    description=(
        "Edita el color con sus imágenes y SKUs en una transacción, con el mismo "
        "body que la creación; lo que se omite no cambia. Cambiar color_id "
        "corrige la etiqueta del color sin tocar sus imágenes, SKUs ni stock; "
        "el producto no puede tener ya ese color (409). "
        "imagenes reemplaza la galería emparejando por url ([] quita todas); las "
        "nuevas se suben antes con POST /imagenes/uploads. En skus, una fila con "
        "id actualiza ese SKU (solo los campos enviados; precio completo) y una "
        "sin id crea uno nuevo; un SKU que no se envía no cambia. Las filas con "
        "id no aceptan stock: se ajusta con PATCH /skus/{id}. sku_ids_eliminar "
        "elimina SKUs del color y libera su talla y su código de barras para "
        "las filas de la misma petición. Responde la ficha del color, igual que "
        "GET /producto-colores/{id}."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_producto_color(
    producto_color_id: UUID,
    data: ProductoColorUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProductoColorDetail:
    producto_color = await ProductoColorService.update(
        db_session,
        producto_color_id,
        data,
        current_user.id,
        settings,
    )
    return ProductoColorService.detail(producto_color, settings)


@router.delete(
    "/{producto_color_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar color de producto",
    description=(
        "Eliminación lógica en cascada: también elimina sus imágenes y SKUs. Los "
        "archivos de las imágenes se conservan en Cloudinary."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def delete_producto_color(
    producto_color_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.PRODUCTO_COLOR, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await ProductoColorService.delete(db_session, producto_color_id, current_user.id)
