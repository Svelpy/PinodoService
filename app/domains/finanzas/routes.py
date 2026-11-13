"""
Reportes económicos. Cada reporte tiene dos rutas con los mismos parámetros:
la base responde JSON y /excel entrega el mismo reporte como archivo .xlsx
(hojas Resumen y Detalle). Sin desde ni hasta, cubren toda la historia.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domains.auth.dependencies import require_permission
from app.domains.auth.schemas import CurrentUser
from app.domains.finanzas.schemas import ReporteRentabilidad, ReporteVentas
from app.domains.finanzas.services import FinanzasService
from app.shared.enums import Action, Module
from app.shared.schemas.errors import ErrorResponse
from app.shared.services.excel import XLSX_MEDIA_TYPE


router = APIRouter(prefix="/finanzas", tags=["Finanzas"])

ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}
EXCEL_RESPONSES = {
    200: {
        "content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        "description": "Archivo Excel con las hojas Resumen y Detalle.",
    },
    **ERROR_RESPONSES,
}

Lector = Annotated[CurrentUser, Depends(require_permission(Module.FINANZAS, Action.READ))]
Desde = Annotated[date | None, Query(description="Fecha de la tienda, incluida. Sin ella, desde la primera venta.")]
Hasta = Annotated[date | None, Query(description="Fecha de la tienda, incluida. Sin ella, hasta hoy.")]


def _archivo(nombre: str, contenido: bytes) -> Response:
    return Response(
        content=contenido,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get(
    "/ventas",
    response_model=ReporteVentas,
    summary="Reporte de ventas",
    description=(
        "Cuánto se vendió y cobró, por dónde, quién y cómo se pagó. Solo ventas "
        "confirmadas, por fecha de confirmación. resumen y cobrado_por_metodo "
        "son los totales; detalle, una línea por prenda vendida. Las anuladas "
        "solo cuentan en resumen.ventas_anuladas y resumen.monto_anulado."
    ),
    responses=ERROR_RESPONSES,
)
async def reporte_ventas(
    current_user: Lector,
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    desde: Desde = None,
    hasta: Hasta = None,
) -> ReporteVentas:
    return await FinanzasService.ventas(db_session, settings, desde=desde, hasta=hasta)


@router.get(
    "/ventas/excel",
    response_class=Response,
    summary="Reporte de ventas en Excel",
    description="El mismo reporte que GET /finanzas/ventas, como archivo .xlsx.",
    responses=EXCEL_RESPONSES,
)
async def reporte_ventas_excel(
    current_user: Lector,
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    desde: Desde = None,
    hasta: Hasta = None,
) -> Response:
    nombre, contenido = await FinanzasService.ventas_excel(
        db_session, settings, current_user, desde=desde, hasta=hasta
    )
    return _archivo(nombre, contenido)


@router.get(
    "/rentabilidad",
    response_model=ReporteRentabilidad,
    summary="Reporte de rentabilidad",
    description=(
        "Ingreso − costo = margen bruto de las ventas confirmadas. detalle es "
        "una línea por SKU con el total del período, de mayor a menor margen; "
        "por_mes, la evolución. No incluye gastos: no es la utilidad neta."
    ),
    responses=ERROR_RESPONSES,
)
async def reporte_rentabilidad(
    current_user: Lector,
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    desde: Desde = None,
    hasta: Hasta = None,
) -> ReporteRentabilidad:
    return await FinanzasService.rentabilidad(db_session, settings, desde=desde, hasta=hasta)


@router.get(
    "/rentabilidad/excel",
    response_class=Response,
    summary="Reporte de rentabilidad en Excel",
    description="El mismo reporte que GET /finanzas/rentabilidad, como archivo .xlsx.",
    responses=EXCEL_RESPONSES,
)
async def reporte_rentabilidad_excel(
    current_user: Lector,
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    desde: Desde = None,
    hasta: Hasta = None,
) -> Response:
    nombre, contenido = await FinanzasService.rentabilidad_excel(
        db_session, settings, current_user, desde=desde, hasta=hasta
    )
    return _archivo(nombre, contenido)
