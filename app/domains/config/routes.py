from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission, require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.config.schemas import (
    HORARIO_DESCRIPTION,
    REDES_SOCIALES_DESCRIPTION,
    ConfigMantenimientoUpdate,
    ConfigResponse,
    ConfigResponseAudit,
    ConfigUpdate,
)
from app.domains.config.services import ConfigService
from app.shared.enums import Action, Module, Role
from app.shared.errors.exceptions import body_validation_error
from app.shared.schemas.errors import ErrorResponse


# La fila única (id = 1) se crea con el seed seeds/config.py; la API solo la lee y la edita.
router = APIRouter(prefix="/config", tags=["Config"])

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
    response_model=ConfigResponse,
    summary="Consultar configuración de la tienda",
    responses=_error_responses(401, 403, 404, 500),
)
async def get_config(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CONFIG, Action.READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigResponse:
    return await ConfigService.get(db_session)


@router.get(
    "/audit",
    response_model=ConfigResponseAudit,
    summary="Consultar auditoría de la configuración",
    responses=_error_responses(401, 403, 404, 500),
)
async def get_config_audit(
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CONFIG, Action.AUDIT)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigResponseAudit:
    return await ConfigService.get(db_session)


@router.patch(
    "/",
    response_model=ConfigResponse,
    summary="Actualizar configuración de la tienda",
    description=(
        "multipart/form-data. Solo se modifican los campos enviados. Un campo "
        "de texto enviado vacío se borra (equivale a null); en nombre_tienda, "
        "horario y redes_sociales se rechaza. horario y "
        "redes_sociales se envían como texto JSON y se reemplazan completos; "
        "envía {} para vaciarlos. logo y favicon son archivos de imagen: se "
        "suben a Cloudinary y reemplazan al anterior. No se admiten SVG ni "
        "archivos de más de 5 MB. Para quitarlos, envía eliminar_logo o "
        "eliminar_favicon en true. El modo mantenimiento no se edita aquí: "
        "usa PATCH /config/mantenimiento."
    ),
    responses=_error_responses(400, 401, 403, 404, 422, 500),
)
async def update_config(
    request: Request,
    current_user: Annotated[
        CurrentUser,
        Depends(require_permission(Module.CONFIG, Action.UPDATE)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    nombre_tienda: Annotated[str | None, Form()] = None,
    descripcion: Annotated[str | None, Form()] = None,
    email_contacto: Annotated[str | None, Form()] = None,
    telefono: Annotated[str | None, Form()] = None,
    whatsapp: Annotated[str | None, Form()] = None,
    direccion: Annotated[str | None, Form()] = None,
    map_url: Annotated[str | None, Form()] = None,
    ciudad: Annotated[str | None, Form()] = None,
    horario: Annotated[
        str | None,
        Form(description=f"Texto JSON. {HORARIO_DESCRIPTION}"),
    ] = None,
    redes_sociales: Annotated[
        str | None,
        Form(description=f"Texto JSON. {REDES_SOCIALES_DESCRIPTION}"),
    ] = None,
    logo: Annotated[UploadFile | None, File(description="Imagen del logo.")] = None,
    favicon: Annotated[UploadFile | None, File(description="Imagen del favicon.")] = None,
    eliminar_logo: Annotated[bool, Form(description="true quita el logo actual.")] = False,
    eliminar_favicon: Annotated[bool, Form(description="true quita el favicon actual.")] = False,
) -> ConfigResponse:
    form_fields = {
        "nombre_tienda": nombre_tienda,
        "descripcion": descripcion,
        "email_contacto": email_contacto,
        "telefono": telefono,
        "whatsapp": whatsapp,
        "direccion": direccion,
        "map_url": map_url,
        "ciudad": ciudad,
        "horario": horario,
        "redes_sociales": redes_sociales,
    }
    # FastAPI entrega None tanto si el campo se omitió como si llegó vacío. Se
    # consulta el formulario para distinguirlos: un campo omitido no se envía
    # al schema y uno vacío llega como null, porque multipart no puede
    # expresar null.
    sent_names = (await request.form()).keys()
    sent_fields = {
        name: value for name, value in form_fields.items() if name in sent_names
    }
    try:
        data = ConfigUpdate.model_validate(sent_fields)
    except ValidationError as error:
        raise body_validation_error(error) from error

    return await ConfigService.update(
        db_session,
        data,
        current_user.id,
        settings,
        # Un selector de archivo vacío llega como un archivo sin nombre.
        logo=logo if logo is not None and logo.filename else None,
        favicon=favicon if favicon is not None and favicon.filename else None,
        eliminar_logo=eliminar_logo,
        eliminar_favicon=eliminar_favicon,
    )


@router.patch(
    "/mantenimiento",
    response_model=ConfigResponse,
    summary="Activar o desactivar el modo mantenimiento",
    description=(
        "Exclusivo de SUPERADMIN. Body JSON con en_mantenimiento (true o "
        "false). Mientras esté en true, la tienda pública responde 503."
    ),
    responses=_error_responses(401, 403, 404, 422, 500),
)
async def update_mantenimiento(
    data: ConfigMantenimientoUpdate,
    current_user: Annotated[CurrentUser, Depends(require_role(Role.SUPERADMIN))],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigResponse:
    return await ConfigService.set_mantenimiento(db_session, data, current_user.id)
