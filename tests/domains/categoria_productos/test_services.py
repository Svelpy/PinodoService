from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.categoria_productos.schemas import ProductoCategoriasUpdate
from app.domains.categoria_productos.services import CategoriaProductoService
from app.domains.categorias.models import Categoria
from app.domains.categorias.repositories import CategoriaRepository
from app.domains.productos.models import Producto
from app.domains.productos.repositories import ProductoRepository
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


def _categoria(seccion_id: UUID, nombre: str) -> Categoria:
    return Categoria(seccion_id=seccion_id, nombre=nombre, slug=nombre.lower())


def _link(producto: Producto, categoria: Categoria) -> CategoriaProducto:
    return CategoriaProducto(categoria_id=categoria.id, producto_id=producto.id)


def _patches(
    producto: Producto | None,
    categorias: list[Categoria],
    links: list[CategoriaProducto],
):
    return (
        patch.object(ProductoRepository, "get_by_id", new=AsyncMock(return_value=producto)),
        patch.object(CategoriaRepository, "get_many_by_ids", new=AsyncMock(return_value=categorias)),
        patch.object(
            CategoriaProductoRepository,
            "list_active_by_producto",
            new=AsyncMock(return_value=links),
        ),
        patch.object(
            CategoriaProductoRepository,
            "list_categorias_by_producto",
            new=AsyncMock(return_value=[]),
        ),
    )


@pytest.mark.asyncio
async def test_reemplazo_conserva_quita_y_anade() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    a = _categoria(producto.seccion_id, "A")
    b = _categoria(producto.seccion_id, "B")
    c = _categoria(producto.seccion_id, "C")
    link_a = _link(producto, a)
    link_c = _link(producto, c)
    session = _session()
    actor_id = uuid4()

    p1, p2, p3, p4 = _patches(producto, [a, b], [link_a, link_c])
    with p1, p2, p3, p4:
        await CategoriaProductoService.replace_categorias(
            session,
            producto.id,
            ProductoCategoriasUpdate(categoria_ids=[a.id, b.id]),
            actor_id,
        )

    assert link_a.is_deleted is False
    assert link_a.updated_by is None
    assert link_c.is_deleted is True
    assert link_c.deleted_by == actor_id
    assert link_c.deleted_at is not None

    added = [call.args[0] for call in session.add.call_args_list]
    assert [(link.categoria_id, link.producto_id) for link in added] == [(b.id, producto.id)]
    assert added[0].created_by == actor_id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_lista_vacia_quita_todas() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    a = _categoria(producto.seccion_id, "A")
    link_a = _link(producto, a)
    session = _session()

    p1, p2, p3, p4 = _patches(producto, [], [link_a])
    with p1, p2, p3, p4:
        await CategoriaProductoService.replace_categorias(
            session,
            producto.id,
            ProductoCategoriasUpdate(categoria_ids=[]),
            uuid4(),
        )

    assert link_a.is_deleted is True
    session.add.assert_not_called()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mismo_conjunto_no_hace_commit() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    a = _categoria(producto.seccion_id, "A")
    session = _session()

    p1, p2, p3, p4 = _patches(producto, [a], [_link(producto, a)])
    with p1, p2, p3, p4:
        await CategoriaProductoService.replace_categorias(
            session,
            producto.id,
            ProductoCategoriasUpdate(categoria_ids=[a.id]),
            uuid4(),
        )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rechaza_categorias_inexistentes_sin_cambiar_nada() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    a = _categoria(producto.seccion_id, "A")
    inexistente = uuid4()
    session = _session()

    p1, p2, p3, p4 = _patches(producto, [a], [])
    with p1, p2, p3, p4:
        with pytest.raises(AppException) as error:
            await CategoriaProductoService.replace_categorias(
                session,
                producto.id,
                ProductoCategoriasUpdate(categoria_ids=[a.id, inexistente]),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert str(inexistente) in error.value.details["categoria_ids"]
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rechaza_categorias_de_otra_seccion() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    ajena = _categoria(uuid4(), "Vestidos")
    session = _session()

    p1, p2, p3, p4 = _patches(producto, [ajena], [])
    with p1, p2, p3, p4:
        with pytest.raises(AppException) as error:
            await CategoriaProductoService.replace_categorias(
                session,
                producto.id,
                ProductoCategoriasUpdate(categoria_ids=[ajena.id]),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert "otra sección" in error.value.details["categoria_ids"]
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_producto_inexistente_responde_404() -> None:
    p1, p2, p3, p4 = _patches(None, [], [])
    with p1, p2, p3, p4:
        with pytest.raises(AppException) as error:
            await CategoriaProductoService.replace_categorias(
                _session(),
                uuid4(),
                ProductoCategoriasUpdate(categoria_ids=[]),
                uuid4(),
            )

    assert error.value.status_code == 404
