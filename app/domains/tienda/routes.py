"""
Tienda pública: endpoints abiertos, sin login, de solo lectura.

Todos tienen rate limit por IP. Mientras config.en_mantenimiento sea true,
todos salvo GET /tienda/config responden 503 con code MAINTENANCE.
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.tienda.schemas import (
    TiendaConfig,
    TiendaFiltros,
    TiendaNavegacionSeccion,
    TiendaProductoCard,
    TiendaProductoDetalle,
)
from app.domains.tienda.services import TiendaService
from app.middlewares.limiter import limiter
from app.shared.enums import OrdenTienda
from app.shared.schemas.errors import ErrorResponse
from app.shared.schemas.pagination import PaginatedResponse


router = APIRouter(prefix="/tienda", tags=["Tienda"])

# Una página de la tienda hace pocas llamadas (config, navegación, listado o
# ficha y filtros); el límite deja navegar con holgura y frena el scraping.
RATE_LIMIT = "120/minute"

ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "No existe o no está visible en la tienda."},
    422: {"model": ErrorResponse, "description": "Los parámetros enviados no son válidos."},
    429: {"model": ErrorResponse, "description": "Se superó el límite de solicitudes."},
    500: {"model": ErrorResponse, "description": "Error interno."},
    503: {"model": ErrorResponse, "description": "La tienda está en mantenimiento."},
}


def _error_responses(*status_codes: int) -> dict[int, dict[str, object]]:
    return {status_code: ERROR_RESPONSES[status_code] for status_code in status_codes}


async def tienda_abierta(db_session: Annotated[AsyncSession, Depends(get_db)]) -> None:
    """Responde 503 mientras la tienda esté en mantenimiento."""
    await TiendaService.verificar_abierta(db_session)


SeccionQuery = Annotated[
    UUID | None,
    Query(description="Solo productos de esta sección visible (404 si no lo es)."),
]
CategoriaQuery = Annotated[
    UUID | None,
    Query(
        description=(
            "Productos de esta categoría o de sus subcategorías visibles. Es el id "
            "de la URL /{slug}-l{id} (404 si no está visible)."
        )
    ),
]
BusquedaQuery = Annotated[
    str | None,
    Query(max_length=100, description="Busca coincidencias parciales en el nombre."),
]


@router.get(
    "/config",
    response_model=TiendaConfig,
    summary="Datos de la tienda",
    description=(
        "Nombre, logo, contacto, horario y redes. Responde aunque la tienda esté "
        "en mantenimiento: con en_mantenimiento en true, el frontend no muestra "
        "la tienda."
    ),
    responses=_error_responses(404, 429, 500),
)
@limiter.limit(RATE_LIMIT)
async def get_config(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> TiendaConfig:
    return TiendaConfig.model_validate(await TiendaService.get_config(db_session))


@router.get(
    "/navegacion",
    response_model=list[TiendaNavegacionSeccion],
    dependencies=[Depends(tienda_abierta)],
    summary="Menú de la tienda",
    description=(
        "Secciones visibles, cada una con el árbol de sus categorías visibles. "
        "Una categoría oculta oculta también sus subcategorías."
    ),
    responses=_error_responses(429, 500, 503),
)
@limiter.limit(RATE_LIMIT)
async def get_navegacion(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> list[TiendaNavegacionSeccion]:
    return await TiendaService.navegacion(db_session)


@router.get(
    "/productos",
    response_model=PaginatedResponse[TiendaProductoCard],
    dependencies=[Depends(tienda_abierta)],
    summary="Listar productos de la tienda",
    description=(
        "Productos visibles de secciones visibles con al menos una talla visible; "
        "los agotados también se listan, con agotado en true. color_id y talla_id "
        "se repiten para elegir varios (?color_id=a&color_id=b). Los filtros de "
        "color, talla, disponible, en_rebaja y precio se cumplen en una misma "
        "talla: negro y M con disponible=true exige un negro en M con stock. El "
        "precio es el vigente hoy. Los productos asignados a una subcategoría "
        "oculta no aparecen al filtrar por su categoría padre."
    ),
    responses=_error_responses(404, 422, 429, 500, 503),
)
@limiter.limit(RATE_LIMIT)
async def list_productos(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=60)] = 24,
    orden: Annotated[
        OrdenTienda,
        Query(description="NOVEDADES (por defecto), PRECIO_ASC o PRECIO_DESC por precio desde."),
    ] = OrdenTienda.NOVEDADES,
    seccion_id: SeccionQuery = None,
    categoria_id: CategoriaQuery = None,
    q: BusquedaQuery = None,
    color_id: Annotated[list[UUID] | None, Query(max_length=30)] = None,
    talla_id: Annotated[list[UUID] | None, Query(max_length=30)] = None,
    disponible: Annotated[
        bool | None,
        Query(description="true: solo con stock; false: solo agotados."),
    ] = None,
    en_rebaja: Annotated[bool | None, Query()] = None,
    precio_min: Annotated[Decimal | None, Query(ge=0, max_digits=10, decimal_places=2)] = None,
    precio_max: Annotated[Decimal | None, Query(ge=0, max_digits=10, decimal_places=2)] = None,
) -> PaginatedResponse[TiendaProductoCard]:
    return await TiendaService.listar_productos(
        db_session,
        settings,
        page=page,
        per_page=per_page,
        orden=orden,
        seccion_id=seccion_id,
        categoria_id=categoria_id,
        q=q,
        color_ids=color_id,
        talla_ids=talla_id,
        disponible=disponible,
        en_rebaja=en_rebaja,
        precio_min=precio_min,
        precio_max=precio_max,
    )


@router.get(
    "/productos/filtros",
    response_model=TiendaFiltros,
    dependencies=[Depends(tienda_abierta)],
    summary="Opciones de filtro",
    description=(
        "Colores, tallas, rango de precios vigentes y si hay rebajas entre los "
        "productos visibles de la sección, categoría o búsqueda indicadas. Sirve "
        "para mostrar solo las opciones que devuelven resultados."
    ),
    responses=_error_responses(404, 422, 429, 500, 503),
)
@limiter.limit(RATE_LIMIT)
async def get_filtros(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    seccion_id: SeccionQuery = None,
    categoria_id: CategoriaQuery = None,
    q: BusquedaQuery = None,
) -> TiendaFiltros:
    return await TiendaService.filtros(
        db_session,
        settings,
        seccion_id=seccion_id,
        categoria_id=categoria_id,
        q=q,
    )


@router.get(
    "/productos/{producto_id}",
    response_model=TiendaProductoDetalle,
    dependencies=[Depends(tienda_abierta)],
    summary="Ficha de producto",
    description=(
        "producto_id es el id de la URL /{slug}-p{id}. Si el slug de la URL no "
        "coincide con el de la respuesta, el frontend debe redirigir a la URL "
        "canónica. Solo incluye colores visibles con alguna talla visible, sus "
        "imágenes y sus tallas visibles."
    ),
    responses=_error_responses(404, 422, 429, 500, 503),
)
@limiter.limit(RATE_LIMIT)
async def get_producto(
    request: Request,
    producto_id: UUID,
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TiendaProductoDetalle:
    return await TiendaService.get_producto(db_session, settings, producto_id)
