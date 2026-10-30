from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.categorias.models import Categoria
from app.domains.categorias.repositories import CategoriaRepository
from app.domains.categorias.schemas import CategoriaCreate, CategoriaUpdate
from app.domains.categorias.services import CategoriaService
from app.domains.secciones.models import Seccion
from app.domains.secciones.repositories import SeccionRepository
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _seccion(nombre: str = "Mujer") -> Seccion:
    return Seccion(nombre=nombre, slug=nombre.lower())


def _categoria(
    seccion_id: UUID,
    nombre: str = "Ropa",
    parent_id: UUID | None = None,
) -> Categoria:
    return Categoria(seccion_id=seccion_id, parent_id=parent_id, nombre=nombre, slug=nombre.lower())


def _by_id(*categorias: Categoria) -> AsyncMock:
    index = {categoria.id: categoria for categoria in categorias}
    return AsyncMock(side_effect=lambda categoria_id, **_: index.get(categoria_id))


@pytest.mark.asyncio
async def test_create_genera_slug_y_valida_unicidad_dentro_de_la_seccion() -> None:
    seccion = _seccion()
    session = _session()
    actor_id = uuid4()

    with (
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=seccion)),
        patch.object(
            CategoriaRepository,
            "get_active_by_slug",
            new=AsyncMock(return_value=None),
        ) as get_by_slug,
        patch.object(CategoriaRepository, "add") as add,
    ):
        categoria = await CategoriaService.create(
            session,
            CategoriaCreate(seccion_id=seccion.id, nombre="Vestidos Largos"),
            actor_id,
        )

    get_by_slug.assert_awaited_once_with(seccion.id, "vestidos-largos", exclude_id=None)
    assert categoria.slug == "vestidos-largos"
    assert categoria.created_by == actor_id
    add.assert_called_once_with(categoria)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_rechaza_seccion_inexistente() -> None:
    with patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await CategoriaService.create(
                _session(),
                CategoriaCreate(seccion_id=uuid4(), nombre="Ropa"),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert "seccion_id" in error.value.details


@pytest.mark.asyncio
async def test_create_rechaza_padre_de_otra_seccion() -> None:
    mujer = _seccion("Mujer")
    padre_hombre = _categoria(uuid4(), "Ropa")

    with (
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=mujer)),
        patch.object(CategoriaRepository, "get_by_id", new=_by_id(padre_hombre)),
    ):
        with pytest.raises(AppException) as error:
            await CategoriaService.create(
                _session(),
                CategoriaCreate(seccion_id=mujer.id, parent_id=padre_hombre.id, nombre="Vestidos"),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert "parent_id" in error.value.details


@pytest.mark.asyncio
async def test_create_rechaza_slug_duplicado_en_la_seccion() -> None:
    seccion = _seccion()

    with (
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=seccion)),
        patch.object(
            CategoriaRepository,
            "get_active_by_slug",
            new=AsyncMock(return_value=_categoria(seccion.id)),
        ),
    ):
        with pytest.raises(AppException) as error:
            await CategoriaService.create(
                _session(),
                CategoriaCreate(seccion_id=seccion.id, nombre="ROPA"),
                uuid4(),
            )

    assert error.value.status_code == 409
    assert "nombre" in error.value.details


@pytest.mark.asyncio
async def test_update_rechaza_ser_su_propio_padre() -> None:
    categoria = _categoria(uuid4())

    with patch.object(CategoriaService, "get", new=AsyncMock(return_value=categoria)):
        with pytest.raises(AppException) as error:
            await CategoriaService.update(
                _session(),
                categoria.id,
                CategoriaUpdate(parent_id=categoria.id),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert categoria.parent_id is None


@pytest.mark.asyncio
async def test_update_rechaza_ciclo_con_una_descendiente() -> None:
    seccion_id = uuid4()
    ropa = _categoria(seccion_id, "Ropa")
    vestidos = _categoria(seccion_id, "Vestidos", parent_id=ropa.id)
    largos = _categoria(seccion_id, "Largos", parent_id=vestidos.id)

    with (
        patch.object(CategoriaService, "get", new=AsyncMock(return_value=ropa)),
        patch.object(CategoriaRepository, "get_by_id", new=_by_id(ropa, vestidos, largos)),
    ):
        with pytest.raises(AppException) as error:
            await CategoriaService.update(
                _session(),
                ropa.id,
                CategoriaUpdate(parent_id=largos.id),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert "subcategorías" in error.value.details["parent_id"]


@pytest.mark.asyncio
async def test_update_mueve_dentro_del_arbol() -> None:
    seccion_id = uuid4()
    ropa = _categoria(seccion_id, "Ropa")
    zapatos = _categoria(seccion_id, "Zapatos")
    botas = _categoria(seccion_id, "Botas", parent_id=ropa.id)
    session = _session()

    with (
        patch.object(CategoriaService, "get", new=AsyncMock(return_value=botas)),
        patch.object(CategoriaRepository, "get_by_id", new=_by_id(ropa, zapatos, botas)),
    ):
        result = await CategoriaService.update(
            session,
            botas.id,
            CategoriaUpdate(parent_id=zapatos.id),
            uuid4(),
        )

    assert result.parent_id == zapatos.id
    assert result.slug == "botas"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_cambio_de_seccion_con_hijos_responde_409() -> None:
    categoria = _categoria(uuid4())

    with (
        patch.object(CategoriaService, "get", new=AsyncMock(return_value=categoria)),
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=_seccion("Hombre"))),
        patch.object(CategoriaRepository, "has_active_children", new=AsyncMock(return_value=True)),
    ):
        with pytest.raises(AppException) as error:
            await CategoriaService.update(
                _session(),
                categoria.id,
                CategoriaUpdate(seccion_id=uuid4()),
                uuid4(),
            )

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_update_cambio_de_seccion_con_productos_responde_409() -> None:
    categoria = _categoria(uuid4())
    seccion_original = categoria.seccion_id

    with (
        patch.object(CategoriaService, "get", new=AsyncMock(return_value=categoria)),
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=_seccion("Hombre"))),
        patch.object(CategoriaRepository, "has_active_children", new=AsyncMock(return_value=False)),
        patch.object(CategoriaRepository, "has_active_products", new=AsyncMock(return_value=True)),
    ):
        with pytest.raises(AppException) as error:
            await CategoriaService.update(
                _session(),
                categoria.id,
                CategoriaUpdate(seccion_id=uuid4()),
                uuid4(),
            )

    assert error.value.status_code == 409
    assert categoria.seccion_id == seccion_original


@pytest.mark.asyncio
async def test_update_cambio_de_seccion_revalida_slug_en_la_seccion_destino() -> None:
    categoria = _categoria(uuid4(), "Vestidos")
    destino = _seccion("Niñas")

    with (
        patch.object(CategoriaService, "get", new=AsyncMock(return_value=categoria)),
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=destino)),
        patch.object(CategoriaRepository, "has_active_children", new=AsyncMock(return_value=False)),
        patch.object(CategoriaRepository, "has_active_products", new=AsyncMock(return_value=False)),
        patch.object(
            CategoriaRepository,
            "get_active_by_slug",
            new=AsyncMock(return_value=None),
        ) as get_by_slug,
    ):
        result = await CategoriaService.update(
            _session(),
            categoria.id,
            CategoriaUpdate(seccion_id=destino.id),
            uuid4(),
        )

    get_by_slug.assert_awaited_once_with(destino.id, "vestidos", exclude_id=categoria.id)
    assert result.seccion_id == destino.id


@pytest.mark.asyncio
async def test_update_cambio_de_seccion_con_padre_de_la_seccion_anterior_responde_422() -> None:
    seccion_id = uuid4()
    ropa = _categoria(seccion_id, "Ropa")
    vestidos = _categoria(seccion_id, "Vestidos", parent_id=ropa.id)

    with (
        patch.object(CategoriaService, "get", new=AsyncMock(return_value=vestidos)),
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=_seccion("Niñas"))),
        patch.object(CategoriaRepository, "has_active_children", new=AsyncMock(return_value=False)),
        patch.object(CategoriaRepository, "has_active_products", new=AsyncMock(return_value=False)),
        patch.object(CategoriaRepository, "get_by_id", new=_by_id(ropa, vestidos)),
    ):
        with pytest.raises(AppException) as error:
            await CategoriaService.update(
                _session(),
                vestidos.id,
                CategoriaUpdate(seccion_id=uuid4()),
                uuid4(),
            )

    assert error.value.status_code == 422
    assert "parent_id" in error.value.details


@pytest.mark.asyncio
async def test_delete_rechaza_con_subcategorias() -> None:
    categoria = _categoria(uuid4())
    session = _session()

    with (
        patch.object(CategoriaService, "get", new=AsyncMock(return_value=categoria)),
        patch.object(CategoriaRepository, "has_active_children", new=AsyncMock(return_value=True)),
        patch.object(CategoriaProductoRepository, "soft_delete_by_categoria", new=AsyncMock()) as enlaces,
    ):
        with pytest.raises(AppException) as error:
            await CategoriaService.delete(session, categoria.id, uuid4())

    assert error.value.status_code == 409
    assert categoria.is_deleted is False
    enlaces.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_quita_sus_productos_sin_eliminarlos() -> None:
    categoria = _categoria(uuid4())
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(CategoriaService, "get", new=AsyncMock(return_value=categoria)),
        patch.object(CategoriaRepository, "has_active_children", new=AsyncMock(return_value=False)),
        patch.object(
            CategoriaProductoRepository,
            "soft_delete_by_categoria",
            new=AsyncMock(return_value=4),
        ) as enlaces,
    ):
        await CategoriaService.delete(session, categoria.id, actor_id)

    assert categoria.is_deleted is True
    assert categoria.deleted_by == actor_id
    enlaces.assert_awaited_once_with(categoria.id, actor_id, categoria.deleted_at)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_arbol_agrupa_por_seccion_e_incluye_secciones_vacias() -> None:
    mujer = _seccion("Mujer")
    hombre = _seccion("Hombre")
    ropa = _categoria(mujer.id, "Ropa")
    vestidos = _categoria(mujer.id, "Vestidos", parent_id=ropa.id)
    largos = _categoria(mujer.id, "Largos", parent_id=vestidos.id)
    zapatos = _categoria(mujer.id, "Zapatos")

    with (
        patch.object(SeccionRepository, "list_all", new=AsyncMock(return_value=[mujer, hombre])),
        patch.object(
            CategoriaRepository,
            "list_for_tree",
            new=AsyncMock(return_value=[ropa, vestidos, largos, zapatos]),
        ) as list_for_tree,
    ):
        arbol = await CategoriaService.arbol(_session())

    list_for_tree.assert_awaited_once_with(None)
    assert [item.seccion.nombre for item in arbol] == ["Mujer", "Hombre"]

    mujer_arbol = arbol[0].categorias
    assert mujer_arbol.total == 4
    assert [nodo.data.nombre for nodo in mujer_arbol.data] == ["Ropa", "Zapatos"]
    assert mujer_arbol.data[0].children[0].data.nombre == "Vestidos"
    assert mujer_arbol.data[0].children[0].children[0].data.nombre == "Largos"

    assert arbol[1].categorias.total == 0
    assert arbol[1].categorias.data == []


@pytest.mark.asyncio
async def test_arbol_con_seccion_inexistente_responde_404() -> None:
    with patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await CategoriaService.arbol(_session(), seccion_id=uuid4())

    assert error.value.status_code == 404
