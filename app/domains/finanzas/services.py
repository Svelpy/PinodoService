import asyncio
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from itertools import groupby
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.auth.schemas import CurrentUser
from app.domains.config.repositories import ConfigRepository
from app.domains.finanzas.repositories import FinanzasRepository, LineaRow
from app.domains.finanzas.schemas import (
    ReportePeriodo,
    ReporteRentabilidad,
    ReporteRentabilidadLinea,
    ReporteRentabilidadMes,
    ReporteRentabilidadResumen,
    ReporteVentas,
    ReporteVentasLinea,
    ReporteVentasMetodo,
    ReporteVentasResumen,
)
from app.domains.usuarios.repositories import UsuarioRepository
from app.shared.enums import MetodoPago
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.services import excel
from app.shared.services.excel import Columna


logger = get_logger(__name__)

CENTAVO = Decimal("0.01")
FRACCION = Decimal("0.0001")
CERO = Decimal("0")
MESES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)


def _centavos(value: Decimal) -> Decimal:
    return value.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _fraccion(numerador: Decimal, denominador: Decimal) -> Decimal:
    if not denominador:
        return CERO
    return (numerador / denominador).quantize(FRACCION, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class _LineaNeta:
    """Un ítem vendido con su parte del descuento general de la venta."""

    row: LineaRow
    descuento_venta: Decimal

    @property
    def total(self) -> Decimal:
        return Decimal(self.row.subtotal) - self.descuento_venta

    @property
    def costo(self) -> Decimal:
        return Decimal(self.row.costo_unitario or 0) * self.row.cantidad

    @property
    def venta_precio_normal(self) -> Decimal:
        return Decimal(self.row.precio_normal) * self.row.cantidad


@dataclass(frozen=True)
class _Contexto:
    """Lo que el Excel muestra en su encabezado."""

    tienda: str
    generado_por: str


class FinanzasService:
    """
    Reportes económicos calculados de las ventas confirmadas, sin tablas
    propias. Cada reporte se pide en JSON o en Excel con los mismos parámetros:
    el Excel es la misma respuesta presentada en dos hojas, así que nunca
    descuadra con el JSON.
    """

    # ------------------------------------------------------------------ período

    @staticmethod
    def _tz(settings: Settings) -> timezone:
        return timezone(timedelta(hours=settings.TIMEZONE_OFFSET_HOURS))

    @classmethod
    def _local_start(cls, day: date, settings: Settings) -> datetime:
        """Inicio del día day en la zona horaria de la tienda."""
        return datetime.combine(day, time.min, tzinfo=cls._tz(settings))

    @classmethod
    async def _periodo(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        desde: date | None,
        hasta: date | None,
    ) -> tuple[ReportePeriodo, datetime | None, datetime | None]:
        """
        El período que se muestra y el rango de la consulta. Sin desde, el
        reporte empieza en la primera venta confirmada; sin hasta, llega a hoy.
        """
        if desde is not None and hasta is not None and desde > hasta:
            message = "La fecha desde no puede ser posterior a hasta."
            raise AppException(message, 422, ErrorCode.VALIDATION_ERROR, {"desde": message})

        tz = cls._tz(settings)
        ahora = utc_now().astimezone(tz)
        hasta_periodo = hasta or ahora.date()
        desde_periodo = desde
        if desde_periodo is None:
            primera = await FinanzasRepository(db_session).primera_confirmacion()
            desde_periodo = primera.astimezone(tz).date() if primera is not None else hasta_periodo
            desde_periodo = min(desde_periodo, hasta_periodo)

        periodo = ReportePeriodo(
            desde=desde_periodo,
            hasta=hasta_periodo,
            sin_filtros=desde is None and hasta is None,
            generado_at=ahora,
        )
        desde_at = cls._local_start(desde, settings) if desde is not None else None
        hasta_at = cls._local_start(hasta + timedelta(days=1), settings) if hasta is not None else None
        return periodo, desde_at, hasta_at

    # ------------------------------------------------------------------ líneas

    @staticmethod
    def _lineas_netas(rows: list[LineaRow]) -> Iterator[_LineaNeta]:
        """
        Reparte el descuento general de cada venta entre sus ítems según su
        subtotal; el último absorbe el redondeo, así que las líneas de una
        venta suman exactamente su total.
        """
        for _, items in groupby(rows, key=lambda row: row.venta_id):
            items = list(items)
            subtotal = Decimal(items[0].venta_subtotal)
            restante = Decimal(items[0].venta_descuento)
            for indice, row in enumerate(items):
                if indice == len(items) - 1:
                    parte = restante
                elif subtotal:
                    parte = _centavos(Decimal(items[0].venta_descuento) * Decimal(row.subtotal) / subtotal)
                else:
                    parte = CERO
                restante -= parte
                yield _LineaNeta(row=row, descuento_venta=parte)

    @staticmethod
    def _vendedor(row: LineaRow) -> str:
        nombre = " ".join(part for part in (row.vendedor_nombre, row.vendedor_apellidos) if part)
        return nombre or "Sin usuario"

    # ------------------------------------------------------------------ ventas

    @classmethod
    async def ventas(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        *,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> ReporteVentas:
        periodo, desde_at, hasta_at = await cls._periodo(db_session, settings, desde, hasta)
        repository = FinanzasRepository(db_session)
        rows = await repository.lineas(desde_at, hasta_at)
        pagos = await repository.pagos(desde_at, hasta_at)
        anuladas, monto_anulado = await repository.anuladas(desde_at, hasta_at)

        metodos_por_venta: dict[UUID, list[MetodoPago]] = defaultdict(list)
        cobrado: dict[MetodoPago, list] = {}
        for venta_id, metodo, monto in pagos:
            metodo = MetodoPago(metodo)
            if metodo not in metodos_por_venta[venta_id]:
                metodos_por_venta[venta_id].append(metodo)
            acumulado = cobrado.setdefault(metodo, [0, CERO])
            acumulado[0] += 1
            acumulado[1] += Decimal(monto)

        tz = cls._tz(settings)
        lineas = list(cls._lineas_netas(rows))
        detalle = []
        for linea in lineas:
            row = linea.row
            confirmada = row.confirmada_at.astimezone(tz)
            detalle.append(
                ReporteVentasLinea(
                    fecha=confirmada.date(),
                    hora=confirmada.time().replace(microsecond=0, tzinfo=None),
                    venta_id=row.venta_id,
                    numero=row.numero,
                    canal=row.canal,
                    vendedor=cls._vendedor(row),
                    metodos_pago=metodos_por_venta.get(row.venta_id, []),
                    sku_id=row.sku_id,
                    producto=row.producto_nombre,
                    color=row.color_nombre,
                    talla=row.talla_etiqueta,
                    codigo_barras=row.codigo_barras,
                    cantidad=row.cantidad,
                    precio_normal=Decimal(row.precio_normal),
                    precio_cobrado=Decimal(row.precio_unitario),
                    descuento_prenda=Decimal(row.descuento_unitario) * row.cantidad,
                    descuento_venta=linea.descuento_venta,
                    total=linea.total,
                )
            )

        ventas = {row.venta_id: row for row in rows}
        cantidad_ventas = len(ventas)
        unidades = sum(linea.cantidad for linea in detalle)
        total_vendido = sum((Decimal(row.venta_total) for row in ventas.values()), CERO)
        resumen = ReporteVentasResumen(
            ventas=cantidad_ventas,
            unidades=unidades,
            venta_precio_normal=sum((linea.precio_normal * linea.cantidad for linea in detalle), CERO),
            rebajas=sum(((linea.precio_normal - linea.precio_cobrado) * linea.cantidad for linea in detalle), CERO),
            descuentos_prenda=sum((linea.descuento_prenda for linea in detalle), CERO),
            descuentos_venta=sum((Decimal(row.venta_descuento) for row in ventas.values()), CERO),
            total_vendido=total_vendido,
            ticket_promedio=_centavos(total_vendido / cantidad_ventas) if cantidad_ventas else CERO,
            unidades_por_venta=_centavos(Decimal(unidades) / cantidad_ventas) if cantidad_ventas else CERO,
            ventas_anuladas=anuladas,
            monto_anulado=monto_anulado,
        )
        total_cobrado = sum((monto for _, monto in cobrado.values()), CERO)
        por_metodo = [
            ReporteVentasMetodo(metodo=metodo, pagos=cantidad, monto=monto, porcentaje=_fraccion(monto, total_cobrado))
            for metodo, (cantidad, monto) in sorted(cobrado.items(), key=lambda item: -item[1][1])
        ]
        return ReporteVentas(periodo=periodo, resumen=resumen, cobrado_por_metodo=por_metodo, detalle=detalle)

    # ------------------------------------------------------------------ rentabilidad

    @classmethod
    async def rentabilidad(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        *,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> ReporteRentabilidad:
        periodo, desde_at, hasta_at = await cls._periodo(db_session, settings, desde, hasta)
        rows = await FinanzasRepository(db_session).lineas(desde_at, hasta_at)
        lineas = list(cls._lineas_netas(rows))
        tz = cls._tz(settings)

        por_sku: dict[UUID, list[_LineaNeta]] = defaultdict(list)
        por_mes: dict[tuple[int, int], list[_LineaNeta]] = defaultdict(list)
        for linea in lineas:
            por_sku[linea.row.sku_id].append(linea)
            confirmada = linea.row.confirmada_at.astimezone(tz)
            por_mes[(confirmada.year, confirmada.month)].append(linea)

        detalle = []
        for sku_id, grupo in por_sku.items():
            # Las líneas van por fecha: la última trae los nombres más recientes.
            ultima = grupo[-1].row
            normal = sum((linea.venta_precio_normal for linea in grupo), CERO)
            ingreso = sum((linea.total for linea in grupo), CERO)
            costo = sum((linea.costo for linea in grupo), CERO)
            detalle.append(
                ReporteRentabilidadLinea(
                    sku_id=sku_id,
                    producto=ultima.producto_nombre,
                    color=ultima.color_nombre,
                    talla=ultima.talla_etiqueta,
                    codigo_barras=ultima.codigo_barras,
                    cantidad=sum(linea.row.cantidad for linea in grupo),
                    venta_precio_normal=normal,
                    descuentos=normal - ingreso,
                    ingreso_neto=ingreso,
                    costo=costo,
                    margen_bruto=ingreso - costo,
                    margen_porcentaje=_fraccion(ingreso - costo, ingreso),
                )
            )
        detalle.sort(key=lambda linea: (-linea.margen_bruto, linea.producto, linea.color, linea.talla))

        meses = []
        for (anio, mes), grupo in sorted(por_mes.items()):
            ingreso = sum((linea.total for linea in grupo), CERO)
            costo = sum((linea.costo for linea in grupo), CERO)
            meses.append(
                ReporteRentabilidadMes(
                    anio=anio,
                    mes=mes,
                    unidades=sum(linea.row.cantidad for linea in grupo),
                    ingreso_neto=ingreso,
                    costo=costo,
                    margen_bruto=ingreso - costo,
                    margen_porcentaje=_fraccion(ingreso - costo, ingreso),
                )
            )

        normal = sum((linea.venta_precio_normal for linea in lineas), CERO)
        ingreso = sum((linea.total for linea in lineas), CERO)
        costo = sum((linea.costo for linea in lineas), CERO)
        resumen = ReporteRentabilidadResumen(
            unidades=sum(linea.row.cantidad for linea in lineas),
            venta_precio_normal=normal,
            descuentos=normal - ingreso,
            ingreso_neto=ingreso,
            costo=costo,
            margen_bruto=ingreso - costo,
            margen_porcentaje=_fraccion(ingreso - costo, ingreso),
            unidades_sin_costo=sum(linea.row.cantidad for linea in lineas if not linea.row.costo_unitario),
        )
        return ReporteRentabilidad(periodo=periodo, resumen=resumen, por_mes=meses, detalle=detalle)

    # ------------------------------------------------------------------ excel

    @staticmethod
    async def _contexto(db_session: AsyncSession, actor: CurrentUser) -> _Contexto:
        config = await ConfigRepository(db_session).get()
        usuario = await UsuarioRepository(db_session).get_by_id(actor.id, include_deleted=True)
        nombre = " ".join(part for part in (usuario.nombre, usuario.apellidos) if part) if usuario else "—"
        return _Contexto(
            tienda=config.nombre_tienda if config is not None else "Tienda",
            generado_por=f"{nombre} ({actor.rol.value})",
        )

    @staticmethod
    def _lineas_encabezado(periodo: ReportePeriodo, contexto: _Contexto) -> list[str]:
        rango = f"Período: {periodo.desde:%d/%m/%Y} – {periodo.hasta:%d/%m/%Y}"
        if periodo.sin_filtros:
            rango += " (sin filtros: desde la primera venta hasta hoy)"
        return [rango, f"Generado: {periodo.generado_at:%d/%m/%Y %H:%M} por {contexto.generado_por}"]

    @classmethod
    def _libro_ventas(cls, reporte: ReporteVentas, contexto: _Contexto) -> bytes:
        libro = excel.nuevo_libro()
        lineas = cls._lineas_encabezado(reporte.periodo, contexto)
        r = reporte.resumen

        hoja = libro.active
        hoja.title = "Resumen"
        fila = excel.encabezado(
            hoja,
            f"{contexto.tienda} — Reporte de ventas",
            lineas,
            [
                "Solo ventas confirmadas, por fecha de confirmación (hora de la tienda).",
                "El desglose por día, producto, canal, método o vendedor está en la hoja Detalle, filtrando.",
            ],
        )
        indicadores = [
            ("Ventas confirmadas", r.ventas, excel.ENTERO),
            ("Unidades vendidas", r.unidades, excel.ENTERO),
            ("Venta a precio normal", r.venta_precio_normal, excel.DINERO),
            ("(−) Rebajas", r.rebajas, excel.DINERO),
            ("(−) Descuentos por prenda", r.descuentos_prenda, excel.DINERO),
            ("(−) Descuentos de venta", r.descuentos_venta, excel.DINERO),
            ("Total vendido", r.total_vendido, excel.DINERO),
            ("Ticket promedio", r.ticket_promedio, excel.DINERO),
            ("Unidades por venta", r.unidades_por_venta, excel.DECIMAL),
            ("Ventas anuladas", r.ventas_anuladas, excel.ENTERO),
            ("Monto anulado", r.monto_anulado, excel.DINERO),
        ]
        fila = excel.tabla_simple(
            hoja,
            fila,
            ["Indicador", "Valor"],
            [[nombre, valor] for nombre, valor, _ in indicadores],
            [[None, formato] for *_, formato in indicadores],
            negrita={6},
            anchos=[32, 16, 16, 14],
        )

        fila = excel.titulo_seccion(hoja, fila, "Cobrado por método de pago")
        filas = [[m.metodo.value, m.pagos, m.monto, m.porcentaje] for m in reporte.cobrado_por_metodo]
        filas.append(
            [
                "Total",
                sum(m.pagos for m in reporte.cobrado_por_metodo),
                sum((m.monto for m in reporte.cobrado_por_metodo), CERO),
                Decimal(1) if reporte.cobrado_por_metodo else CERO,
            ]
        )
        fila = excel.tabla_simple(
            hoja,
            fila,
            ["Método", "Pagos", "Monto cobrado", "% del total"],
            filas,
            [[None, excel.ENTERO, excel.DINERO, excel.PORCENTAJE]] * len(filas),
            negrita={len(filas) - 1},
        )
        excel.nota(
            hoja,
            fila - 1,
            "En una venta pagada con varios métodos, esta tabla reparte el monto exacto de cada uno; "
            "en el Detalle la venta aparece completa en la columna «Métodos de pago».",
        )

        hoja = libro.create_sheet("Detalle")
        fila = excel.encabezado(
            hoja,
            f"{contexto.tienda} — Detalle de ventas",
            lineas,
            [
                "Una fila por prenda vendida. «Desc. venta» es el descuento general de la venta repartido entre sus prendas.",
                "Filtra cualquier columna (fecha, producto, código, canal, método, vendedor): "
                "la fila «Total filtrado» suma solo lo visible.",
            ],
        )
        excel.tabla_filtrable(
            hoja,
            fila,
            [
                Columna("Fecha", excel.FECHA, 12),
                Columna("Hora", excel.HORA, 7),
                Columna("N° venta", excel.ENTERO, 9),
                Columna("Canal", None, 13),
                Columna("Vendedor", None, 18),
                Columna("Métodos de pago", None, 17),
                Columna("Producto", None, 24),
                Columna("Color", None, 13),
                Columna("Talla", None, 7),
                Columna("Código de barras", None, 16),
                Columna("Cantidad", excel.ENTERO, 10, "suma"),
                Columna("Precio normal", excel.DINERO, 12),
                Columna("Precio cobrado", excel.DINERO, 12),
                Columna("Desc. prenda", excel.DINERO, 11, "suma"),
                Columna("Desc. venta", excel.DINERO, 11, "suma"),
                Columna("Total", excel.DINERO, 13, "suma"),
            ],
            [
                [
                    linea.fecha,
                    linea.hora,
                    linea.numero,
                    linea.canal.value,
                    linea.vendedor,
                    " + ".join(metodo.value for metodo in linea.metodos_pago),
                    linea.producto,
                    linea.color,
                    linea.talla,
                    linea.codigo_barras,
                    linea.cantidad,
                    linea.precio_normal,
                    linea.precio_cobrado,
                    linea.descuento_prenda,
                    linea.descuento_venta,
                    linea.total,
                ]
                for linea in reporte.detalle
            ],
        )
        return excel.a_bytes(libro)

    @classmethod
    def _libro_rentabilidad(cls, reporte: ReporteRentabilidad, contexto: _Contexto) -> bytes:
        libro = excel.nuevo_libro()
        lineas = cls._lineas_encabezado(reporte.periodo, contexto)
        r = reporte.resumen

        hoja = libro.active
        hoja.title = "Resumen"
        fila = excel.encabezado(
            hoja,
            f"{contexto.tienda} — Reporte de rentabilidad",
            lineas,
            [
                "Solo ventas confirmadas. El costo es el costo promedio de cada prenda al confirmar la venta.",
                "No incluye gastos (alquiler, sueldos, publicidad): es el margen bruto, no la utilidad neta.",
                "El margen por producto o SKU está en la hoja Detalle, filtrando.",
            ],
        )
        indicadores = [
            ("Unidades vendidas", r.unidades, excel.ENTERO),
            ("Venta a precio normal", r.venta_precio_normal, excel.DINERO),
            ("(−) Descuentos", r.descuentos, excel.DINERO),
            ("Ingreso neto", r.ingreso_neto, excel.DINERO),
            ("(−) Costo de lo vendido", r.costo, excel.DINERO),
            ("Margen bruto", r.margen_bruto, excel.DINERO),
            ("Margen bruto %", r.margen_porcentaje, excel.PORCENTAJE),
            ("Unidades vendidas con costo 0", r.unidades_sin_costo, excel.ENTERO),
        ]
        fila = excel.tabla_simple(
            hoja,
            fila,
            ["Indicador", "Valor"],
            [[nombre, valor] for nombre, valor, _ in indicadores],
            [[None, formato] for *_, formato in indicadores],
            negrita={5},
            anchos=[32, 15, 15, 15, 15, 12],
        )

        fila = excel.titulo_seccion(hoja, fila, "Margen por mes")
        filas = [
            [f"{MESES[m.mes - 1]} {m.anio}", m.unidades, m.ingreso_neto, m.costo, m.margen_bruto, m.margen_porcentaje]
            for m in reporte.por_mes
        ]
        filas.append(["Total", r.unidades, r.ingreso_neto, r.costo, r.margen_bruto, r.margen_porcentaje])
        excel.tabla_simple(
            hoja,
            fila,
            ["Mes", "Unidades", "Ingreso neto", "Costo", "Margen bruto", "Margen %"],
            filas,
            [[None, excel.ENTERO, excel.DINERO, excel.DINERO, excel.DINERO, excel.PORCENTAJE]] * len(filas),
            negrita={len(filas) - 1},
        )

        hoja = libro.create_sheet("Detalle")
        fila = excel.encabezado(
            hoja,
            f"{contexto.tienda} — Detalle de rentabilidad",
            lineas,
            [
                "Una fila por SKU con el total del período, de mayor a menor margen bruto.",
                "«Descuentos» = rebajas + descuentos por prenda + su parte del descuento general de cada venta.",
                "Filtra por Producto o SKU (Código de barras, o Color + Talla): "
                "la fila «Total filtrado» suma solo lo visible.",
            ],
        )
        excel.tabla_filtrable(
            hoja,
            fila,
            [
                Columna("Producto", None, 24),
                Columna("Color", None, 13),
                Columna("Talla", None, 7),
                Columna("Código de barras", None, 16),
                Columna("Cantidad", excel.ENTERO, 10, "suma"),
                Columna("Venta a precio normal", excel.DINERO, 14, "suma"),
                Columna("Descuentos", excel.DINERO, 12, "suma"),
                Columna("Ingreso neto", excel.DINERO, 13, "suma"),
                Columna("Costo", excel.DINERO, 12, "suma"),
                Columna("Margen bruto", excel.DINERO, 13, "suma"),
                Columna("Margen %", excel.PORCENTAJE, 10, ("ratio", "Margen bruto", "Ingreso neto")),
            ],
            [
                [
                    linea.producto,
                    linea.color,
                    linea.talla,
                    linea.codigo_barras,
                    linea.cantidad,
                    linea.venta_precio_normal,
                    linea.descuentos,
                    linea.ingreso_neto,
                    linea.costo,
                    linea.margen_bruto,
                    linea.margen_porcentaje,
                ]
                for linea in reporte.detalle
            ],
        )
        return excel.a_bytes(libro)

    @classmethod
    async def ventas_excel(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        actor: CurrentUser,
        *,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> tuple[str, bytes]:
        """El reporte de ventas en Excel: (nombre del archivo, contenido)."""
        reporte = await cls.ventas(db_session, settings, desde=desde, hasta=hasta)
        contexto = await cls._contexto(db_session, actor)
        contenido = await asyncio.to_thread(cls._libro_ventas, reporte, contexto)
        logger.info("Reporte de ventas en Excel: lineas=%s actor_id=%s", len(reporte.detalle), actor.id)
        return f"ventas_{reporte.periodo.desde}_{reporte.periodo.hasta}.xlsx", contenido

    @classmethod
    async def rentabilidad_excel(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        actor: CurrentUser,
        *,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> tuple[str, bytes]:
        """El reporte de rentabilidad en Excel: (nombre del archivo, contenido)."""
        reporte = await cls.rentabilidad(db_session, settings, desde=desde, hasta=hasta)
        contexto = await cls._contexto(db_session, actor)
        contenido = await asyncio.to_thread(cls._libro_rentabilidad, reporte, contexto)
        logger.info("Reporte de rentabilidad en Excel: skus=%s actor_id=%s", len(reporte.detalle), actor.id)
        return f"rentabilidad_{reporte.periodo.desde}_{reporte.periodo.hasta}.xlsx", contenido
