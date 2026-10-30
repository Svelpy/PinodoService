from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.colores.models import Color
from app.domains.colores.repositories import ColorRepository
from app.domains.imagenes.repositories import ImagenRepository
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.schemas import ProductoColorCreate, ProductoColorUpdate
from app.domains.producto_colores.services import ProductoColorService
from app.domains.productos.models import Producto
from app.domains.productos.repositories import ProductoRepository
from app.domains.skus.repositories import SkuRepository
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _producto() -> Producto:
    return Producto(seccion_id=uuid4(), nombre="Camisa Oxford")


def _color(nombre: str = "Azul") -> Color:
    return Color(nombre=nombre, slug=nombre.lower(), codigo_hex="#1E3A8A")


def _producto_color() -> ProductoColor:
    return ProductoColor(producto_id=uuid4(), color_id=uuid4())


@pytest.mark.asyncio
async def test_create_valida_referencias_y_asigna_auditoria() -> None:
    producto = _producto()
    color = _color()
    session = _session()
    actor_id = uuid4()

    with (
        patch.object(ProductoRepository, "get_by_id", new=AsyncMock(return_value=producto)),
        patch.object(ColorRepository, "get_by_id", new=AsyncMock(return_value=color)),
        patch.object(
            ProductoColorRepository,
            "get_active_by_producto_and_color",
            new=AsyncMock(return_value=None),
        ),
        patch.object(ProductoColorRepository, "add") as add,
    ):
        producto_color = await ProductoColorService.create(
            session,
            ProductoColorCreate(producto_id=producto.id, color_id=color.id),
            actor_id,
        )

    assert producto_color.producto_id == producto.id
    assert producto_color.is_visible is True
    assert producto_color.created_by == actor_id
    add.assert_called_once_with(producto_color)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("producto_existe", "color_existe", "campo"),
    [(False, True, "producto_id"), (True, False, "color_id")],
)
@pytest.mark.asyncio
async def test_create_rechaza_referencias_inexistentes(
    producto_existe: bool,
    color_existe: bool,
    campo: str,
) -> None:
    with (
        patch.object(
            ProductoRepository,
            "get_by_id",
            new=AsyncMock(return_value=_producto() if producto_existe else None),
        ),
        patch.object(
            ColorRepository,
            "get_by_id",
            new=AsyncMock(return_value=_color() if color_existe else None),
        ),
    ):
        with pytest.raises(AppException) as error:
            await ProductoColorService.create(
                _session(),
                ProductoColorCreate(producto_id=uuid4(), color_id=uuid4()),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert campo in error.value.details


@pytest.mark.asyncio
async def test_create_rechaza_color_repetido_en_el_producto() -> None:
    session = _session()

    with (
        patch.object(ProductoRepository, "get_by_id", new=AsyncMock(return_value=_producto())),
        patch.object(ColorRepository, "get_by_id", new=AsyncMock(return_value=_color())),
        patch.object(
            ProductoColorRepository,
            "get_active_by_producto_and_color",
            new=AsyncMock(return_value=_producto_color()),
        ),
    ):
        with pytest.raises(AppException) as error:
            await ProductoColorService.create(
                session,
                ProductoColorCreate(producto_id=uuid4(), color_id=uuid4()),
                uuid4(),
            )

    assert error.value.status_code == 409
    assert "color_id" in error.value.details
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cambia_color_validando_unicidad_en_el_mismo_producto() -> None:
    producto_color = _producto_color()
    nuevo = _color("Negro")
    actor_id = uuid4()

    with (
        patch.object(ProductoColorService, "get", new=AsyncMock(return_value=producto_color)),
        patch.object(ColorRepository, "get_by_id", new=AsyncMock(return_value=nuevo)),
        patch.object(
            ProductoColorRepository,
            "get_active_by_producto_and_color",
            new=AsyncMock(return_value=None),
        ) as unique,
    ):
        result = await ProductoColorService.update(
            _session(),
            producto_color.id,
            ProductoColorUpdate(color_id=nuevo.id),
            actor_id,
        )

    unique.assert_awaited_once_with(
        producto_color.producto_id,
        nuevo.id,
        exclude_id=producto_color.id,
    )
    assert result.color_id == nuevo.id
    assert result.updated_by == actor_id


@pytest.mark.asyncio
async def test_update_solo_visibilidad_no_valida_color() -> None:
    producto_color = _producto_color()

    with (
        patch.object(ProductoColorService, "get", new=AsyncMock(return_value=producto_color)),
        patch.object(ColorRepository, "get_by_id", new=AsyncMock()) as color,
    ):
        result = await ProductoColorService.update(
            _session(),
            producto_color.id,
            ProductoColorUpdate(is_visible=False),
            uuid4(),
        )

    color.assert_not_awaited()
    assert result.is_visible is False


def test_update_no_acepta_cambiar_el_producto() -> None:
    with pytest.raises(ValueError):
        ProductoColorUpdate.model_validate({"producto_id": str(uuid4())})


@pytest.mark.asyncio
async def test_delete_elimina_en_cascada_imagenes_y_skus() -> None:
    producto_color = _producto_color()
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(ProductoColorService, "get", new=AsyncMock(return_value=producto_color)),
        patch.object(
            ImagenRepository,
            "soft_delete_by_producto_color_ids",
            new=AsyncMock(return_value=2),
        ) as imagenes,
        patch.object(
            SkuRepository,
            "soft_delete_by_producto_color_ids",
            new=AsyncMock(return_value=3),
        ) as skus,
    ):
        await ProductoColorService.delete(session, producto_color.id, actor_id)

    assert producto_color.is_deleted is True
    assert producto_color.deleted_by == actor_id
    imagenes.assert_awaited_once_with([producto_color.id], actor_id, producto_color.deleted_at)
    skus.assert_awaited_once_with([producto_color.id], actor_id, producto_color.deleted_at)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_no_confirma_nada_si_falla_la_cascada() -> None:
    producto_color = _producto_color()
    session = _session()

    with (
        patch.object(ProductoColorService, "get", new=AsyncMock(return_value=producto_color)),
        patch.object(
            ImagenRepository,
            "soft_delete_by_producto_color_ids",
            new=AsyncMock(side_effect=RuntimeError("fallo")),
        ),
    ):
        with pytest.raises(RuntimeError):
            await ProductoColorService.delete(session, producto_color.id, uuid4())

    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(ProductoColorRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await ProductoColorService.get(_session(), uuid4())

    assert error.value.status_code == 404
