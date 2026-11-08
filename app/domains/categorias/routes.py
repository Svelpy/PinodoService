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
    CategoriaResponseAudit,
    CategoriaUpdate,
)
from app.domains.categorias.services import CategoriaService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse


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
    "/arbol",
    response_model=list[CategoriaArbolSeccion],
    summary="Árbol de categorías por sección",
    description=(
        "Sin seccion_id devuelve todas las secciones con su árbol de categorías, "
        "incluidas las secciones sin categorías. Con seccion_id devuelve solo esa "
        "sección (404 si no existe). "
        "is_visible filtra por la visibilidad efectiva: una categoría se ve solo si "
        "ella, todas sus categorías padre y su sección son visibles. "
        "Sin is_visible devuelve todo; is_visible=true solo lo visible; "
        "is_visible=false solo lo oculto, con cada rama oculta colgando de su "
        "sección y las secciones ocultas completas."
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
    is_visible: Annotated[bool | None, Query()] = None,
) -> list[CategoriaArbolSeccion]:
    return await CategoriaService.arbol(
        db_session,
        seccion_id=seccion_id,
        is_visible=is_visible,
    )


@router.post(
    "/",
    response_model=CategoriaDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Crear categoría",
    description=(
        "El slug se genera a partir del nombre. El nombre es único entre "
        "hermanas: mismo padre o, en las raíces, misma sección. "
        "La categoría padre no puede tener productos asignados (409), porque los "
        "productos solo se asignan a categorías sin subcategorías. "
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
) -> CategoriaDetail:
    return await CategoriaService.create(db_session, data, current_user.id)


@router.get(
    "/{categoria_id}",
    response_model=CategoriaDetail,
    summary="Consultar categoría",
    description=(
        "Incluye la sección y el árbol completo de categorías de esa sección, "
        "visibles y ocultas, para ubicar la categoría (ruta, hermanas y "
        "descendientes) y elegir un nuevo padre."
    ),
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
    return await CategoriaService.get_detail(db_session, categoria_id)


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
        Depends(require_permission(Module.CATEGORIA, Action.AUDIT)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CategoriaResponseAudit:
    return await CategoriaService.get(db_session, categoria_id, include_deleted=True)


@router.patch(
    "/{categoria_id}",
    response_model=CategoriaDetail,
    summary="Actualizar categoría",
    description=(
        "Cambia el nombre, la visibilidad o el lugar en el árbol. La sección no "
        "se modifica. parent_id mueve la categoría con sus subcategorías y "
        "productos; null la convierte en raíz. El nuevo padre debe ser de la "
        "misma sección, no puede ser una de sus subcategorías ni tener productos "
        "asignados (409). El nombre es único entre hermanas (mismo padre o, en "
        "las raíces, misma sección): si cambia el nombre o el padre, el slug se "
        "regenera y se revalida (409)."
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
) -> CategoriaDetail:
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
