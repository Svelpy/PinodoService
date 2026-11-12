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
    VENTA_PAGO = "VENTA_PAGO"
    MOVIMIENTO_INVENTARIO = "MOVIMIENTO_INVENTARIO"


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
    """Dónde el cliente se comprometió a comprar, no por dónde paga."""

    TIENDA = "TIENDA"  # venta presencial en el local
    WHATSAPP = "WHATSAPP"  # cliente escribe directo por WhatsApp
    TIKTOK_LIVE = "TIKTOK_LIVE"  # venta tomada durante una transmisión en vivo
    TIKTOK = "TIKTOK"  # DM o TikTok Shop, fuera del live
    INSTAGRAM = "INSTAGRAM"  # DM de Instagram
    FACEBOOK = "FACEBOOK"  # Messenger / Marketplace
    PAGINA_WEB = "PAGINA_WEB"  # pedido desde el catálogo público
    OTROS = "OTROS"



class EstadoVenta(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADA = "CONFIRMADA"
    CANCELADA = "CANCELADA"


class MetodoPago(str, Enum):
    EFECTIVO = "EFECTIVO"
    TARJETA = "TARJETA"
    CHEQUE = "CHEQUE"
    VALES = "VALES" 
    OTROS = "OTROS"
    QR = "QR"
    TRANSFERENCIA = "TRANSFERENCIA"


class TipoMovimiento(str, Enum):
    INGRESO = "INGRESO"
    VENTA = "VENTA"
    ANULACION = "ANULACION"
    AJUSTE = "AJUSTE"
