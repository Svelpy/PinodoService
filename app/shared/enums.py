from enum import Enum

class Role(str, Enum):
    SUPERADMIN = "SUPERADMIN"
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    


class Module(str, Enum):
    USUARIO = "USUARIO"
    CONFIG = "CONFIG"
    SECCION = "SECCION"
    CATEGORIA = "CATEGORIA"
    PRODUCTO = "PRODUCTO"
    CATEGORIA_PRODUCTO = "CATEGORIA_PRODUCTO"
    COLOR = "COLOR"
    PRODUCTO_COLOR = "PRODUCTO_COLOR"
    IMAGEN = "IMAGEN"
    TALLA = "TALLA"
    SKU = "SKU"


class Action(str, Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class TipoImagen(str, Enum):
    MODELO = "MODELO"
    PRENDA = "PRENDA"
    DETALLE = "DETALLE"


