from fastapi import APIRouter

from app.core.system_router import router as system_router
from app.domains.auth.routes import router as auth_router
from app.domains.categoria_productos.routes import router as categoria_productos_router
from app.domains.categorias.routes import router as categorias_router
from app.domains.colores.routes import router as colores_router
from app.domains.config.routes import router as config_router
from app.domains.imagenes.routes import router as imagenes_router
from app.domains.producto_colores.routes import router as producto_colores_router
from app.domains.productos.routes import router as productos_router
from app.domains.secciones.routes import router as secciones_router
from app.domains.skus.routes import router as skus_router
from app.domains.tallas.routes import router as tallas_router
from app.domains.usuarios.routes import router as usuarios_router


no_system_router = APIRouter(prefix="/api/v1")
no_system_router.include_router(auth_router)
no_system_router.include_router(usuarios_router)
no_system_router.include_router(secciones_router)
no_system_router.include_router(colores_router)
no_system_router.include_router(tallas_router)
no_system_router.include_router(config_router)
no_system_router.include_router(categorias_router)
no_system_router.include_router(productos_router)
no_system_router.include_router(producto_colores_router)
no_system_router.include_router(categoria_productos_router)
no_system_router.include_router(imagenes_router)
no_system_router.include_router(skus_router)


api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(no_system_router)
