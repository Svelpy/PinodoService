from enum import Enum

class Role(str, Enum):
    SUPERADMIN = "SUPERADMIN"
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    CAJERO = "CAJERO"



class Module(str, Enum):
    USUARIO = "USUARIO"
    CONFIG = "CONFIG"
    SECCION = "SECCION"
    CATEGORIA = "CATEGORIA"
    PRODUCTO = "PRODUCTO"
    COLOR = "COLOR"
    PRODUCTO_COLOR = "PRODUCTO_COLOR"
    IMAGEN = "IMAGEN"
    TALLA = "TALLA"
    SKU = "SKU"
    VENTA = "VENTA"


class Action(str, Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    AUDIT = "AUDIT"


class TipoImagen(str, Enum):
    MODELO = "MODELO"
    PRENDA = "PRENDA"
    DETALLE = "DETALLE"




class OrdenTienda(str, Enum):
    """Orden del listado de productos de la tienda pública."""

    NOVEDADES = "NOVEDADES"
    PRECIO_ASC = "PRECIO_ASC"
    PRECIO_DESC = "PRECIO_DESC"


class CanalVenta(str, Enum):
    WHATSAPP = "WHATSAPP"
    TIENDA = "TIENDA"


class EstadoVenta(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADA = "CONFIRMADA"
    CANCELADA = "CANCELADA"


class MetodoPago(str, Enum):
    EFECTIVO = "EFECTIVO"
    QR = "QR"
    TRANSFERENCIA = "TRANSFERENCIA"
