from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.auth.schemas import CurrentUser
from app.domains.skus.schemas import SkuPrecio
from app.domains.skus.services import SkuService
from app.domains.venta_items.models import VentaItem
from app.domains.venta_items.repositories import SkuParaVenta, VentaItemRepository
from app.domains.venta_items.schemas import VentaItemCreate
from app.domains.ventas.models import Venta
from app.domains.ventas.repositories import VentaRepository, VentaScope
from app.domains.ventas.schemas import (
    VentaCreate,
    VentaEstadoUpdate,
    VentaItemsUpdate,
    VentaResponse,
)
from app.shared.enums import Action, CanalVenta, EstadoVenta, MetodoPago, Module
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.services.permissions import (
    VENTA_GLOBAL_SCOPE_ROLES,
    VENTA_OWN_SCOPE_ROLES,
    has_permission,
)


logger = get_logger(__name__)


class VentaService:
    """
    Reglas de negocio de las ventas y de sus ítems, que no tienen service propio.

    - Los precios y el snapshot de cada ítem se toman del SKU al crear la venta
      y se rehacen en cada PUT /items.
    - El stock se descuenta al confirmar (o al crear la venta ya confirmada) y
      se devuelve al anular una venta confirmada.
    - Una venta nunca se elimina: se cancela.
    """

    # ------------------------------------------------------------------ alcance

    @staticmethod
    def _scope_for(actor: CurrentUser) -> VentaScope:
        if actor.rol in VENTA_GLOBAL_SCOPE_ROLES:
            return VentaScope(all=True)
        if actor.rol in VENTA_OWN_SCOPE_ROLES:
            return VentaScope(created_by=actor.id)
        return VentaScope()  # alcance vacío: no devuelve filas

    # ------------------------------------------------------------------ errores

    @staticmethod
    def _validation_error(field_name: str, message: str) -> AppException:
        return AppException(message, 422, ErrorCode.VALIDATION_ERROR, {field_name: message})

    @staticmethod
    def _conflict(message: str, field_name: str | None = None) -> AppException:
        details = {field_name: message} if field_name is not None else None
        return AppException(message, 409, ErrorCode.CONFLICT, details)

    @staticmethod
    async def _commit(db_session: AsyncSession) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise AppException(
                "Los datos de la venta entran en conflicto con un registro existente.",
                409,
                ErrorCode.CONFLICT,
            ) from error
        except Exception:
            await db_session.rollback()
            raise

    # ------------------------------------------------------------------ lectura

    @classmethod
    async def get(
        cls,
        db_session: AsyncSession,
        venta_id: UUID,
        actor: CurrentUser,
        *,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> Venta:
        """Una venta fuera del alcance del actor responde 404, igual que una inexistente."""
        venta = await VentaRepository(db_session).get_by_id(
            venta_id,
            scope=cls._scope_for(actor),
            for_update=for_update,
            load_detail=load_detail,
        )
        if venta is None:
            raise AppException("Venta no encontrada.", 404, ErrorCode.RESOURCE_NOT_FOUND)
        return venta

    @staticmethod
    def _local_start(day: date, settings: Settings) -> datetime:
        """Inicio del día day en la zona horaria de la tienda."""
        tz = timezone(timedelta(hours=settings.TIMEZONE_OFFSET_HOURS))
        return datetime.combine(day, time.min, tzinfo=tz)

    @classmethod
    async def list(
        cls,
        db_session: AsyncSession,
        actor: CurrentUser,
        settings: Settings,
        *,
        page: int = 1,
        per_page: int = 20,
        estado: EstadoVenta | None = None,
        canal: CanalVenta | None = None,
        metodo_pago: MetodoPago | None = None,
        created_by: UUID | None = None,
        numero: int | None = None,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> PaginatedResponse[VentaResponse]:
        """desde y hasta son fechas de la tienda, ambas incluidas."""
        if page < 1:
            raise cls._validation_error("page", "La página debe ser mayor o igual a 1.")
        if per_page < 1 or per_page > 100:
            raise cls._validation_error("per_page", "La cantidad por página debe estar entre 1 y 100.")
        if desde is not None and hasta is not None and desde > hasta:
            raise cls._validation_error("desde", "La fecha desde no puede ser posterior a hasta.")

        ventas, total = await VentaRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            scope=cls._scope_for(actor),
            estado=estado,
            canal=canal,
            metodo_pago=metodo_pago,
            created_by=created_by,
            numero=numero,
            desde=cls._local_start(desde, settings) if desde is not None else None,
            hasta=cls._local_start(hasta + timedelta(days=1), settings) if hasta is not None else None,
        )
        return PaginatedResponse[VentaResponse](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=ventas,
        )

    # ------------------------------------------------------------------ ítems

    @classmethod
    async def _skus_para_venta(
        cls,
        db_session: AsyncSession,
        sku_ids: Sequence[UUID],
        *,
        for_update: bool = False,
    ) -> dict[UUID, SkuParaVenta]:
        skus = await VentaItemRepository(db_session).get_skus_para_venta(
            sku_ids,
            for_update=for_update,
        )
        missing = [str(sku_id) for sku_id in sku_ids if sku_id not in skus]
        if missing:
            raise cls._validation_error(
                "items",
                f"Estos SKUs no existen o fueron eliminados: {', '.join(missing)}.",
            )
        return skus

    @classmethod
    def _valores_item(
        cls,
        data: VentaItemCreate,
        sku_venta: SkuParaVenta,
        today: date,
    ) -> dict[str, Any]:
        """Precios, subtotal y snapshot de un ítem, calculados con el SKU actual."""
        sku = sku_venta.sku
        precio = SkuPrecio.model_validate(sku.precio)
        precio_unitario = precio.vigente(today)
        cls._validar_descuento_unitario(sku_venta.producto_nombre, data.descuento_unitario, precio_unitario)
        return {
            "sku_id": sku.id,
            "cantidad": data.cantidad,
            "precio_normal": precio.normal,
            "precio_unitario": precio_unitario,
            "descuento_unitario": data.descuento_unitario,
            "subtotal": (precio_unitario - data.descuento_unitario) * data.cantidad,
            "producto_nombre": sku_venta.producto_nombre,
            "color_nombre": sku_venta.color_nombre,
            "talla_etiqueta": sku_venta.talla_etiqueta,
            "codigo_barras": sku.codigo_barras,
        }

    @classmethod
    def _valores_ofrecidos(cls, data: VentaItemCreate, item: VentaItem) -> dict[str, Any]:
        """
        Valores de un ítem que ya estaba en la venta, sin recalcular precios:
        conserva el precio y el snapshot con que se ofreció y solo cambia su
        cantidad y su descuento.
        """
        cls._validar_descuento_unitario(item.producto_nombre, data.descuento_unitario, item.precio_unitario)
        return {
            "cantidad": data.cantidad,
            "descuento_unitario": data.descuento_unitario,
            "subtotal": (item.precio_unitario - data.descuento_unitario) * data.cantidad,
        }

    @classmethod
    def _validar_descuento_unitario(cls, producto_nombre: str, descuento: Decimal, precio_unitario: Decimal) -> None:
        if descuento > precio_unitario:
            raise cls._validation_error(
                "items",
                f"El descuento de {producto_nombre} ({descuento}) "
                f"supera su precio unitario ({precio_unitario}).",
            )

    @staticmethod
    def _nuevo_item(
        venta: Venta,
        actor: CurrentUser,
        now: datetime,
        posicion: int,
        valores: dict[str, Any],
    ) -> VentaItem:
        """
        Los ítems se ordenan por created_at. Los de una misma petición se crean en
        el mismo instante (y en Windows el reloj ni siquiera avanza entre ellos),
        así que cada uno suma un microsegundo para conservar el orden enviado.
        """
        created_at = now + timedelta(microseconds=posicion)
        return VentaItem(
            venta_id=venta.id,
            created_at=created_at,
            created_by=actor.id,
            updated_at=created_at,
            updated_by=actor.id,
            **valores,
        )

    @staticmethod
    def _actualizar_item(
        item: VentaItem,
        valores: dict[str, Any],
        actor: CurrentUser,
        now: datetime,
    ) -> None:
        """Aplica al ítem los valores recalculados que cambiaron; si nada cambió, no lo toca."""
        cambios = {key: value for key, value in valores.items() if getattr(item, key) != value}
        if cambios:
            for key, value in cambios.items():
                setattr(item, key, value)
            item.updated_at = now
            item.updated_by = actor.id

    @classmethod
    def _aplicar_totales(cls, venta: Venta, subtotales: Sequence[Decimal]) -> None:
        venta.subtotal = sum(subtotales, Decimal("0"))
        if venta.descuento > venta.subtotal:
            raise cls._validation_error(
                "descuento",
                f"El descuento ({venta.descuento}) no puede superar el subtotal de la venta ({venta.subtotal}).",
            )
        venta.total = venta.subtotal - venta.descuento

    # ------------------------------------------------------------------ stock

    @classmethod
    def _descontar_stock(
        cls,
        skus: dict[UUID, SkuParaVenta],
        cantidades: dict[UUID, int],
        actor_id: UUID,
        now: datetime,
    ) -> None:
        """Descuenta el stock de todos los SKUs, o de ninguno si alguno no alcanza."""
        faltantes = []
        for sku_id, cantidad in cantidades.items():
            sku_venta = skus[sku_id]
            disponible = int(sku_venta.sku.stock.get("cantidad", 0))
            if disponible < cantidad:
                faltantes.append(
                    f"{sku_venta.producto_nombre} {sku_venta.color_nombre} "
                    f"{sku_venta.talla_etiqueta} (disponible {disponible}, pedido {cantidad})"
                )
        if faltantes:
            raise cls._conflict(f"Stock insuficiente: {'; '.join(faltantes)}.", "items")

        for sku_id, cantidad in cantidades.items():
            cls._mover_stock(skus[sku_id], -cantidad, actor_id, now)

    @staticmethod
    def _mover_stock(sku_venta: SkuParaVenta, delta: int, actor_id: UUID, now: datetime) -> None:
        sku = sku_venta.sku
        sku.stock = {
            **sku.stock,
            "cantidad": int(sku.stock.get("cantidad", 0)) + delta,
            "actualizado": now.isoformat(),
        }
        sku.updated_at = now
        sku.updated_by = actor_id

    # ------------------------------------------------------------------ escritura

    @classmethod
    async def _reload(cls, db_session: AsyncSession, venta_id: UUID, actor: CurrentUser) -> Venta:
        # Responde lo mismo que GET /{id}: se recarga con su Detail.
        db_session.expire_all()
        return await cls.get(db_session, venta_id, actor, load_detail=True)

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: VentaCreate,
        actor: CurrentUser,
        settings: Settings,
    ) -> Venta:
        """
        Crea la venta con sus ítems. Si llega CONFIRMADA (venta de mostrador),
        descuenta el stock en la misma transacción.
        """
        confirmar = data.estado == EstadoVenta.CONFIRMADA
        sku_ids = [item.sku_id for item in data.items]
        skus = await cls._skus_para_venta(db_session, sku_ids, for_update=confirmar)
        today = SkuService.local_today(settings)
        now = utc_now()

        venta = Venta(
            **data.model_dump(exclude={"items"}),
            created_by=actor.id,
            updated_by=actor.id,
        )
        items = [
            cls._nuevo_item(venta, actor, now, posicion, cls._valores_item(item, skus[item.sku_id], today))
            for posicion, item in enumerate(data.items)
        ]
        cls._aplicar_totales(venta, [item.subtotal for item in items])
        if confirmar:
            cls._descontar_stock(skus, {item.sku_id: item.cantidad for item in items}, actor.id, now)
            venta.confirmada_at = now

        VentaRepository(db_session).add(venta)
        item_repository = VentaItemRepository(db_session)
        for item in items:
            item_repository.add(item)
        await cls._commit(db_session)

        logger.info(
            "Venta creada: venta_id=%s estado=%s items=%s actor_id=%s",
            venta.id,
            venta.estado,
            len(items),
            actor.id,
        )
        return await cls._reload(db_session, venta.id, actor)

    @classmethod
    async def replace_items(
        cls,
        db_session: AsyncSession,
        venta_id: UUID,
        data: VentaItemsUpdate,
        actor: CurrentUser,
        settings: Settings,
    ) -> Venta:
        """
        Reemplaza los ítems de una venta PENDIENTE, actualiza los datos enviados
        y recalcula los totales. Los ítems nuevos toman el precio y el snapshot
        de su SKU actual. Los que ya estaban conservan los suyos, como en una
        proforma, salvo con recalcular_precios, que los rehace todos con el
        catálogo del día. Todos los SKUs enviados deben seguir activos.
        """
        venta = await cls.get(db_session, venta_id, actor, for_update=True, load_detail=True)
        if venta.estado != EstadoVenta.PENDIENTE:
            raise cls._conflict("Solo se pueden modificar las ventas pendientes.", "estado")

        skus = await cls._skus_para_venta(db_session, [item.sku_id for item in data.items])
        today = SkuService.local_today(settings)
        now = utc_now()

        actuales = {item.sku_id: item for item in venta.items}
        nuevos: list[VentaItem] = []
        subtotales: list[Decimal] = []
        for item_data in data.items:
            existente = actuales.pop(item_data.sku_id, None)
            if existente is None:
                valores = cls._valores_item(item_data, skus[item_data.sku_id], today)
                nuevos.append(cls._nuevo_item(venta, actor, now, len(nuevos), valores))
            else:
                if data.recalcular_precios:
                    valores = cls._valores_item(item_data, skus[item_data.sku_id], today)
                else:
                    valores = cls._valores_ofrecidos(item_data, existente)
                cls._actualizar_item(existente, valores, actor, now)
            subtotales.append(valores["subtotal"])

        datos_venta = data.model_dump(exclude_unset=True, exclude={"items", "recalcular_precios"})
        for field_name, value in datos_venta.items():
            setattr(venta, field_name, value)
        cls._aplicar_totales(venta, subtotales)
        venta.updated_at = now
        venta.updated_by = actor.id

        item_repository = VentaItemRepository(db_session)
        await item_repository.soft_delete_by_ids(
            [item.id for item in actuales.values()],
            actor.id,
            now,
        )
        for item in nuevos:
            item_repository.add(item)
        await cls._commit(db_session)

        logger.info(
            "Ítems de venta reemplazados: venta_id=%s nuevos=%s eliminados=%s actor_id=%s",
            venta_id,
            len(nuevos),
            len(actuales),
            actor.id,
        )
        return await cls._reload(db_session, venta_id, actor)

    @classmethod
    async def change_estado(
        cls,
        db_session: AsyncSession,
        venta_id: UUID,
        data: VentaEstadoUpdate,
        actor: CurrentUser,
        settings: Settings,
    ) -> Venta:
        """
        PENDIENTE → CONFIRMADA cobra la venta y descuenta el stock. Por defecto
        la cobra como una proforma, tal como se ofreció; con recalcular_precios
        antes rehace el snapshot y los precios de cada ítem con su SKU actual,
        igual que PUT /items (conserva cantidades y descuentos), y recalcula
        los totales. PENDIENTE → CANCELADA no toca el stock; CONFIRMADA
        → CANCELADA lo devuelve y exige la acción DELETE de ventas (anular una
        venta cobrada). Cancelar no recalcula nada. CANCELADA es definitiva.
        """
        venta = await cls.get(db_session, venta_id, actor, for_update=True, load_detail=True)
        destino = data.estado
        if venta.estado == EstadoVenta.CANCELADA:
            raise cls._conflict("La venta ya está cancelada.", "estado")
        if venta.estado == destino:
            raise cls._conflict("La venta ya está confirmada.", "estado")

        now = utc_now()
        cantidades = {item.sku_id: item.cantidad for item in venta.items}
        item_repository = VentaItemRepository(db_session)

        if destino == EstadoVenta.CONFIRMADA:
            skus = await item_repository.get_skus_para_venta(list(cantidades), for_update=True)
            eliminados = [item for item in venta.items if item.sku_id not in skus]
            if eliminados:
                nombres = ", ".join(
                    f"{item.producto_nombre} {item.color_nombre} {item.talla_etiqueta}"
                    for item in eliminados
                )
                raise cls._conflict(
                    f"Estos productos fueron eliminados del catálogo: {nombres}. "
                    "Quítalos con PUT /ventas/{id}/items antes de confirmar.",
                    "items",
                )
            if data.recalcular_precios:
                # Se cobra con el catálogo de hoy: precios, rebajas vigentes y nombres.
                today = SkuService.local_today(settings)
                subtotales: list[Decimal] = []
                for item in venta.items:
                    datos = VentaItemCreate(
                        sku_id=item.sku_id,
                        cantidad=item.cantidad,
                        descuento_unitario=item.descuento_unitario,
                    )
                    valores = cls._valores_item(datos, skus[item.sku_id], today)
                    cls._actualizar_item(item, valores, actor, now)
                    subtotales.append(valores["subtotal"])
                cls._aplicar_totales(venta, subtotales)
            cls._descontar_stock(skus, cantidades, actor.id, now)
            venta.confirmada_at = now
        else:
            if venta.estado == EstadoVenta.CONFIRMADA:
                if not has_permission(actor.rol, Module.VENTA, Action.DELETE):
                    raise AppException(
                        "No tienes permisos para anular una venta confirmada.",
                        403,
                        ErrorCode.PERMISSION_DENIED,
                    )
                # El stock vuelve a los SKUs que siguen activos; los eliminados se omiten.
                skus = await item_repository.get_skus_para_venta(list(cantidades), for_update=True)
                for sku_id, sku_venta in skus.items():
                    cls._mover_stock(sku_venta, cantidades[sku_id], actor.id, now)
            venta.cancelada_at = now

        estado_anterior = venta.estado
        venta.estado = destino
        venta.updated_at = now
        venta.updated_by = actor.id
        await cls._commit(db_session)

        logger.info(
            "Estado de venta cambiado: venta_id=%s %s -> %s actor_id=%s",
            venta_id,
            estado_anterior,
            destino,
            actor.id,
        )
        return await cls._reload(db_session, venta_id, actor)
