from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.config import get_settings
from app.domains.auth.schemas import CurrentUser
from app.domains.movimientos_inventario.models import MovimientoInventario
from app.domains.movimientos_inventario.repositories import MovimientoInventarioRepository
from app.domains.skus.models import Sku
from app.domains.venta_items.models import VentaItem
from app.domains.venta_items.repositories import SkuParaVenta, VentaItemRepository
from app.domains.venta_pagos.models import VentaPago
from app.domains.venta_pagos.repositories import VentaPagoRepository
from app.domains.ventas.models import Venta
from app.domains.ventas.repositories import VentaRepository, VentaScope
from app.domains.ventas.schemas import VentaCreate, VentaEstadoUpdate, VentaItemsUpdate
from app.domains.ventas.services import VentaService
from app.shared.enums import EstadoVenta, MetodoPago, Role, TipoMovimiento
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _actor(rol: Role = Role.CAJERO) -> CurrentUser:
    return CurrentUser(id=uuid4(), rol=rol)


def _sku_venta(
    *,
    normal: float = 29.95,
    rebajado: float | None = None,
    cantidad: int = 10,
    nombre: str = "Camisa Oxford",
    costo: str = "12.50",
) -> SkuParaVenta:
    sku = Sku(
        producto_color_id=uuid4(),
        talla_id=uuid4(),
        codigo_barras="8412345678905",
        precio={
            "normal": normal,
            "rebajado": rebajado,
            "rebaja_hasta": "2099-12-31" if rebajado is not None else None,
        },
        stock={"cantidad": cantidad, "minimo": 2, "actualizado": None},
        costo=Decimal(costo),
    )
    return SkuParaVenta(sku, nombre, "Azul marino", "M")


def _item(sku_venta: SkuParaVenta, venta: Venta, cantidad: int = 1) -> VentaItem:
    precio = Decimal(str(sku_venta.sku.precio["normal"]))
    return VentaItem(
        venta_id=venta.id,
        sku_id=sku_venta.sku.id,
        cantidad=cantidad,
        precio_normal=precio,
        precio_unitario=precio,
        descuento_unitario=Decimal("0"),
        subtotal=precio * cantidad,
        producto_nombre=sku_venta.producto_nombre,
        color_nombre=sku_venta.color_nombre,
        talla_etiqueta=sku_venta.talla_etiqueta,
        codigo_barras=sku_venta.sku.codigo_barras,
    )


def _venta(estado: EstadoVenta, *skus: tuple[SkuParaVenta, int]) -> Venta:
    venta = Venta(estado=estado)
    venta.items = [_item(sku_venta, venta, cantidad) for sku_venta, cantidad in skus]
    venta.subtotal = sum((item.subtotal for item in venta.items), Decimal("0"))
    venta.total = venta.subtotal
    # Sin fiado: una venta confirmada está pagada completa.
    if estado == EstadoVenta.CONFIRMADA:
        venta.total_pagado = venta.total
    return venta


def _pago(monto: str, metodo: str = "EFECTIVO") -> dict[str, str]:
    return {"metodo": metodo, "monto": monto}


def _confirmacion(*pagos: dict[str, str], recalcular: bool = False) -> VentaEstadoUpdate:
    return VentaEstadoUpdate.model_validate(
        {"estado": "CONFIRMADA", "recalcular_precios": recalcular, "pagos": list(pagos)}
    )


@contextmanager
def _repos(
    *,
    skus: dict[UUID, SkuParaVenta],
    venta: Venta | None = None,
) -> Iterator[dict[str, MagicMock]]:
    with (
        patch.object(
            VentaItemRepository,
            "get_skus_para_venta",
            new=AsyncMock(side_effect=lambda ids, **_: {i: skus[i] for i in ids if i in skus}),
        ) as get_skus,
        patch.object(VentaItemRepository, "add") as add_item,
        patch.object(VentaItemRepository, "soft_delete_by_ids", new=AsyncMock(return_value=0)) as soft_delete,
        patch.object(VentaRepository, "add") as add_venta,
        patch.object(VentaPagoRepository, "add") as add_pago,
        patch.object(MovimientoInventarioRepository, "add") as add_movimiento,
        patch.object(VentaRepository, "get_by_id", new=AsyncMock(return_value=venta)) as get_by_id,
        patch.object(VentaService, "_reload", new=AsyncMock(side_effect=lambda s, venta_id, a: venta_id)),
    ):
        yield {
            "get_skus": get_skus,
            "add_item": add_item,
            "soft_delete": soft_delete,
            "add_venta": add_venta,
            "add_pago": add_pago,
            "add_movimiento": add_movimiento,
            "get_by_id": get_by_id,
        }


def _added_items(repos: dict[str, MagicMock]) -> list[VentaItem]:
    return [call.args[0] for call in repos["add_item"].call_args_list]


def _added_pagos(repos: dict[str, MagicMock]) -> list[VentaPago]:
    return [call.args[0] for call in repos["add_pago"].call_args_list]


def _added_movimientos(repos: dict[str, MagicMock]) -> list[MovimientoInventario]:
    return [call.args[0] for call in repos["add_movimiento"].call_args_list]


# ---------------------------------------------------------------- alcance


@pytest.mark.parametrize("rol", [Role.SUPERADMIN, Role.OWNER, Role.ADMIN])
def test_roles_superiores_ven_todas_las_ventas(rol: Role) -> None:
    assert VentaService._scope_for(_actor(rol)) == VentaScope(all=True)


def test_cajero_solo_ve_sus_ventas() -> None:
    actor = _actor(Role.CAJERO)

    assert VentaService._scope_for(actor) == VentaScope(created_by=actor.id)


@pytest.mark.asyncio
async def test_get_fuera_de_alcance_responde_404() -> None:
    actor = _actor(Role.CAJERO)

    with _repos(skus={}, venta=None) as repos, pytest.raises(AppException) as error:
        await VentaService.get(_session(), uuid4(), actor)

    assert error.value.status_code == 404
    assert repos["get_by_id"].call_args.kwargs["scope"] == VentaScope(created_by=actor.id)


# ---------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_pendiente_copia_snapshot_y_no_toca_stock() -> None:
    camisa = _sku_venta(normal=29.95, rebajado=19.95, cantidad=5)
    actor = _actor()
    data = VentaCreate.model_validate(
        {
            "descuento": "4.90",
            "items": [{"sku_id": str(camisa.sku.id), "cantidad": 2, "descuento_unitario": "2.50"}],
        }
    )

    with _repos(skus={camisa.sku.id: camisa}) as repos:
        await VentaService.create(_session(), data, actor, get_settings())

    venta = repos["add_venta"].call_args.args[0]
    [item] = _added_items(repos)
    assert item.venta_id == venta.id
    assert item.precio_normal == Decimal("29.95")
    assert item.precio_unitario == Decimal("19.95")  # rebaja vigente
    assert item.subtotal == Decimal("34.90")  # (19.95 - 2.50) * 2
    assert (item.producto_nombre, item.color_nombre, item.talla_etiqueta) == ("Camisa Oxford", "Azul marino", "M")
    assert item.codigo_barras == "8412345678905"
    assert venta.subtotal == Decimal("34.90")
    assert venta.total == Decimal("30.00")
    assert venta.estado == EstadoVenta.PENDIENTE
    assert venta.created_by == actor.id
    assert venta.confirmada_at is None
    assert camisa.sku.stock["cantidad"] == 5
    assert repos["get_skus"].call_args.kwargs["for_update"] is False


@pytest.mark.asyncio
async def test_create_conserva_el_orden_de_los_items() -> None:
    skus = [_sku_venta(nombre=f"Producto {n}") for n in range(5)]
    data = VentaCreate.model_validate(
        {"items": [{"sku_id": str(s.sku.id), "cantidad": 1} for s in skus]}
    )

    with _repos(skus={s.sku.id: s for s in skus}) as repos:
        await VentaService.create(_session(), data, _actor(), get_settings())

    items = _added_items(repos)
    assert [item.sku_id for item in items] == [s.sku.id for s in skus]
    # created_at estrictamente creciente: el orden de lectura es el enviado.
    assert all(a.created_at < b.created_at for a, b in zip(items, items[1:]))


@pytest.mark.asyncio
async def test_create_confirmada_descuenta_stock() -> None:
    camisa = _sku_venta(cantidad=5)
    data = VentaCreate.model_validate(
        {
            "estado": "CONFIRMADA",
            "canal": "TIENDA",
            "items": [{"sku_id": str(camisa.sku.id), "cantidad": 2}],
            "pagos": [_pago("59.90")],
        }
    )

    with _repos(skus={camisa.sku.id: camisa}) as repos:
        await VentaService.create(_session(), data, _actor(), get_settings())

    venta = repos["add_venta"].call_args.args[0]
    assert venta.confirmada_at is not None
    assert venta.total_pagado == venta.total == Decimal("59.90")
    assert camisa.sku.stock["cantidad"] == 3
    assert camisa.sku.stock["actualizado"] is not None
    assert repos["get_skus"].call_args.kwargs["for_update"] is True
    # La salida queda en el kardex y el ítem copia el costo del SKU.
    [movimiento] = _added_movimientos(repos)
    assert (movimiento.tipo, movimiento.cantidad, movimiento.saldo, movimiento.venta_id) == (
        TipoMovimiento.VENTA,
        -2,
        3,
        venta.id,
    )
    assert _added_items(repos)[0].costo_unitario == Decimal("12.50")


@pytest.mark.asyncio
async def test_create_confirmada_sin_stock_suficiente_responde_409_sin_tocar_nada() -> None:
    camisa = _sku_venta(cantidad=5)
    pantalon = _sku_venta(cantidad=1, nombre="Pantalón chino")
    session = _session()
    data = VentaCreate.model_validate(
        {
            "estado": "CONFIRMADA",
            "items": [
                {"sku_id": str(camisa.sku.id), "cantidad": 2},
                {"sku_id": str(pantalon.sku.id), "cantidad": 3},
            ],
            "pagos": [_pago("149.75")],
        }
    )

    with (
        _repos(skus={camisa.sku.id: camisa, pantalon.sku.id: pantalon}),
        pytest.raises(AppException) as error,
    ):
        await VentaService.create(session, data, _actor(), get_settings())

    assert error.value.status_code == 409
    assert "Pantalón chino" in error.value.message
    assert camisa.sku.stock["cantidad"] == 5
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_con_sku_inexistente_responde_422() -> None:
    data = VentaCreate.model_validate({"items": [{"sku_id": str(uuid4()), "cantidad": 1}]})

    with _repos(skus={}), pytest.raises(AppException) as error:
        await VentaService.create(_session(), data, _actor(), get_settings())

    assert error.value.status_code == 422
    assert "items" in error.value.details


@pytest.mark.asyncio
async def test_create_descuento_mayor_que_subtotal_responde_422() -> None:
    camisa = _sku_venta(normal=10)
    data = VentaCreate.model_validate(
        {"descuento": 11, "items": [{"sku_id": str(camisa.sku.id), "cantidad": 1}]}
    )

    with _repos(skus={camisa.sku.id: camisa}), pytest.raises(AppException) as error:
        await VentaService.create(_session(), data, _actor(), get_settings())

    assert error.value.status_code == 422
    assert "descuento" in error.value.details


@pytest.mark.asyncio
async def test_create_descuento_unitario_mayor_que_precio_responde_422() -> None:
    camisa = _sku_venta(normal=10)
    data = VentaCreate.model_validate(
        {"items": [{"sku_id": str(camisa.sku.id), "cantidad": 1, "descuento_unitario": 10.01}]}
    )

    with _repos(skus={camisa.sku.id: camisa}), pytest.raises(AppException) as error:
        await VentaService.create(_session(), data, _actor(), get_settings())

    assert error.value.status_code == 422


# ---------------------------------------------------------------- PUT items


@pytest.mark.asyncio
async def test_replace_items_con_recalcular_actualiza_elimina_crea_y_rehace_snapshot() -> None:
    camisa = _sku_venta(normal=29.95)
    pantalon = _sku_venta(normal=49.90, nombre="Pantalón chino")
    falda = _sku_venta(normal=39.90, nombre="Falda")
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1), (pantalon, 1))
    item_camisa, item_pantalon = venta.items
    # El precio de la camisa cambió desde que se agregó: se rehace el snapshot.
    camisa.sku.precio = {"normal": 25.00, "rebajado": None, "rebaja_hasta": None}
    actor = _actor()
    data = VentaItemsUpdate.model_validate(
        {
            "nota": "Cambió el pantalón por una falda.",
            "items": [
                {"sku_id": str(camisa.sku.id), "cantidad": 2},
                {"sku_id": str(falda.sku.id), "cantidad": 1},
            ],
            "recalcular_precios": True,
        }
    )

    with _repos(
        skus={s.sku.id: s for s in (camisa, pantalon, falda)},
        venta=venta,
    ) as repos:
        await VentaService.replace_items(_session(), venta.id, data, actor, get_settings())

    assert item_camisa.cantidad == 2
    assert item_camisa.precio_unitario == Decimal("25.0")
    assert item_camisa.subtotal == Decimal("50.0")
    assert item_camisa.updated_by == actor.id
    repos["soft_delete"].assert_awaited_once()
    assert repos["soft_delete"].call_args.args[0] == [item_pantalon.id]
    [nuevo] = _added_items(repos)
    assert nuevo.sku_id == falda.sku.id
    assert venta.subtotal == Decimal("89.90")
    assert venta.total == Decimal("89.90")
    assert venta.nota == "Cambió el pantalón por una falda."
    assert venta.updated_by == actor.id


@pytest.mark.asyncio
async def test_replace_items_por_defecto_conserva_el_precio_ofrecido() -> None:
    camisa = _sku_venta(normal=80)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 2))  # se ofreció a 80
    [item_camisa] = venta.items
    # Después la camisa sube a 100 y cambia de nombre; se añaden unas medias.
    camisa.sku.precio = {"normal": 100, "rebajado": None, "rebaja_hasta": None}
    camisa = SkuParaVenta(camisa.sku, "Camisa Oxford slim", "Azul marino", "M")
    medias = _sku_venta(normal=20, nombre="Medias")
    actor = _actor()
    data = VentaItemsUpdate.model_validate(
        {
            "items": [
                {"sku_id": str(camisa.sku.id), "cantidad": 1, "descuento_unitario": 5},
                {"sku_id": str(medias.sku.id), "cantidad": 1},
            ]
        }
    )

    with _repos(skus={s.sku.id: s for s in (camisa, medias)}, venta=venta) as repos:
        await VentaService.replace_items(_session(), venta.id, data, actor, get_settings())

    assert (item_camisa.precio_normal, item_camisa.precio_unitario) == (Decimal("80"), Decimal("80"))
    assert item_camisa.producto_nombre == "Camisa Oxford"
    assert (item_camisa.cantidad, item_camisa.descuento_unitario) == (1, Decimal("5"))
    assert item_camisa.subtotal == Decimal("75")
    assert item_camisa.updated_by == actor.id
    [nuevo] = _added_items(repos)
    assert nuevo.precio_unitario == Decimal("20")  # el ítem nuevo entra con el precio del día
    assert (venta.subtotal, venta.total) == (Decimal("95"), Decimal("95"))


@pytest.mark.asyncio
async def test_replace_items_por_defecto_no_bloquea_si_el_precio_bajo() -> None:
    camisa = _sku_venta(normal=100)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.items[0].descuento_unitario = Decimal("70")
    venta.items[0].subtotal = Decimal("30")
    # El precio bajó a 50: recalcular daría 422, pero solo se corrige la nota.
    camisa.sku.precio = {"normal": 50, "rebajado": None, "rebaja_hasta": None}
    data = VentaItemsUpdate.model_validate(
        {
            "nota": "Recoge el lunes.",
            "items": [{"sku_id": str(camisa.sku.id), "cantidad": 1, "descuento_unitario": 70}],
        }
    )

    with _repos(skus={camisa.sku.id: camisa}, venta=venta):
        await VentaService.replace_items(_session(), venta.id, data, _actor(), get_settings())

    [item] = venta.items
    assert (item.precio_unitario, item.subtotal) == (Decimal("100"), Decimal("30"))
    assert item.updated_by is None  # nada del ítem cambió
    assert venta.total == Decimal("30")
    assert venta.nota == "Recoge el lunes."


@pytest.mark.asyncio
async def test_replace_items_por_defecto_valida_el_descuento_contra_el_precio_ofrecido() -> None:
    camisa = _sku_venta(normal=80)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    camisa.sku.precio = {"normal": 100, "rebajado": None, "rebaja_hasta": None}
    data = VentaItemsUpdate.model_validate(
        {"items": [{"sku_id": str(camisa.sku.id), "cantidad": 1, "descuento_unitario": 90}]}
    )

    with _repos(skus={camisa.sku.id: camisa}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.replace_items(_session(), venta.id, data, _actor(), get_settings())

    assert error.value.status_code == 422
    assert "items" in error.value.details


@pytest.mark.asyncio
async def test_replace_items_con_recalcular_rechaza_descuento_mayor_al_precio_del_dia() -> None:
    camisa = _sku_venta(normal=100)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    camisa.sku.precio = {"normal": 50, "rebajado": None, "rebaja_hasta": None}
    data = VentaItemsUpdate.model_validate(
        {
            "items": [{"sku_id": str(camisa.sku.id), "cantidad": 1, "descuento_unitario": 70}],
            "recalcular_precios": True,
        }
    )

    with _repos(skus={camisa.sku.id: camisa}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.replace_items(_session(), venta.id, data, _actor(), get_settings())

    assert error.value.status_code == 422


@pytest.mark.parametrize("estado", [EstadoVenta.CONFIRMADA, EstadoVenta.CANCELADA])
@pytest.mark.asyncio
async def test_replace_items_solo_en_pendiente(estado: EstadoVenta) -> None:
    camisa = _sku_venta()
    venta = _venta(estado, (camisa, 1))
    data = VentaItemsUpdate.model_validate({"items": [{"sku_id": str(camisa.sku.id), "cantidad": 2}]})

    with _repos(skus={camisa.sku.id: camisa}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.replace_items(_session(), venta.id, data, _actor(), get_settings())

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_replace_items_rechaza_sku_eliminado() -> None:
    camisa = _sku_venta()
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    data = VentaItemsUpdate.model_validate({"items": [{"sku_id": str(camisa.sku.id), "cantidad": 1}]})

    with _repos(skus={}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.replace_items(_session(), venta.id, data, _actor(), get_settings())

    assert error.value.status_code == 422


# ---------------------------------------------------------------- estado


@pytest.mark.asyncio
async def test_confirmar_descuenta_stock_y_fija_confirmada_at() -> None:
    camisa = _sku_venta(cantidad=5)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 2))
    actor = _actor()

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos:
        await VentaService.change_estado(_session(), venta.id, _confirmacion(_pago("59.90")), actor, get_settings())

    assert venta.estado == EstadoVenta.CONFIRMADA
    assert venta.confirmada_at is not None
    assert venta.total_pagado == Decimal("59.90")
    assert venta.cancelada_at is None
    assert venta.updated_by == actor.id
    assert camisa.sku.stock["cantidad"] == 3
    assert repos["get_skus"].call_args.kwargs["for_update"] is True


@pytest.mark.asyncio
async def test_confirmar_sin_stock_responde_409() -> None:
    camisa = _sku_venta(cantidad=1)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 2))

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos, pytest.raises(AppException) as error:
        await VentaService.change_estado(_session(), venta.id, _confirmacion(_pago("59.90")), _actor(), get_settings())

    repos["add_movimiento"].assert_not_called()
    assert error.value.status_code == 409
    assert "Stock insuficiente" in error.value.message
    assert venta.estado == EstadoVenta.PENDIENTE
    assert camisa.sku.stock["cantidad"] == 1
    assert venta.items[0].costo_unitario is None


@pytest.mark.asyncio
async def test_confirmar_con_sku_eliminado_responde_409() -> None:
    camisa = _sku_venta()
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))

    with _repos(skus={}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=EstadoVenta.CONFIRMADA), _actor(), get_settings()
        )

    assert error.value.status_code == 409
    assert "Camisa Oxford" in error.value.message


@pytest.mark.asyncio
async def test_cajero_cancela_pendiente_sin_tocar_stock() -> None:
    camisa = _sku_venta(cantidad=5)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 2))

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos:
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=EstadoVenta.CANCELADA), _actor(Role.CAJERO), get_settings()
        )

    assert venta.estado == EstadoVenta.CANCELADA
    assert venta.cancelada_at is not None
    assert camisa.sku.stock["cantidad"] == 5
    repos["get_skus"].assert_not_awaited()


@pytest.mark.asyncio
async def test_cajero_no_puede_anular_confirmada() -> None:
    camisa = _sku_venta(cantidad=3)
    venta = _venta(EstadoVenta.CONFIRMADA, (camisa, 2))

    with _repos(skus={camisa.sku.id: camisa}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=EstadoVenta.CANCELADA), _actor(Role.CAJERO), get_settings()
        )

    assert error.value.status_code == 403
    assert venta.estado == EstadoVenta.CONFIRMADA
    assert camisa.sku.stock["cantidad"] == 3


@pytest.mark.asyncio
async def test_owner_anula_confirmada_devuelve_stock_y_conserva_lo_pagado() -> None:
    camisa = _sku_venta(cantidad=3)
    venta = _venta(EstadoVenta.CONFIRMADA, (camisa, 2))

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos:
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=EstadoVenta.CANCELADA), _actor(Role.OWNER), get_settings()
        )

    assert venta.estado == EstadoVenta.CANCELADA
    assert venta.cancelada_at is not None
    assert camisa.sku.stock["cantidad"] == 5
    # Se devuelven todos los pagos: total_pagado queda como lo devuelto.
    assert venta.total_pagado == Decimal("59.90")
    repos["add_pago"].assert_not_called()
    [movimiento] = _added_movimientos(repos)
    assert (movimiento.tipo, movimiento.cantidad, movimiento.saldo, movimiento.venta_id) == (
        TipoMovimiento.ANULACION,
        2,
        5,
        venta.id,
    )


@pytest.mark.asyncio
async def test_confirmar_registra_la_venta_en_el_kardex_y_copia_el_costo() -> None:
    camisa = _sku_venta(cantidad=5, costo="12.50")
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 2))
    actor = _actor()

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos:
        await VentaService.change_estado(_session(), venta.id, _confirmacion(_pago("59.90")), actor, get_settings())

    [movimiento] = _added_movimientos(repos)
    assert movimiento.sku_id == camisa.sku.id
    assert (movimiento.tipo, movimiento.cantidad, movimiento.saldo) == (TipoMovimiento.VENTA, -2, 3)
    assert movimiento.costo_unitario == movimiento.costo_promedio == Decimal("12.50")
    assert movimiento.created_by == actor.id
    assert venta.items[0].costo_unitario == Decimal("12.50")
    # Una venta no cambia el costo promedio.
    assert camisa.sku.costo == Decimal("12.50")


@pytest.mark.asyncio
async def test_anular_devuelve_al_costo_con_que_salio_y_recalcula_el_promedio() -> None:
    # Salieron 2 a 10; mientras tanto el promedio subió a 16 con 2 en stock.
    camisa = _sku_venta(cantidad=2, costo="16")
    venta = _venta(EstadoVenta.CONFIRMADA, (camisa, 2))
    venta.items[0].costo_unitario = Decimal("10")

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos:
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=EstadoVenta.CANCELADA), _actor(Role.OWNER), get_settings()
        )

    [movimiento] = _added_movimientos(repos)
    assert movimiento.costo_unitario == Decimal("10")
    assert camisa.sku.costo == movimiento.costo_promedio == Decimal("13.00")


@pytest.mark.asyncio
async def test_anular_omite_skus_eliminados_en_el_kardex() -> None:
    camisa = _sku_venta(cantidad=3)
    venta = _venta(EstadoVenta.CONFIRMADA, (camisa, 2))

    with _repos(skus={}, venta=venta) as repos:
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=EstadoVenta.CANCELADA), _actor(Role.OWNER), get_settings()
        )

    assert venta.estado == EstadoVenta.CANCELADA
    repos["add_movimiento"].assert_not_called()


@pytest.mark.parametrize(
    ("actual", "destino"),
    [
        (EstadoVenta.CANCELADA, EstadoVenta.CONFIRMADA),
        (EstadoVenta.CANCELADA, EstadoVenta.CANCELADA),
        (EstadoVenta.CONFIRMADA, EstadoVenta.CONFIRMADA),
    ],
)
@pytest.mark.asyncio
async def test_transiciones_invalidas_responden_409(actual: EstadoVenta, destino: EstadoVenta) -> None:
    camisa = _sku_venta()
    venta = _venta(actual, (camisa, 1))

    with _repos(skus={camisa.sku.id: camisa}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=destino), _actor(Role.ADMIN), get_settings()
        )

    assert error.value.status_code == 409


# ------------------------------------------------- confirmar: proforma o precios del día


async def _confirmar(
    venta: Venta,
    *skus: SkuParaVenta,
    actor: CurrentUser | None = None,
    recalcular: bool = True,
    pagos: tuple[dict[str, str], ...] = (),
) -> None:
    with _repos(skus={s.sku.id: s for s in skus}, venta=venta):
        await VentaService.change_estado(
            _session(),
            venta.id,
            _confirmacion(*pagos, recalcular=recalcular),
            actor or _actor(),
            get_settings(),
        )


@pytest.mark.asyncio
async def test_confirmar_cobra_el_precio_y_los_nombres_del_dia() -> None:
    camisa = _sku_venta(normal=100)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 2))  # se pidió a 100
    venta.descuento = Decimal("10")
    venta.total = venta.subtotal - venta.descuento
    # Antes de confirmar entra una rebaja y se corrige el nombre del producto.
    camisa.sku.precio = {"normal": 100, "rebajado": 80, "rebaja_hasta": None}
    camisa = SkuParaVenta(camisa.sku, "Camisa Oxford slim", "Azul marino", "M")
    actor = _actor()

    await _confirmar(venta, camisa, actor=actor, pagos=(_pago("150"),))

    [item] = venta.items
    assert (item.precio_normal, item.precio_unitario) == (Decimal("100"), Decimal("80"))
    assert item.subtotal == Decimal("160")
    assert item.producto_nombre == "Camisa Oxford slim"
    assert item.updated_by == actor.id
    assert (venta.subtotal, venta.descuento, venta.total) == (Decimal("160"), Decimal("10"), Decimal("150"))
    assert venta.estado == EstadoVenta.CONFIRMADA
    assert camisa.sku.stock["cantidad"] == 8


@pytest.mark.asyncio
async def test_confirmar_sin_cambios_en_el_catalogo_no_toca_los_items() -> None:
    camisa = _sku_venta()
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))

    await _confirmar(venta, camisa, pagos=(_pago("29.95"),))

    assert venta.items[0].updated_by is None
    assert venta.estado == EstadoVenta.CONFIRMADA


@pytest.mark.asyncio
async def test_confirmar_rechaza_descuento_mayor_al_precio_del_dia_sin_tocar_stock() -> None:
    camisa = _sku_venta(normal=100, cantidad=5)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.items[0].descuento_unitario = Decimal("90")
    camisa.sku.precio = {"normal": 50, "rebajado": None, "rebaja_hasta": None}  # bajó el precio

    with pytest.raises(AppException) as error:
        await _confirmar(venta, camisa)

    assert error.value.status_code == 422
    assert "items" in error.value.details
    assert venta.estado == EstadoVenta.PENDIENTE
    assert camisa.sku.stock["cantidad"] == 5


@pytest.mark.asyncio
async def test_confirmar_rechaza_descuento_de_venta_mayor_al_nuevo_subtotal() -> None:
    camisa = _sku_venta(normal=100, cantidad=5)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.descuento = Decimal("90")
    camisa.sku.precio = {"normal": 50, "rebajado": None, "rebaja_hasta": None}

    with pytest.raises(AppException) as error:
        await _confirmar(venta, camisa)

    assert error.value.status_code == 422
    assert "descuento" in error.value.details
    assert camisa.sku.stock["cantidad"] == 5


@pytest.mark.asyncio
async def test_cancelar_no_recalcula_precios() -> None:
    camisa = _sku_venta(normal=100)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    camisa.sku.precio = {"normal": 70, "rebajado": None, "rebaja_hasta": None}

    with _repos(skus={camisa.sku.id: camisa}, venta=venta):
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=EstadoVenta.CANCELADA), _actor(), get_settings()
        )

    assert venta.items[0].precio_unitario == Decimal("100")
    assert venta.total == Decimal("100")


@pytest.mark.asyncio
async def test_confirmar_por_defecto_cobra_la_proforma_tal_como_se_ofrecio() -> None:
    camisa = _sku_venta(normal=100, cantidad=5)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.items[0].descuento_unitario = Decimal("70")
    venta.items[0].subtotal = Decimal("30")
    venta.subtotal = venta.total = Decimal("30")
    # El precio bajó a 50: recalcular daría 422, pero la proforma se cobra como se ofreció.
    camisa.sku.precio = {"normal": 50, "rebajado": None, "rebaja_hasta": None}

    with _repos(skus={camisa.sku.id: camisa}, venta=venta):
        await VentaService.change_estado(_session(), venta.id, _confirmacion(_pago("30")), _actor(), get_settings())

    [item] = venta.items
    assert (item.precio_unitario, item.subtotal) == (Decimal("100"), Decimal("30"))
    assert item.updated_by is None
    assert venta.total == Decimal("30")
    assert venta.estado == EstadoVenta.CONFIRMADA
    assert camisa.sku.stock["cantidad"] == 4


# ---------------------------------------------------------------- pagos


@pytest.mark.asyncio
async def test_create_pendiente_registra_anticipo() -> None:
    camisa = _sku_venta(normal=100)
    actor = _actor()
    data = VentaCreate.model_validate(
        {
            "items": [{"sku_id": str(camisa.sku.id), "cantidad": 1}],
            "pagos": [{"metodo": "QR", "monto": "40", "referencia": "0048213"}],
        }
    )

    with _repos(skus={camisa.sku.id: camisa}) as repos:
        await VentaService.create(_session(), data, actor, get_settings())

    venta = repos["add_venta"].call_args.args[0]
    [pago] = _added_pagos(repos)
    assert (pago.venta_id, pago.metodo, pago.monto, pago.referencia) == (
        venta.id,
        MetodoPago.QR,
        Decimal("40"),
        "0048213",
    )
    assert pago.created_by == pago.updated_by == actor.id
    assert venta.estado == EstadoVenta.PENDIENTE
    assert venta.total_pagado == Decimal("40")
    assert camisa.sku.stock["cantidad"] == 10


@pytest.mark.asyncio
async def test_create_confirmada_con_pagos_mixtos_conserva_el_orden() -> None:
    camisa = _sku_venta(normal=100)
    data = VentaCreate.model_validate(
        {
            "estado": "CONFIRMADA",
            "items": [{"sku_id": str(camisa.sku.id), "cantidad": 3}],
            "pagos": [_pago("200"), _pago("50", "QR"), _pago("50", "TRANSFERENCIA")],
        }
    )

    with _repos(skus={camisa.sku.id: camisa}) as repos:
        await VentaService.create(_session(), data, _actor(), get_settings())

    venta = repos["add_venta"].call_args.args[0]
    pagos = _added_pagos(repos)
    assert [pago.metodo for pago in pagos] == [MetodoPago.EFECTIVO, MetodoPago.QR, MetodoPago.TRANSFERENCIA]
    assert all(a.created_at < b.created_at for a, b in zip(pagos, pagos[1:]))
    assert venta.total_pagado == venta.total == Decimal("300")
    assert venta.estado == EstadoVenta.CONFIRMADA


@pytest.mark.parametrize("pagos", [[], [_pago("99.99")], [_pago("50"), _pago("49.99", "QR")]])
@pytest.mark.asyncio
async def test_create_confirmada_sin_cubrir_el_total_responde_409_sin_tocar_stock(
    pagos: list[dict[str, str]],
) -> None:
    camisa = _sku_venta(normal=100, cantidad=5)
    session = _session()
    data = VentaCreate.model_validate(
        {"estado": "CONFIRMADA", "items": [{"sku_id": str(camisa.sku.id), "cantidad": 1}], "pagos": pagos}
    )

    with _repos(skus={camisa.sku.id: camisa}), pytest.raises(AppException) as error:
        await VentaService.create(session, data, _actor(), get_settings())

    assert error.value.status_code == 409
    assert "Falta cobrar" in error.value.message
    assert "pagos" in error.value.details
    assert camisa.sku.stock["cantidad"] == 5
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("estado", ["PENDIENTE", "CONFIRMADA"])
@pytest.mark.asyncio
async def test_create_con_pagos_mayores_al_total_responde_409(estado: str) -> None:
    camisa = _sku_venta(normal=100)
    data = VentaCreate.model_validate(
        {
            "estado": estado,
            "items": [{"sku_id": str(camisa.sku.id), "cantidad": 1}],
            "pagos": [_pago("80"), _pago("20.01", "QR")],
        }
    )

    with _repos(skus={camisa.sku.id: camisa}), pytest.raises(AppException) as error:
        await VentaService.create(_session(), data, _actor(), get_settings())

    assert error.value.status_code == 409
    assert "superan el saldo" in error.value.message


@pytest.mark.asyncio
async def test_confirmar_suma_anticipo_y_saldo() -> None:
    camisa = _sku_venta(normal=100, cantidad=5)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.total_pagado = Decimal("40")  # anticipo por QR

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos:
        await VentaService.change_estado(_session(), venta.id, _confirmacion(_pago("60")), _actor(), get_settings())

    [saldo] = _added_pagos(repos)
    assert (saldo.venta_id, saldo.monto) == (venta.id, Decimal("60"))
    assert venta.total_pagado == Decimal("100")
    assert venta.estado == EstadoVenta.CONFIRMADA
    assert camisa.sku.stock["cantidad"] == 4


@pytest.mark.asyncio
async def test_confirmar_ya_pagada_con_anticipos_no_requiere_pagos() -> None:
    camisa = _sku_venta(normal=100)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.total_pagado = Decimal("100")

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos:
        await VentaService.change_estado(_session(), venta.id, _confirmacion(), _actor(), get_settings())

    assert venta.estado == EstadoVenta.CONFIRMADA
    repos["add_pago"].assert_not_called()


@pytest.mark.asyncio
async def test_confirmar_con_saldo_pendiente_responde_409_sin_tocar_stock() -> None:
    camisa = _sku_venta(normal=100, cantidad=5)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.total_pagado = Decimal("40")

    with _repos(skus={camisa.sku.id: camisa}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.change_estado(_session(), venta.id, _confirmacion(_pago("30")), _actor(), get_settings())

    assert error.value.status_code == 409
    assert "Falta cobrar 30" in error.value.message
    assert venta.estado == EstadoVenta.PENDIENTE
    assert camisa.sku.stock["cantidad"] == 5


@pytest.mark.asyncio
async def test_confirmar_recalculando_por_debajo_de_lo_pagado_responde_409() -> None:
    camisa = _sku_venta(normal=100, cantidad=5)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.total_pagado = Decimal("100")
    camisa.sku.precio = {"normal": 80, "rebajado": None, "rebaja_hasta": None}  # bajó el precio

    with pytest.raises(AppException) as error:
        await _confirmar(venta, camisa)

    assert error.value.status_code == 409
    assert "menor que lo ya pagado" in error.value.message
    assert venta.estado == EstadoVenta.PENDIENTE
    assert camisa.sku.stock["cantidad"] == 5


@pytest.mark.asyncio
async def test_replace_items_no_baja_el_total_de_lo_pagado() -> None:
    camisa = _sku_venta(normal=100)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 2))
    venta.total_pagado = Decimal("150")
    session = _session()
    data = VentaItemsUpdate.model_validate({"items": [{"sku_id": str(camisa.sku.id), "cantidad": 1}]})

    with _repos(skus={camisa.sku.id: camisa}, venta=venta), pytest.raises(AppException) as error:
        await VentaService.replace_items(session, venta.id, data, _actor(), get_settings())

    assert error.value.status_code == 409
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelar_pendiente_con_anticipo_lo_devuelve() -> None:
    camisa = _sku_venta(normal=100)
    venta = _venta(EstadoVenta.PENDIENTE, (camisa, 1))
    venta.total_pagado = Decimal("40")

    with _repos(skus={camisa.sku.id: camisa}, venta=venta) as repos:
        await VentaService.change_estado(
            _session(), venta.id, VentaEstadoUpdate(estado=EstadoVenta.CANCELADA), _actor(), get_settings()
        )

    assert venta.estado == EstadoVenta.CANCELADA
    assert venta.total_pagado == Decimal("40")
    repos["add_pago"].assert_not_called()


def test_resumen_suma_pagos_por_metodo_y_anticipos() -> None:
    resumen = VentaService._resumen(
        {
            EstadoVenta.CONFIRMADA: (Decimal("300"), Decimal("300")),
            EstadoVenta.PENDIENTE: (Decimal("160"), Decimal("50")),
        },
        {MetodoPago.EFECTIVO: Decimal("200"), MetodoPago.QR: Decimal("100")},
    )

    assert resumen.confirmada.efectivo == Decimal("200")
    assert resumen.confirmada.qr == Decimal("100")
    assert resumen.confirmada.transferencia == Decimal("0")
    assert resumen.confirmada.total == Decimal("300")
    assert (resumen.pendiente, resumen.pendiente_pagado) == (Decimal("160"), Decimal("50"))
    assert resumen.cancelada == Decimal("0")
