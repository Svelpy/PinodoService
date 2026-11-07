from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.colores.models import Color
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.domains.skus.models import Sku
from app.domains.tallas.models import Talla
from app.domains.venta_items.models import VentaItem


@dataclass(frozen=True)
class SkuParaVenta:
    """Un SKU activo con los datos de su catálogo que se copian al snapshot del ítem."""

    sku: Sku
    producto_nombre: str
    color_nombre: str
    talla_etiqueta: str


class VentaItemRepository:
    """
    Acceso a datos de los ítems de venta. No tiene service ni rutas propias:
    lo usa VentaService. No hace commit.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_skus_para_venta(
        self,
        sku_ids: Sequence[UUID],
        *,
        for_update: bool = False,
    ) -> dict[UUID, SkuParaVenta]:
        """
        SKUs activos de esos ids con su producto, color y talla. Los ids que no
        aparecen en el resultado no existen o fueron eliminados.

        Con for_update bloquea solo las filas de los SKUs, en orden de id para
        que dos ventas simultáneas no se bloqueen mutuamente al tocar el stock.
        """
        if not sku_ids:
            return {}
        statement = (
            select(Sku, Producto.nombre, Color.nombre, Talla.etiqueta)
            .join(ProductoColor, Sku.producto_color_id == ProductoColor.id)
            .join(Producto, ProductoColor.producto_id == Producto.id)
            .join(Color, ProductoColor.color_id == Color.id)
            .join(Talla, Sku.talla_id == Talla.id)
            .where(Sku.id.in_(sku_ids), Sku.is_deleted.is_(False))
            .order_by(Sku.id)
        )
        if for_update:
            statement = statement.with_for_update(of=Sku)

        result = await self.db_session.execute(statement)
        return {
            sku.id: SkuParaVenta(sku, producto_nombre, color_nombre, talla_etiqueta)
            for sku, producto_nombre, color_nombre, talla_etiqueta in result.all()
        }

    def add(self, item: VentaItem) -> None:
        self.db_session.add(item)

    async def soft_delete_by_ids(
        self,
        item_ids: Sequence[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> int:
        """Elimina lógicamente esos ítems activos. Devuelve cuántos marcó."""
        if not item_ids:
            return 0
        result = await self.db_session.execute(
            update(VentaItem)
            .where(VentaItem.id.in_(item_ids), VentaItem.is_deleted.is_(False))
            .values(
                is_deleted=True,
                deleted_at=now,
                deleted_by=actor_id,
                updated_at=now,
                updated_by=actor_id,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount
