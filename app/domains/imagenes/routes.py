from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.imagenes.schemas import (
    ImagenBibliotecaItem,
    ImagenCreate,
    ImagenDetail,
    ImagenResponseAudit,
    ImagenUpdate,
    ImagenUploadResponse,
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
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


def _error_responses(*status_codes: int) -> dict[int, dict[str, object]]:
    return {status_code: ERROR_RESPONSES[status_code] for status_code in status_codes}


@router.get(
    "/biblioteca",
    response_model=PaginatedResponse[ImagenBibliotecaItem],
    summary="Biblioteca de imágenes",
    description=(
        "Todas las imágenes activas con el producto y el color a los que "
        "pertenecen, de la más reciente a la más antigua. nombre busca "
        "coincidencias parciales en el nombre del producto. Las subidas "
        "pendientes de POST /imagenes/uploads no aparecen hasta que se asocian "
        "a un color."
    ),
    responses=_error_responses(401, 403, 422, 500),
)
async def list_biblioteca(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    producto_id: Annotated[UUID | None, Query()] = None,
    color_id: Annotated[UUID | None, Query()] = None,
    tipo: Annotated[TipoImagen | None, Query()] = None,
    nombre: Annotated[str | None, Query(max_length=200)] = None,
) -> PaginatedResponse[ImagenBibliotecaItem]:
    return await ImagenService.list_biblioteca(
        db_session,
        page=page,
        per_page=per_page,
        producto_id=producto_id,
        color_id=color_id,
        tipo=tipo,
        nombre=nombre,
    )


@router.post(
    "/",
    response_model=ImagenDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Añadir imagen a un color",
    description=(
        "Asocia a un color existente una imagen ya subida con POST "
        "/imagenes/uploads: se envía su url, no el archivo. La url debe ser una "
        "subida del proyecto que no esté asociada a otra imagen (409). Al "
        "guardarse, la imagen se mueve en Cloudinary a la carpeta de su color; su "
        "url no cambia."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_imagen(
    data: ImagenCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ImagenDetail:
    return await ImagenService.create(db_session, data, current_user.id, settings)


@router.post(
    "/uploads",
    response_model=ImagenUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir el archivo de una imagen",
    description=(
        "multipart/form-data con el archivo. Es el único endpoint que recibe "
        "archivos de imágenes de producto: lo sube a Cloudinary, en la carpeta "
        "de pendientes, y devuelve su url sin crear ningún registro. La url se "
        "envía después en POST /productos/, POST /producto-colores/ o POST "
        "/imagenes/, que la asocian a su color. Las que no se usen se consideran "
        "huérfanas. No se admiten SVG ni archivos de más de 5 MB."
    ),
    responses=_error_responses(400, 401, 403, 422, 500),
)
async def upload_imagen_pendiente(
    file: Annotated[UploadFile, File(description="Archivo de imagen.")],
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.IMAGEN, Action.CREATE)),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ImagenUploadResponse:
    url = await ImagenService.upload_pending(file, settings, current_user.id)
    return ImagenUploadResponse(url=url)


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
        Depends(require_permission(Module.IMAGEN, Action.AUDIT)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ImagenResponseAudit:
    return await ImagenService.get(db_session, imagen_id, include_deleted=True)


@router.patch(
    "/{imagen_id}",
    response_model=ImagenDetail,
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
) -> ImagenDetail:
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
