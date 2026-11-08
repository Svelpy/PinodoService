"""
Schemas de la tienda pública.

Son propios de la tienda y no reutilizan los de administración: nunca exponen
auditoría, is_visible, códigos de barras ni la cantidad de stock (solo si hay
o no). Las URL siguen el estilo de Zara: un slug decorativo seguido del id,
`/{slug}-p{id}` para un producto y `/{slug}-l{id}` para una categoría. El
backend busca solo por id; el slug se devuelve para que el frontend construya
la URL canónica y redirija si la recibida no coincide.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.shared.enums import TipoImagen
from app.shared.schemas.tree import TreeResponse


SLUG_PRODUCTO_DESCRIPTION = (
    "Slug decorativo calculado del nombre. URL canónica: /{slug}-p{id}."
)
SLUG_CATEGORIA_DESCRIPTION = (
    "Slug decorativo con la sección y la categoría, por ejemplo "
    "mujer-vestidos-midi para la subcategoría «Vestidos midi». URL canónica: "
    "/{slug}-l{id}."
)


def _money(value: Decimal | None) -> float | None:
    # La API expone los importes como números JSON, igual que en administración.
    return None if value is None else float(value)


class TiendaConfig(BaseModel):
    """Datos públicos de la tienda. Se pueden leer aunque esté en mantenimiento."""

    nombre_tienda: str
    descripcion: str | None
    logo_url: str | None
    favicon_url: str | None
    email_contacto: str | None
    telefono: str | None
    whatsapp: str | None
    direccion: str | None
    map_url: str | None
    ciudad: str | None
    horario: dict[str, str]
    redes_sociales: dict[str, str]
    en_mantenimiento: bool

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "nombre_tienda": "Tienda Moda",
                "descripcion": "Ropa para mujer, hombre y niños.",
                "logo_url": "https://res.cloudinary.com/demo/image/upload/logo.png",
                "favicon_url": "https://res.cloudinary.com/demo/image/upload/favicon.png",
                "email_contacto": "contacto@tienda.com",
                "telefono": "71234567",
                "whatsapp": "+59171234567",
                "direccion": "Avenida Principal 123",
                "map_url": "https://maps.google.com/?q=-17.78,-63.18",
                "ciudad": "Santa Cruz",
                "horario": {"lunes": "09:00-20:00", "sábado": "10:00-14:00"},
                "redes_sociales": {"instagram": "https://instagram.com/tiendamoda"},
                "en_mantenimiento": False,
            }
        },
    )


class TiendaSeccion(BaseModel):
    id: UUID
    nombre: str
    slug: str

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "33333333-3333-4333-8333-333333333333",
                "nombre": "Mujer",
                "slug": "mujer",
            }
        },
    )


class TiendaCategoria(BaseModel):
    id: UUID
    nombre: str
    slug: str = Field(description=SLUG_CATEGORIA_DESCRIPTION)

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "44444444-4444-4444-8444-444444444444",
                "nombre": "Vestidos",
                "slug": "mujer-vestidos",
            }
        },
    )


class TiendaNavegacionSeccion(TiendaSeccion):
    """Una sección visible con el árbol de sus categorías visibles, para el menú."""

    categorias: TreeResponse[TiendaCategoria]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "33333333-3333-4333-8333-333333333333",
                "nombre": "Mujer",
                "slug": "mujer",
                "categorias": {
                    "total": 2,
                    "data": [
                        {
                            "data": {
                                "id": "44444444-4444-4444-8444-444444444444",
                                "nombre": "Vestidos",
                                "slug": "mujer-vestidos",
                            },
                            "children": [
                                {
                                    "data": {
                                        "id": "55555555-5555-4555-8555-555555555555",
                                        "nombre": "Vestidos midi",
                                        "slug": "mujer-vestidos-midi",
                                    },
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            }
        },
    )


class TiendaColor(BaseModel):
    id: UUID
    nombre: str
    codigo_hex: str

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "66666666-6666-4666-8666-666666666666",
                "nombre": "Negro",
                "codigo_hex": "#000000",
            }
        },
    )


class TiendaTalla(BaseModel):
    id: UUID
    etiqueta: str

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "77777777-7777-4777-8777-777777777777",
                "etiqueta": "M",
            }
        },
    )


class TiendaImagen(BaseModel):
    url: str
    tipo: TipoImagen

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "url": "https://res.cloudinary.com/demo/image/upload/vestido.jpg",
                "tipo": "MODELO",
            }
        },
    )


class TiendaSku(BaseModel):
    """
    Una talla del color. precio_vigente es el que se cobra hoy: el rebajado
    mientras la rebaja siga vigente (rebaja_hasta incluido) y, si no, el normal.
    """

    id: UUID
    talla: TiendaTalla
    precio_normal: Decimal
    precio_vigente: Decimal
    en_rebaja: bool
    rebaja_hasta: date | None = Field(
        description="Último día de la rebaja; null si no tiene fecha de fin o no está en rebaja."
    )
    disponible: bool

    @field_serializer("precio_normal", "precio_vigente", when_used="json")
    def serialize_money(self, value: Decimal) -> float | None:
        return _money(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "88888888-8888-4888-8888-888888888888",
                "talla": {
                    "id": "77777777-7777-4777-8777-777777777777",
                    "etiqueta": "M",
                },
                "precio_normal": 29.95,
                "precio_vigente": 19.95,
                "en_rebaja": True,
                "rebaja_hasta": "2026-12-31",
                "disponible": True,
            }
        },
    )


class TiendaProductoColor(BaseModel):
    """Un color visible del producto, con su galería y sus tallas visibles."""

    id: UUID
    color: TiendaColor
    agotado: bool
    imagenes: list[TiendaImagen]
    skus: list[TiendaSku]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "99999999-9999-4999-8999-999999999999",
                "color": {
                    "id": "66666666-6666-4666-8666-666666666666",
                    "nombre": "Negro",
                    "codigo_hex": "#000000",
                },
                "agotado": False,
                "imagenes": [
                    {
                        "url": "https://res.cloudinary.com/demo/image/upload/vestido.jpg",
                        "tipo": "MODELO",
                    }
                ],
                "skus": [
                    {
                        "id": "88888888-8888-4888-8888-888888888888",
                        "talla": {
                            "id": "77777777-7777-4777-8777-777777777777",
                            "etiqueta": "M",
                        },
                        "precio_normal": 29.95,
                        "precio_vigente": 19.95,
                        "en_rebaja": True,
                        "rebaja_hasta": "2026-12-31",
                        "disponible": True,
                    }
                ],
            }
        },
    )


class TiendaProductoBase(BaseModel):
    """
    Campos comunes de la tarjeta y la ficha. Los precios son el rango entre las
    tallas visibles: precio_desde/hasta con el precio vigente hoy y
    precio_normal_desde/hasta sin rebajas, para mostrar el precio tachado.
    """

    id: UUID
    slug: str = Field(description=SLUG_PRODUCTO_DESCRIPTION)
    nombre: str
    precio_desde: Decimal
    precio_hasta: Decimal
    precio_normal_desde: Decimal
    precio_normal_hasta: Decimal
    en_rebaja: bool = Field(description="true si alguna talla visible está en rebaja hoy.")
    agotado: bool = Field(description="true si ninguna talla visible tiene stock.")

    @field_serializer(
        "precio_desde",
        "precio_hasta",
        "precio_normal_desde",
        "precio_normal_hasta",
        when_used="json",
    )
    def serialize_money(self, value: Decimal) -> float | None:
        return _money(value)


class TiendaProductoCard(TiendaProductoBase):
    """Producto en el listado de la tienda."""

    portada_url: str | None = Field(
        description="Primera imagen del primer color visible que tenga imágenes."
    )
    colores: list[TiendaColor]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "22222222-2222-4222-8222-222222222222",
                "slug": "vestido-midi-satinado",
                "nombre": "Vestido midi satinado",
                "precio_desde": 19.95,
                "precio_hasta": 29.95,
                "precio_normal_desde": 29.95,
                "precio_normal_hasta": 29.95,
                "en_rebaja": True,
                "agotado": False,
                "portada_url": "https://res.cloudinary.com/demo/image/upload/vestido.jpg",
                "colores": [
                    {
                        "id": "66666666-6666-4666-8666-666666666666",
                        "nombre": "Negro",
                        "codigo_hex": "#000000",
                    }
                ],
            }
        },
    )


class TiendaProductoDetalle(TiendaProductoBase):
    """Ficha pública del producto."""

    descripcion: str | None
    cuidados: str | None
    composicion: str | None
    seccion: TiendaSeccion
    categorias: list[TiendaCategoria] = Field(
        description="Categorías visibles del producto, en el orden en que se asignaron."
    )
    colores: list[TiendaProductoColor]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "22222222-2222-4222-8222-222222222222",
                "slug": "vestido-midi-satinado",
                "nombre": "Vestido midi satinado",
                "precio_desde": 19.95,
                "precio_hasta": 29.95,
                "precio_normal_desde": 29.95,
                "precio_normal_hasta": 29.95,
                "en_rebaja": True,
                "agotado": False,
                "descripcion": "Vestido de tirantes con caída fluida.",
                "cuidados": "Lavar a mano en agua fría.",
                "composicion": "100 % poliéster",
                "seccion": {
                    "id": "33333333-3333-4333-8333-333333333333",
                    "nombre": "Mujer",
                    "slug": "mujer",
                },
                "categorias": [
                    {
                        "id": "44444444-4444-4444-8444-444444444444",
                        "nombre": "Vestidos",
                        "slug": "mujer-vestidos",
                    }
                ],
                "colores": [
                    {
                        "id": "99999999-9999-4999-8999-999999999999",
                        "color": {
                            "id": "66666666-6666-4666-8666-666666666666",
                            "nombre": "Negro",
                            "codigo_hex": "#000000",
                        },
                        "agotado": False,
                        "imagenes": [
                            {
                                "url": "https://res.cloudinary.com/demo/image/upload/vestido.jpg",
                                "tipo": "MODELO",
                            }
                        ],
                        "skus": [
                            {
                                "id": "88888888-8888-4888-8888-888888888888",
                                "talla": {
                                    "id": "77777777-7777-4777-8777-777777777777",
                                    "etiqueta": "M",
                                },
                                "precio_normal": 29.95,
                                "precio_vigente": 19.95,
                                "en_rebaja": True,
                                "rebaja_hasta": "2026-12-31",
                                "disponible": True,
                            }
                        ],
                    }
                ],
            }
        },
    )


class TiendaFiltros(BaseModel):
    """
    Opciones de filtro disponibles entre los productos visibles del alcance
    pedido (sección, categoría y búsqueda). precio_min y precio_max son null si
    no hay productos.
    """

    colores: list[TiendaColor]
    tallas: list[TiendaTalla]
    precio_min: Decimal | None
    precio_max: Decimal | None
    hay_rebajas: bool

    @field_serializer("precio_min", "precio_max", when_used="json")
    def serialize_money(self, value: Decimal | None) -> float | None:
        return _money(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "colores": [
                    {
                        "id": "66666666-6666-4666-8666-666666666666",
                        "nombre": "Negro",
                        "codigo_hex": "#000000",
                    }
                ],
                "tallas": [
                    {
                        "id": "77777777-7777-4777-8777-777777777777",
                        "etiqueta": "M",
                    }
                ],
                "precio_min": 19.95,
                "precio_max": 59.9,
                "hay_rebajas": True,
            }
        },
    )
