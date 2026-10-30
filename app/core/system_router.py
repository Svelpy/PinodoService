from typing import Literal
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings, get_settings
from app.core.database import check_database_connection
from app.core.logging import get_logger


class HealthResponse(BaseModel):
    status: Literal["healthy", "error"]
    app: str
    version: str
    database: Literal["connected", "disconnected"]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "app": "FarmaTupa_API",
                "version": "1.0.0",
                "database": "connected",
            }
        }
    )

router = APIRouter()
logger = get_logger(__name__)

@router.get("/", include_in_schema=False)
async def root(settings: Settings = Depends(get_settings)):
    """Redirige automáticamente a la documentación interactiva en desarrollo"""
    if settings.DEBUG:
        return RedirectResponse(url="/docs")
    return {"message": settings.APP_NAME, "status": "active"}


@router.get("/health", tags=["Health"],response_model=HealthResponse,responses={503: {"model": HealthResponse,"description": "La aplicación o PostgreSQL no están disponibles."}})
async def health_check(request: Request,settings: Settings = Depends(get_settings)) -> HealthResponse | JSONResponse:
    """
    Endpoint de salud operativa (Readiness Probe).
    Comprueba que la aplicación y PostgreSQL estén disponibles.
    """
    
    try:
        database_engine = getattr(request.app.state, "db_engine", None)
        if database_engine is None:
            raise RuntimeError("Base de datos no inicializada")
        
        await check_database_connection(database_engine)
        return HealthResponse(
            status="healthy",
            app=settings.APP_NAME,
            version=settings.APP_VERSION,
            database="connected",
        )
            
    except Exception:
        logger.exception("Falló la comprobación de salud de PostgreSQL")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "app": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "database": "disconnected",
            },
        )
