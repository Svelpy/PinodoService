from fastapi import APIRouter

from app.core.system_router import router as system_router
from app.domains.auth.routes import router as auth_router
from app.domains.usuarios.routes import router as usuarios_router


no_system_router = APIRouter(prefix="/api/v1")
no_system_router.include_router(auth_router)
no_system_router.include_router(usuarios_router)


api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(no_system_router)
