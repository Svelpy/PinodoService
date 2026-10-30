from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import get_current_principal, require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.usuarios.schemas import (
    UsuarioChangePassword,
    UsuarioCreate,
    UsuarioResetPassword,
    UsuarioResponse,
    UsuarioResponseAudit,
    UsuarioUpdate,
    UsuarioUpdateMe,
)
from app.domains.usuarios.services import UsuarioService
from app.shared.enums import Action, Module, Role
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/usuarios", tags=["Usuarios"])

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
    "/me",
    response_model=UsuarioResponse,
    summary="Consultar mi usuario",
    responses=_error_responses(401, 404, 500),
)
async def get_me(
    current_user: Annotated[CurrentUser, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> UsuarioResponse:
    return await UsuarioService.get(db_session, current_user.id)


@router.patch(
    "/me",
    response_model=UsuarioResponse,
    summary="Actualizar mi usuario",
    responses=_error_responses(401, 404, 409, 422, 500),
)
async def update_me(
    data: UsuarioUpdateMe,
    current_user: Annotated[CurrentUser, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> UsuarioResponse:
    return await UsuarioService.update(
        db_session,
        current_user.id,
        data,
        current_user.id,
    )


@router.patch(
    "/me/password",
    response_model=UsuarioResponse,
    summary="Cambiar mi contraseña",
    description="Revoca todas las sesiones activas del usuario; debe iniciar sesión de nuevo.",
    responses=_error_responses(400, 401, 404, 422, 500),
)
async def change_my_password(
    data: UsuarioChangePassword,
    current_user: Annotated[CurrentUser, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> UsuarioResponse:
    return await UsuarioService.change_password(
        db_session,
        current_user.id,
        data,
        current_user.id,
    )


@router.get(
    "/",
    response_model=PaginatedResponse[UsuarioResponse],
    summary="Listar usuarios",
    responses=_error_responses(401, 403, 422, 500),
)
async def list_usuarios(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.USUARIO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    rol: Annotated[Role | None, Query()] = None,
) -> PaginatedResponse[UsuarioResponse]:
    return await UsuarioService.list(
        db_session,
        page=page,
        per_page=per_page,
        rol=rol,
    )


@router.post(
    "/",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear usuario",
    description="Solo se pueden crear usuarios con un rol inferior al propio.",
    responses=_error_responses(401, 403, 409, 422, 500),
)
async def create_usuario(
    data: UsuarioCreate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.USUARIO, Action.CREATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> UsuarioResponse:
    return await UsuarioService.create(
        db_session,
        data,
        actor_id=current_user.id,
        actor_role=current_user.rol,
    )


@router.get(
    "/{usuario_id}",
    response_model=UsuarioResponse,
    summary="Consultar usuario",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_usuario(
    usuario_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.USUARIO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> UsuarioResponse:
    return await UsuarioService.get(db_session, usuario_id)


@router.get(
    "/{usuario_id}/audit",
    response_model=UsuarioResponseAudit,
    summary="Consultar auditoría de usuario",
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def get_usuario_audit(
    usuario_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.USUARIO, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> UsuarioResponseAudit:
    return await UsuarioService.get(db_session, usuario_id)


@router.patch(
    "/{usuario_id}",
    response_model=UsuarioResponse,
    summary="Actualizar usuario",
    description=(
        "Solo se pueden modificar usuarios con un rol inferior al propio, y "
        "solo se pueden asignar roles inferiores al propio."
    ),
    responses=_error_responses(401, 403, 404, 409, 422, 500),
)
async def update_usuario(
    usuario_id: UUID,
    data: UsuarioUpdate,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.USUARIO, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> UsuarioResponse:
    return await UsuarioService.update(
        db_session,
        usuario_id,
        data,
        current_user.id,
        current_user.rol,
    )


@router.patch(
    "/{usuario_id}/password",
    response_model=UsuarioResponse,
    summary="Restablecer contraseña de usuario",
    description=(
        "Solo para usuarios con un rol inferior al propio. Revoca todas las "
        "sesiones activas del usuario afectado."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def reset_usuario_password(
    usuario_id: UUID,
    data: UsuarioResetPassword,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.USUARIO, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> UsuarioResponse:
    return await UsuarioService.reset_password(
        db_session,
        usuario_id,
        data,
        current_user.id,
        current_user.rol,
    )


@router.delete(
    "/{usuario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar usuario",
    description=(
        "Eliminación lógica. Solo para usuarios con un rol inferior al propio. "
        "Revoca todas las sesiones activas del usuario eliminado."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def delete_usuario(
    usuario_id: UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.USUARIO, Action.DELETE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await UsuarioService.delete(
        db_session,
        usuario_id,
        current_user.id,
        current_user.rol,
    )
