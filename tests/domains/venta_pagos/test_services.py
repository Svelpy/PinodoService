from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.domains.auth.schemas import CurrentUser
from app.domains.venta_pagos.models import VentaPago
from app.domains.venta_pagos.repositories import VentaPagoRepository, VentaPagoScope
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

