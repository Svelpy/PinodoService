from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.services import ProductoColorService
from app.domains.productos.models import Producto
from app.domains.productos.repositories import ProductoRepository
from app.domains.productos.schemas import ProductoCreate, ProductoUpdate
from app.domains.productos.services import ProductoService
from app.domains.secciones.models import Seccion
from app.domains.secciones.repositories import SeccionRepository
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _producto() -> Producto:
    return Producto(seccion_id=uuid4(), nombre="Camisa Oxford", cuidados="Lavar a 30 °C")


@pytest.mark.asyncio
async def test_create_valida_seccion_y_asigna_auditoria() -> None:
    seccion = Seccion(nombre="Hombre", slug="hombre")
    session = _session()
    actor_id = uuid4()

    with (
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=seccion)),
        patch.object(ProductoRepository, "add") as add,
    ):
        producto = await ProductoService.create(
            session,
            ProductoCreate(seccion_id=seccion.id, nombre=" Camisa Oxford "),
            actor_id,
        )

    assert producto.nombre == "Camisa Oxford"
    assert producto.created_by == actor_id
    assert producto.updated_by == actor_id
    add.assert_called_once_with(producto)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_rechaza_seccion_inexistente() -> None:
    session = _session()

    with patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await ProductoService.create(
                session,
                ProductoCreate(seccion_id=uuid4(), nombre="Camisa"),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert "seccion_id" in error.value.details
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_aplica_cambios_y_null_explicito() -> None:
    producto = _producto()
    actor_id = uuid4()

    with patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)):
        result = await ProductoService.update(
            _session(),
            producto.id,
            ProductoUpdate(nombre="Camisa Oxford slim", cuidados=None),
            actor_id,
        )

    assert result.nombre == "Camisa Oxford slim"
    assert result.cuidados is None
    assert result.updated_by == actor_id


@pytest.mark.asyncio
async def test_update_misma_seccion_no_valida_categorias() -> None:
    producto = _producto()

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(ProductoRepository, "has_active_categorias", new=AsyncMock()) as categorias,
    ):
        await ProductoService.update(
            _session(),
            producto.id,
            ProductoUpdate(seccion_id=producto.seccion_id),
            uuid4(),
        )

    categorias.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cambio_de_seccion_con_categorias_responde_409() -> None:
    producto = _producto()
    seccion_original = producto.seccion_id

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(
            SeccionRepository,
            "get_by_id",
            new=AsyncMock(return_value=Seccion(nombre="Mujer", slug="mujer")),
        ),
        patch.object(
            ProductoRepository,
            "has_active_categorias",
            new=AsyncMock(return_value=True),
        ),
    ):
        with pytest.raises(AppException) as error:
            await ProductoService.update(
                _session(),
                producto.id,
                ProductoUpdate(seccion_id=uuid4()),
                uuid4(),
            )

    assert error.value.status_code == 409
    assert producto.seccion_id == seccion_original


@pytest.mark.asyncio
async def test_update_cambio_de_seccion_sin_categorias() -> None:
    producto = _producto()
    destino = uuid4()

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(
            SeccionRepository,
            "get_by_id",
            new=AsyncMock(return_value=Seccion(nombre="Mujer", slug="mujer")),
        ),
        patch.object(
            ProductoRepository,
            "has_active_categorias",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await ProductoService.update(
            _session(),
            producto.id,
            ProductoUpdate(seccion_id=destino),
            uuid4(),
        )

    assert result.seccion_id == destino


@pytest.mark.asyncio
async def test_delete_elimina_en_cascada_colores_hijos_y_enlaces() -> None:
    producto = _producto()
    actor_id = uuid4()
    session = _session()
    producto_color_ids = [uuid4(), uuid4()]

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(
            ProductoColorRepository,
            "list_active_ids_by_producto",
            new=AsyncMock(return_value=producto_color_ids),
        ),
        patch.object(ProductoColorService, "delete_children", new=AsyncMock()) as children,
        patch.object(
            ProductoColorRepository,
            "soft_delete_by_ids",
            new=AsyncMock(return_value=2),
        ) as colores,
        patch.object(
            CategoriaProductoRepository,
            "soft_delete_by_producto",
            new=AsyncMock(return_value=3),
        ) as enlaces,
    ):
        await ProductoService.delete(session, producto.id, actor_id)

    now = producto.deleted_at
    assert producto.is_deleted is True
    assert producto.deleted_by == actor_id
    children.assert_awaited_once_with(session, producto_color_ids, actor_id, now)
    colores.assert_awaited_once_with(producto_color_ids, actor_id, now)
    enlaces.assert_awaited_once_with(producto.id, actor_id, now)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_recorta_la_busqueda_por_nombre() -> None:
    with patch.object(
        ProductoRepository,
        "list",
        new=AsyncMock(return_value=([], 0)),
    ) as repository_list:
        page = await ProductoService.list(_session(), nombre="  oxford ")

    assert page.total == 0
    assert repository_list.await_args.kwargs["nombre"] == "oxford"


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(ProductoRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await ProductoService.get(_session(), uuid4())

    assert error.value.status_code == 404
