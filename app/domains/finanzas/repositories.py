from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.usuarios.models import Usuario
from app.domains.venta_items.models import VentaItem
from app.domains.venta_pagos.models import VentaPago
from app.domains.ventas.models import Venta
from app.shared.enums import EstadoVenta

# Línea de venta confirmada, con los nombres de las columnas como atributos.
LineaRow = Any


class FinanzasRepository:
    """
    Consultas de los reportes económicos. Solo lee: ventas, sus ítems y pagos,
    y el nombre de quien registró cada venta. Usa los datos guardados en la
    venta (precios, costo y nombres de la prenda), no el catálogo actual.

    El período es sobre confirmada_at: desde inclusivo y hasta exclusivo.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    @staticmethod
    def _rango(desde: datetime | None, hasta: datetime | None) -> list[ColumnElement[bool]]:
        filtros: list[ColumnElement[bool]] = []
        if desde is not None:
            filtros.append(Venta.confirmada_at >= desde)
        if hasta is not None:
            filtros.append(Venta.confirmada_at < hasta)
        return filtros

    @classmethod
    def _confirmadas(cls, desde: datetime | None, hasta: datetime | None) -> list[ColumnElement[bool]]:
        return [
            Venta.is_deleted.is_(False),
            Venta.estado == EstadoVenta.CONFIRMADA,
            *cls._rango(desde, hasta),
        ]

    async def primera_confirmacion(self) -> datetime | None:
        """Cuándo se confirmó la primera venta, aunque luego se anulara."""
        result = await self.db_session.execute(
            select(func.min(Venta.confirmada_at)).where(Venta.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def lineas(self, desde: datetime | None, hasta: datetime | None) -> list[LineaRow]:
        """
        Ítems de las ventas confirmadas del período, ordenados por confirmación
        y, dentro de cada venta, en el orden en que se registraron.
        """
        result = await self.db_session.execute(
            select(
                Venta.id.label("venta_id"),
                Venta.numero,
                Venta.confirmada_at,
                Venta.canal,
                Venta.subtotal.label("venta_subtotal"),
                Venta.descuento.label("venta_descuento"),
                Venta.total.label("venta_total"),
                Usuario.nombre.label("vendedor_nombre"),
                Usuario.apellidos.label("vendedor_apellidos"),
                VentaItem.sku_id,
                VentaItem.cantidad,
                VentaItem.precio_normal,
                VentaItem.precio_unitario,
                VentaItem.descuento_unitario,
                VentaItem.subtotal,
                VentaItem.costo_unitario,
                VentaItem.producto_nombre,
                VentaItem.color_nombre,
                VentaItem.talla_etiqueta,
                VentaItem.codigo_barras,
            )
            .join(VentaItem, VentaItem.venta_id == Venta.id)
            # created_by no tiene foreign key: el vendedor puede no existir.
            .outerjoin(Usuario, Usuario.id == Venta.created_by)
            .where(*self._confirmadas(desde, hasta), VentaItem.is_deleted.is_(False))
            .order_by(Venta.confirmada_at, Venta.numero, VentaItem.created_at, VentaItem.id)
        )
        return list(result.all())

    async def pagos(self, desde: datetime | None, hasta: datetime | None) -> list[tuple[Any, ...]]:
        """(venta_id, metodo, monto) de las ventas confirmadas del período, en el orden en que se registraron."""
        result = await self.db_session.execute(
            select(VentaPago.venta_id, VentaPago.metodo, VentaPago.monto)
            .join(Venta, Venta.id == VentaPago.venta_id)
            .where(*self._confirmadas(desde, hasta), VentaPago.is_deleted.is_(False))
            .order_by(VentaPago.venta_id, VentaPago.created_at, VentaPago.id)
        )
        return [tuple(row) for row in result.all()]

    async def anuladas(self, desde: datetime | None, hasta: datetime | None) -> tuple[int, Decimal]:
        """Cuántas ventas del período se confirmaron y luego se anularon, y su total."""
        result = await self.db_session.execute(
            select(func.count(), func.coalesce(func.sum(Venta.total), 0)).where(
                Venta.is_deleted.is_(False),
                Venta.estado == EstadoVenta.CANCELADA,
                Venta.confirmada_at.is_not(None),
                *self._rango(desde, hasta),
            )
        )
        cantidad, total = result.one()
        return int(cantidad), Decimal(total)
