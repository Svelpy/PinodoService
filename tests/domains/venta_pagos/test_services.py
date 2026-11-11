from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.domains.auth.schemas import CurrentUser
from app.domains.venta_pagos.models import VentaPago
from app.domains.venta_pagos.repositories import VentaPagoRepository, VentaPagoScope
from app.domains.venta_pagos.schemas import VentaPagoCreate, VentaPagoUpdate
from app.domains.venta_pagos.services import COMPROBANTES_FOLDER, VentaPagoService
from app.domains.ventas.models import Venta
from app.domains.ventas.repositories import VentaRepository, VentaScope
from app.integrations.cloudinary import CloudinaryService
from app.shared.enums import EstadoVenta, MetodoPago, Role
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _actor(rol: Role = Role.CAJERO) -> CurrentUser:
    return CurrentUser(id=uuid4(), rol=rol)


def _venta(estado: EstadoVenta = EstadoVenta.PENDIENTE, total: str = "100", pagado: str = "0") -> Venta:
    return Venta(
        estado=estado,
        subtotal=Decimal(total),
        total=Decimal(total),
        total_pagado=Decimal(pagado),
    )


def _pago(venta: Venta, **overrides: object) -> VentaPago:
    return VentaPago(
        venta_id=venta.id,
        metodo=MetodoPago.QR,
        monto=Decimal("40"),
        **overrides,
    )


def _create(venta: Venta, monto: str = "40", metodo: str = "QR") -> VentaPagoCreate:
    return VentaPagoCreate.model_validate({"venta_id": str(venta.id), "metodo": metodo, "monto": monto})


@contextmanager
def _repos(*, venta: Venta | None = None, pago: VentaPago | None = None) -> Iterator[dict[str, MagicMock]]:
    with (
        patch.object(VentaRepository, "get_by_id", new=AsyncMock(return_value=venta)) as get_venta,
        patch.object(VentaPagoRepository, "get_by_id", new=AsyncMock(return_value=pago)) as get_pago,
        patch.object(VentaPagoRepository, "add") as add_pago,
        patch.object(VentaPagoService, "_reload", new=AsyncMock(side_effect=lambda s, pago_id, a: pago_id)),
    ):
        yield {"get_venta": get_venta, "get_pago": get_pago, "add_pago": add_pago}


# ---------------------------------------------------------------- alcance


@pytest.mark.parametrize("rol", [Role.SUPERADMIN, Role.OWNER, Role.ADMIN])
def test_roles_superiores_ven_todos_los_pagos(rol: Role) -> None:
    assert VentaPagoService._scope_for(_actor(rol)) == VentaPagoScope(all=True)


def test_cajero_solo_ve_los_pagos_de_sus_ventas() -> None:
    actor = _actor(Role.CAJERO)

    assert VentaPagoService._scope_for(actor) == VentaPagoScope(venta_created_by=actor.id)


def test_scope_vacio_no_devuelve_filas() -> None:
    assert str(VentaPagoScope().condition()) == "false"


@pytest.mark.asyncio
async def test_get_fuera_de_alcance_responde_404() -> None:
    actor = _actor(Role.CAJERO)

    with _repos(pago=None) as repos, pytest.raises(AppException) as error:
        await VentaPagoService.get(_session(), uuid4(), actor)

    assert error.value.status_code == 404
    assert repos["get_pago"].call_args.kwargs["scope"] == VentaPagoScope(venta_created_by=actor.id)


# ---------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_registra_el_pago_y_suma_al_total_pagado() -> None:
    venta = _venta(pagado="30")
    actor = _actor()
    session = _session()

    with _repos(venta=venta) as repos:
        await VentaPagoService.create(session, _create(venta, "50"), actor)

    [pago] = [call.args[0] for call in repos["add_pago"].call_args_list]
    assert (pago.venta_id, pago.metodo, pago.monto) == (venta.id, MetodoPago.QR, Decimal("50"))
    assert pago.created_by == actor.id
    assert venta.total_pagado == Decimal("80")
    assert venta.updated_by == actor.id
    assert venta.estado == EstadoVenta.PENDIENTE
    session.commit.assert_awaited_once()
    # La venta se busca con el alcance del actor y bloqueada contra pagos simultáneos.
    kwargs = repos["get_venta"].call_args.kwargs
    assert kwargs["scope"] == VentaScope(created_by=actor.id)
    assert kwargs["for_update"] is True


@pytest.mark.asyncio
async def test_create_puede_completar_el_total() -> None:
    venta = _venta(pagado="60")

    with _repos(venta=venta):
        await VentaPagoService.create(_session(), _create(venta, "40"), _actor())

    assert venta.total_pagado == venta.total


@pytest.mark.asyncio
async def test_create_que_supera_el_saldo_responde_409() -> None:
    venta = _venta(pagado="60")
    session = _session()

    with _repos(venta=venta), pytest.raises(AppException) as error:
        await VentaPagoService.create(session, _create(venta, "40.01"), _actor())

    assert error.value.status_code == 409
    assert "monto" in error.value.details
    assert venta.total_pagado == Decimal("60")
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("estado", [EstadoVenta.CONFIRMADA, EstadoVenta.CANCELADA])
@pytest.mark.asyncio
async def test_create_solo_en_ventas_pendientes(estado: EstadoVenta) -> None:
    venta = _venta(estado, pagado="0" if estado == EstadoVenta.CANCELADA else "100")

    with _repos(venta=venta) as repos, pytest.raises(AppException) as error:
        await VentaPagoService.create(_session(), _create(venta, "1"), _actor())

    assert error.value.status_code == 409
    repos["add_pago"].assert_not_called()


@pytest.mark.asyncio
async def test_create_en_venta_fuera_de_alcance_responde_404() -> None:
    with _repos(venta=None), pytest.raises(AppException) as error:
        await VentaPagoService.create(_session(), _create(_venta()), _actor())

    assert error.value.status_code == 404


# ---------------------------------------------------------------- update


@pytest.mark.asyncio
async def test_update_cambia_la_referencia() -> None:
    pago = _pago(_venta(), referencia="111")
    actor = _actor()
    session = _session()

    with _repos(pago=pago):
        await VentaPagoService.update(session, pago.id, VentaPagoUpdate(referencia="222"), actor)

    assert pago.referencia == "222"
    assert pago.updated_by == actor.id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_sin_cambios_no_hace_commit() -> None:
    pago = _pago(_venta(), referencia="111")
    session = _session()

    with _repos(pago=pago):
        await VentaPagoService.update(session, pago.id, VentaPagoUpdate(referencia="111"), _actor())

    assert pago.updated_by is None
    session.commit.assert_not_awaited()


# ---------------------------------------------------------------- comprobante


@pytest.mark.asyncio
async def test_upload_comprobante_reemplaza_y_elimina_el_anterior() -> None:
    anterior = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/comprobantes/old.jpg"
    nueva = "https://res.cloudinary.com/demo/image/upload/v2/pinodo/comprobantes/new.jpg"
    pago = _pago(_venta(), comprobante_url=anterior)
    actor = _actor()
    file = MagicMock()

    with (
        _repos(pago=pago),
        patch.object(
            CloudinaryService,
            "upload_image",
            new=AsyncMock(return_value={"url": nueva, "public_id": "new"}),
        ) as upload,
        patch.object(CloudinaryService, "safe_delete_image", new=AsyncMock()) as delete,
    ):
        await VentaPagoService.upload_comprobante(_session(), pago.id, file, actor, get_settings())

    assert upload.call_args.args[:2] == (file, COMPROBANTES_FOLDER)
    assert pago.comprobante_url == nueva
    assert pago.updated_by == actor.id
    delete.assert_awaited_once_with(anterior)


@pytest.mark.asyncio
async def test_upload_comprobante_elimina_la_imagen_nueva_si_falla_el_guardado() -> None:
    nueva = "https://res.cloudinary.com/demo/image/upload/v2/pinodo/comprobantes/new.jpg"
    pago = _pago(_venta())
    session = _session()
    session.commit = AsyncMock(side_effect=RuntimeError("db caída"))

    with (
        _repos(pago=pago),
        patch.object(
            CloudinaryService,
            "upload_image",
            new=AsyncMock(return_value={"url": nueva, "public_id": "new"}),
        ),
        patch.object(CloudinaryService, "safe_delete_image", new=AsyncMock()) as delete,
        pytest.raises(RuntimeError),
    ):
        await VentaPagoService.upload_comprobante(session, pago.id, MagicMock(), _actor(), get_settings())

    delete.assert_awaited_once_with(nueva)


@pytest.mark.asyncio
async def test_upload_comprobante_de_pago_fuera_de_alcance_no_sube_nada() -> None:
    with (
        _repos(pago=None),
        patch.object(CloudinaryService, "upload_image", new=AsyncMock()) as upload,
        pytest.raises(AppException) as error,
    ):
        await VentaPagoService.upload_comprobante(_session(), uuid4(), MagicMock(), _actor(), get_settings())

    assert error.value.status_code == 404
    upload.assert_not_awaited()


# ---------------------------------------------------------------- list


@pytest.mark.asyncio
async def test_list_convierte_fechas_de_la_tienda_y_pagina() -> None:
    actor = _actor()
    with patch.object(VentaPagoRepository, "find_many", new=AsyncMock(return_value=([], 41))) as find:
        page = await VentaPagoService.list(
            _session(),
            actor,
            get_settings(),
            page=3,
            per_page=20,
            metodo=MetodoPago.QR,
            desde=date(2026, 11, 1),
            hasta=date(2026, 11, 7),
        )

    assert (page.total, page.total_pages) == (41, 3)
    kwargs = find.call_args.kwargs
    assert (kwargs["offset"], kwargs["limit"]) == (40, 20)
    assert kwargs["scope"] == VentaPagoScope(venta_created_by=actor.id)
    assert kwargs["metodo"] == MetodoPago.QR
    assert kwargs["hasta"] - kwargs["desde"] == date(2026, 11, 8) - date(2026, 11, 1)
    assert kwargs["desde"].date() == date(2026, 11, 1)


@pytest.mark.asyncio
async def test_list_rechaza_rango_invertido() -> None:
    with pytest.raises(AppException) as error:
        await VentaPagoService.list(
            _session(), _actor(), get_settings(), desde=date(2026, 11, 7), hasta=date(2026, 11, 1)
        )

    assert error.value.status_code == 422
