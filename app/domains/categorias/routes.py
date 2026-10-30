from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.categorias.schemas import (
    CategoriaArbolSeccion,
    CategoriaCreate,
    CategoriaDetail,
    CategoriaListItem,
    CategoriaResponse,
    CategoriaResponseAudit,
    CategoriaUpdate,
)
from app.domains.categorias.services import CategoriaService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/categorias", tags=["Categorías"])

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
    response_model=PaginatedResponse[CategoriaListItem],
    summary="Listar categorías",
    responses=_error_responses(401, 403, 422, 500),
)
async def list_categorias(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CATEGORIA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    seccion_id: Annotated[UUID | None, Query()] = None,
    parent_id: Annotated[UUID | None, Query()] = None,
    is_visible: Annotated[bool | None, Query()] = None,
) -> PaginatedResponse[CategoriaListItem]:
    return await CategoriaService.list(
        db_session,
        page=page,
        per_page=per_page,
        seccion_id=seccion_id,
        parent_id=parent_id,
        is_visible=is_visible,
    )


@router.get(
    "/arbol",
    response_model=list[CategoriaArbolSeccion],
    summary="Árbol de categorías por sección",
    description=(
        "Sin seccion_id devuelve todas las secciones con su árbol de categorías, "
        "incluidas las secciones sin categorías. Con seccion_id devuelve solo esa "
        "sección. Incluye secciones y categorías ocultas."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_arbol(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CATEGORIA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    seccion_id: Annotated[UUID | None, Query()] = None,
) -> list[CategoriaArbolSeccion]:
    return await CategoriaService.arbol(db_session, seccion_id=seccion_id)


@router.post(
    "/",
    response_model=CategoriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear categoría",
    description=(
        "El slug se genera a partir del nombre y es único dentro de la sección. "
        "La categoría padre, si se indica, debe pertenecer a la misma sección."
    ),
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_categoria(
    data: CategoriaCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CATEGORIA, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CategoriaResponse:
    return await CategoriaService.create(db_session, data, current_user.id)


@router.get(
    "/{categoria_id}",
    response_model=CategoriaDetail,
    summary="Consultar categoría",
    description="Incluye la sección y las subcategorías directas (un solo nivel).",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_categoria(
    categoria_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CATEGORIA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CategoriaDetail:
    return await CategoriaService.get(db_session, categoria_id, load_detail=True)


@router.get(
    "/{categoria_id}/audit",
    response_model=CategoriaResponseAudit,
    summary="Consultar auditoría de categoría",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_categoria_audit(
    categoria_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CATEGORIA, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CategoriaResponseAudit:
    return await CategoriaService.get(db_session, categoria_id)


@router.patch(
    "/{categoria_id}",
    response_model=CategoriaResponse,
    summary="Actualizar categoría",
    description=(
        "Si cambia el nombre o la sección, el slug se regenera. parent_id null la "
        "convierte en raíz. No se permiten ciclos ni padres de otra sección, y una "
        "categoría con subcategorías activas no puede cambiar de sección."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_categoria(
    categoria_id: UUID,
    data: CategoriaUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CATEGORIA, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CategoriaResponse:
    return await CategoriaService.update(db_session, categoria_id, data, current_user.id)


@router.delete(
    "/{categoria_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar categoría",
    description=(
        "Eliminación lógica. Se rechaza con 409 si la categoría tiene "
        "subcategorías activas. Sus productos no se eliminan: solo salen de ella."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def delete_categoria(
    categoria_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CATEGORIA, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await CategoriaService.delete(db_session, categoria_id, current_user.id)
