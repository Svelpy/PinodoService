from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.imagenes.schemas import (
    ImagenCreate,
    ImagenDetail,
    ImagenListItem,
    ImagenResponse,
    ImagenResponseAudit,
    ImagenUpdate,
)
from app.domains.imagenes.services import ImagenService
from app.shared.enums import Action, Module, TipoImagen
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/imagenes", tags=["Imágenes"])

ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
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
    response_model=PaginatedResponse[ImagenListItem],
    summary="Listar imágenes",
    description=(
        "Orden de galería: primero MODELO, luego PRENDA y al final DETALLE; dentro "
        "de cada tipo, por orden de subida. Filtra por producto_color_id para "
        "obtener la galería de un color."
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_imagenes(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    producto_color_id: Annotated[UUID | None, Query()] = None,
    tipo: Annotated[TipoImagen | None, Query()] = None,
) -> PaginatedResponse[ImagenListItem]:
    return await ImagenService.list(
        db_session,
        page=page,
        per_page=per_page,
        producto_color_id=producto_color_id,
        tipo=tipo,
    )


@router.post(
    "/",
    response_model=ImagenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir imagen",
    description=(
        "multipart/form-data con el archivo y los datos de la imagen. Se sube a "
        "Cloudinary y se guarda su URL segura. No se admiten SVG ni archivos de "
        "más de 5 MB."
    ),
    responses=_error_responses(400, 401, 403, 422, 500),
)
async def create_imagen(
    file: Annotated[UploadFile, File(description="Archivo de imagen.")],
    producto_color_id: Annotated[UUID, Form()],
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    tipo: Annotated[TipoImagen, Form()] = TipoImagen.MODELO,
) -> ImagenResponse:
    return await ImagenService.create(
        db_session,
        ImagenCreate(producto_color_id=producto_color_id, tipo=tipo),
        file,
        current_user.id,
        settings,
    )


@router.get(
    "/{imagen_id}",
    response_model=ImagenDetail,
    summary="Consultar imagen",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_imagen(
    imagen_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ImagenDetail:
    return await ImagenService.get(db_session, imagen_id)


@router.get(
    "/{imagen_id}/audit",
    response_model=ImagenResponseAudit,
    summary="Consultar auditoría de imagen",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_imagen_audit(
    imagen_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ImagenResponseAudit:
    return await ImagenService.get(db_session, imagen_id)


@router.patch(
    "/{imagen_id}",
    response_model=ImagenResponse,
    summary="Cambiar el tipo de una imagen",
    description="Solo se puede cambiar el tipo. Para cambiar la foto, elimínala y sube otra.",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def update_imagen(
    imagen_id: UUID,
    data: ImagenUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ImagenResponse:
    return await ImagenService.update(db_session, imagen_id, data, current_user.id)


@router.delete(
    "/{imagen_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar imagen",
    description="Eliminación lógica. El archivo se conserva en Cloudinary.",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def delete_imagen(
    imagen_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await ImagenService.delete(db_session, imagen_id, current_user.id)
