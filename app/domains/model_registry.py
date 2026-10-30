"""Importa todos los modelos persistentes para registrar su metadata."""

from app.domains.auth.models import AuthSession
from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categorias.models import Categoria
from app.domains.colores.models import Color
from app.domains.config.models import Config
from app.domains.error_logs.models import ErrorLog
from app.domains.imagenes.models import Imagen
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.domains.secciones.models import Seccion
from app.domains.skus.models import Sku
from app.domains.tallas.models import Talla
from app.domains.usuarios.models import Usuario

__all__ = [
    "AuthSession",
    "Categoria",
    "CategoriaProducto",
    "Color",
    "Config",
    "ErrorLog",
    "Imagen",
    "Producto",
    "ProductoColor",
    "Seccion",
    "Sku",
    "Talla",
    "Usuario",
]
