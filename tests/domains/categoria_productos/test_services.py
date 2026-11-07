from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.base_model import utc_now
from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.categoria_productos.services import CategoriaProductoService
from app.domains.categorias.models import Categoria
from app.domains.categorias.repositories import CategoriaRepository
from app.domains.productos.models import Producto
from app.shared.errors.exceptions import AppException


@pytest.fixture(autouse=True)
def _categorias_hoja() -> Iterator[AsyncMock]:
    """Por defecto, ninguna categoría tiene subcategorías (todas son hojas)."""
    with patch.object(
        CategoriaRepository, "list_ids_with_active_children", new=AsyncMock(return_value=set())
    ) as con_hijas:
        yield con_hijas


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


@contextmanager
def _patches(categorias: list[Categoria], links: list[CategoriaProducto]) -> Iterator[None]:
    with (
        patch.object(CategoriaRepository, "get_many_by_ids", new=AsyncMock(return_value=categorias)),
        patch.object(
            CategoriaProductoRepository,
            "list_active_by_producto",
            new=AsyncMock(return_value=links),
        ),
    ):
        yield


async def _apply(
    session: MagicMock,
    producto: Producto,
    categoria_ids: list[UUID],
    actor_id: UUID | None = None,
) -> tuple[int, int]:
    return await CategoriaProductoService.apply_categorias(
        session,
        producto.id,
        producto.seccion_id,
        categoria_ids,
        actor_id or uuid4(),
        utc_now(),
    )


@pytest.mark.asyncio
async def test_reemplazo_conserva_quita_y_anade_sin_commit() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    a = _categoria(producto.seccion_id, "A")
    b = _categoria(producto.seccion_id, "B")
    c = _categoria(producto.seccion_id, "C")
    link_a = _link(producto, a)
    link_c = _link(producto, c)
    session = _session()
    actor_id = uuid4()

    with _patches([a, b], [link_a, link_c]):
        result = await _apply(session, producto, [a.id, b.id], actor_id)

    assert result == (1, 1)
    assert link_a.is_deleted is False
    assert link_a.updated_by is None
    assert link_c.is_deleted is True
    assert link_c.deleted_by == actor_id
    assert link_c.deleted_at is not None

    added = [call.args[0] for call in session.add.call_args_list]
    assert [(link.categoria_id, link.producto_id) for link in added] == [(b.id, producto.id)]
    assert added[0].created_by == actor_id
    # El commit lo hace quien coordina (PATCH o POST de productos).
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_lista_vacia_quita_todas() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    link_a = _link(producto, _categoria(producto.seccion_id, "A"))
    session = _session()

    with _patches([], [link_a]):
        result = await _apply(session, producto, [])

    assert result == (0, 1)
    assert link_a.is_deleted is True
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_mismo_conjunto_no_cambia_nada() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    a = _categoria(producto.seccion_id, "A")
    session = _session()

    with _patches([a], [_link(producto, a)]):
        result = await _apply(session, producto, [a.id])

    assert result == (0, 0)
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_rechaza_categorias_inexistentes_sin_cambiar_nada() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    a = _categoria(producto.seccion_id, "A")
    inexistente = uuid4()
    session = _session()

    with _patches([a], []), pytest.raises(AppException) as error:
        await _apply(session, producto, [a.id, inexistente])

    assert error.value.status_code == 422
    assert str(inexistente) in error.value.details["categoria_ids"]
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_rechaza_categorias_de_otra_seccion() -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    ajena = _categoria(uuid4(), "Vestidos")
    session = _session()

    with _patches([ajena], []), pytest.raises(AppException) as error:
        await _apply(session, producto, [ajena.id])

    assert error.value.status_code == 422
    assert "otra sección" in error.value.details["categoria_ids"]
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_rechaza_categorias_con_subcategorias_sin_cambiar_nada(
    _categorias_hoja: AsyncMock,
) -> None:
    producto = Producto(seccion_id=uuid4(), nombre="Camisa")
    ropa = _categoria(producto.seccion_id, "Ropa")
    camisas = _categoria(producto.seccion_id, "Camisas")
    session = _session()
    _categorias_hoja.return_value = {ropa.id}

    with _patches([ropa, camisas], []), pytest.raises(AppException) as error:
        await _apply(session, producto, [camisas.id, ropa.id])

    assert error.value.status_code == 422
    detalle = error.value.details["categoria_ids"]
    assert str(ropa.id) in detalle and str(camisas.id) not in detalle
    session.add.assert_not_called()
