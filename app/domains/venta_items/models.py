from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric, text
from sqlmodel import Field

from app.core.base_model import BaseModel


class VentaItem(BaseModel, table=True):
    """
    Línea de una venta. Guarda una copia (snapshot) del producto, color, talla,
    código de barras y precios al momento de vender, para que el historial no
    cambie aunque luego se edite o elimine el catálogo.
    """

    __tablename__ = "venta_items"
    __table_args__ = (
        Index("venta_items_idx_items_sku", "sku_id"),
        # Un SKU aparece una sola vez por venta; varias unidades van en cantidad.
        # Su primera columna también sirve para buscar los ítems de una venta.
        Index(
            "uq_venta_items_venta_sku",
            "venta_id",
            "sku_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint("cantidad > 0", name="ck_venta_items_cantidad_positiva"),
        CheckConstraint("precio_normal >= 0", name="ck_venta_items_precio_normal_no_negativo"),
        CheckConstraint("precio_unitario >= 0", name="ck_venta_items_precio_unitario_no_negativo"),
        CheckConstraint("precio_unitario <= precio_normal", name="ck_venta_items_precio_unitario_hasta_normal"),
        CheckConstraint("descuento_unitario >= 0", name="ck_venta_items_descuento_no_negativo"),
        CheckConstraint("descuento_unitario <= precio_unitario", name="ck_venta_items_descuento_hasta_precio"),
        CheckConstraint(
            "subtotal = (precio_unitario - descuento_unitario) * cantidad",
            name="ck_venta_items_subtotal",
        ),
        {"schema": "public"},
    )

    venta_id: UUID = Field(foreign_key="public.ventas.id", nullable=False)
    sku_id: UUID = Field(foreign_key="public.skus.id", nullable=False)
    cantidad: int = Field(nullable=False)
    # precio["normal"] del SKU al vender: junto a precio_unitario muestra si hubo rebaja.
    precio_normal: Decimal = Field(sa_type=Numeric(12, 2), nullable=False)
    # Precio efectivo cobrado: el rebajado si estaba vigente; si no, el normal.
    precio_unitario: Decimal = Field(sa_type=Numeric(12, 2), nullable=False)
    # Descuento manual extra del cajero por unidad (la rebaja ya va en precio_unitario).
    descuento_unitario: Decimal = Field(default=Decimal("0"), sa_type=Numeric(12, 2), nullable=False)
    subtotal: Decimal = Field(sa_type=Numeric(12, 2), nullable=False)

    producto_nombre: str = Field(max_length=200, nullable=False)
    color_nombre: str = Field(max_length=60, nullable=False)
    talla_etiqueta: str = Field(max_length=30, nullable=False)
    codigo_barras: str | None = Field(default=None, max_length=50, nullable=True)
