from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.categoria_productos.services import CategoriaProductoService
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.services import ProductoColorService
from app.domains.productos.models import Producto
from app.domains.productos.repositories import ProductoRepository
from app.domains.productos.schemas import ProductoDetailCreate, ProductoUpdate
from app.domains.productos.services import ProductoService
from app.domains.secciones.models import Seccion
from app.domains.secciones.repositories import SeccionRepository
from app.shared.errors.exceptions import AppException


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
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
        patch.object(ProductoService, "get_detail", new=AsyncMock(side_effect=lambda *a, **k: add.call_args.args[0])),
    ):
        producto = await ProductoService.create(
            session,
            ProductoDetailCreate(seccion_id=seccion.id, nombre=" Camisa Oxford "),
            actor_id,
            MagicMock(),
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
                ProductoDetailCreate(seccion_id=uuid4(), nombre="Camisa"),
                uuid4(),
                MagicMock(),
            )

    assert error.value.status_code == 422
    assert "seccion_id" in error.value.details
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_aplica_cambios_y_null_explicito() -> None:
    producto = _producto()
    actor_id = uuid4()

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(ProductoService, "get_detail", new=AsyncMock(return_value=producto)) as detail,
    ):
        result = await ProductoService.update(
            _session(),
            producto.id,
            ProductoUpdate(nombre="Camisa Oxford slim", cuidados=None),
            actor_id,
            MagicMock(),
        )

    # Responde la ficha completa, igual que GET /productos/{id}.
    detail.assert_awaited_once_with(ANY, producto.id, ANY)
    assert result.nombre == "Camisa Oxford slim"
    assert result.cuidados is None
    assert result.updated_by == actor_id


@pytest.mark.asyncio
async def test_update_misma_seccion_no_toca_las_categorias() -> None:
    producto = _producto()

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(CategoriaProductoRepository, "soft_delete_by_producto", new=AsyncMock()) as quitar,
        patch.object(ProductoService, "get_detail", new=AsyncMock(return_value=producto)),
    ):
        await ProductoService.update(
            _session(),
            producto.id,
            ProductoUpdate(seccion_id=producto.seccion_id),
            uuid4(),
            MagicMock(),
        )

    quitar.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cambio_de_seccion_quita_las_categorias_en_la_misma_transaccion() -> None:
    producto = _producto()
    destino = uuid4()
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(
            SeccionRepository,
            "get_by_id",
            new=AsyncMock(return_value=Seccion(nombre="Mujer", slug="mujer")),
        ),
        patch.object(
            CategoriaProductoRepository, "soft_delete_by_producto", new=AsyncMock(return_value=3)
        ) as quitar,
        patch.object(ProductoService, "get_detail", new=AsyncMock(return_value=producto)),
    ):
        result = await ProductoService.update(
            session, producto.id, ProductoUpdate(seccion_id=destino), actor_id, MagicMock()
        )

    assert result.seccion_id == destino
    quitar.assert_awaited_once_with(producto.id, actor_id, result.updated_at)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_cambio_a_seccion_inexistente_no_quita_categorias() -> None:
    producto = _producto()
    seccion_original = producto.seccion_id

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=None)),
        patch.object(CategoriaProductoRepository, "soft_delete_by_producto", new=AsyncMock()) as quitar,
    ):
        with pytest.raises(AppException) as error:
            await ProductoService.update(
                _session(), producto.id, ProductoUpdate(seccion_id=uuid4()), uuid4(), MagicMock()
            )

    assert error.value.status_code == 422
    assert producto.seccion_id == seccion_original
    quitar.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_con_categorias_y_nueva_seccion_valida_contra_la_nueva() -> None:
    producto = _producto()
    destino = uuid4()
    categoria_ids = [uuid4(), uuid4()]
    actor_id = uuid4()
    session = _session()

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)) as get,
        patch.object(
            SeccionRepository,
            "get_by_id",
            new=AsyncMock(return_value=Seccion(nombre="Mujer", slug="mujer")),
        ),
        patch.object(
            CategoriaProductoService, "apply_categorias", new=AsyncMock(return_value=(2, 3))
        ) as aplicar,
        patch.object(CategoriaProductoRepository, "soft_delete_by_producto", new=AsyncMock()) as quitar,
        patch.object(ProductoService, "get_detail", new=AsyncMock(return_value=producto)),
    ):
        result = await ProductoService.update(
            session,
            producto.id,
            ProductoUpdate(seccion_id=destino, categoria_ids=categoria_ids),
            actor_id,
            MagicMock(),
        )

    assert get.await_args.kwargs["for_update"] is True
    aplicar.assert_awaited_once_with(session, producto.id, destino, categoria_ids, actor_id, ANY)
    quitar.assert_not_awaited()
    assert result.seccion_id == destino
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_solo_categorias_no_modifica_el_producto() -> None:
    producto = _producto()
    updated_at = producto.updated_at
    session = _session()

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(
            CategoriaProductoService, "apply_categorias", new=AsyncMock(return_value=(1, 0))
        ) as aplicar,
        patch.object(ProductoService, "get_detail", new=AsyncMock(return_value=producto)),
    ):
        await ProductoService.update(
            session, producto.id, ProductoUpdate(categoria_ids=[uuid4()]), uuid4(), MagicMock()
        )

    # Se validan contra la sección actual y solo cambian los enlaces.
    assert aplicar.await_args.args[2] == producto.seccion_id
    assert producto.updated_at == updated_at
    assert producto.updated_by is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_mismas_categorias_no_hace_commit() -> None:
    producto = _producto()
    session = _session()

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(CategoriaProductoService, "apply_categorias", new=AsyncMock(return_value=(0, 0))),
        patch.object(ProductoService, "get_detail", new=AsyncMock(return_value=producto)) as detail,
    ):
        await ProductoService.update(
            session, producto.id, ProductoUpdate(categoria_ids=[uuid4()]), uuid4(), MagicMock()
        )

    session.commit.assert_not_awaited()
    detail.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_categorias_invalidas_no_guarda_nada() -> None:
    producto = _producto()
    nombre_original = producto.nombre
    session = _session()
    invalidas = AppException("Categorías de otra sección que el producto.", 422)

    with (
        patch.object(ProductoService, "get", new=AsyncMock(return_value=producto)),
        patch.object(CategoriaProductoService, "apply_categorias", new=AsyncMock(side_effect=invalidas)),
    ):
        with pytest.raises(AppException) as error:
            await ProductoService.update(
                session,
                producto.id,
                ProductoUpdate(nombre="Otro nombre", categoria_ids=[uuid4()]),
                uuid4(),
                MagicMock(),
            )

    assert error.value.status_code == 422
    assert producto.nombre == nombre_original
    session.commit.assert_not_awaited()


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
        "find_many",
        new=AsyncMock(return_value=([], 0)),
    ) as repository_list:
        page = await ProductoService.list(_session(), MagicMock(), nombre="  oxford ")

    assert page.total == 0
    assert repository_list.await_args.kwargs["nombre"] == "oxford"


@pytest.mark.asyncio
async def test_get_inexistente_responde_404() -> None:
    with patch.object(ProductoRepository, "get_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await ProductoService.get(_session(), uuid4())

    assert error.value.status_code == 404


# --- Create en un solo paso -------------------------------------------------

from app.domains.categoria_productos.services import CategoriaProductoService  # noqa: E402
from app.domains.imagenes.repositories import ImagenRepository  # noqa: E402
from app.domains.skus.repositories import SkuRepository  # noqa: E402
from app.domains.skus.services import SkuService  # noqa: E402
from app.integrations.cloudinary import CloudinaryService  # noqa: E402


PENDIENTE = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/imagenes/{}.jpg"


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.CLOUDINARY_CLOUD_NAME = "demo"
    settings.CLOUDINARY_FOLDER_NAME = "pinodo"
    return settings


def _arbol(**overrides: object) -> ProductoDetailCreate:
    talla_s, talla_m = uuid4(), uuid4()
    return ProductoDetailCreate.model_validate(
        {
            "seccion_id": str(uuid4()),
            "nombre": "Camisa Oxford",
            "categoria_ids": [str(uuid4())],
            "colores": [
                {
                    "color_id": str(uuid4()),
                    "imagenes": [{"url": PENDIENTE.format("azul1"), "tipo": "MODELO"}],
                    "skus": [
                        {"talla_id": str(talla_s), "codigo_barras": "841", "precio": {"normal": 29.95}},
                        {"talla_id": str(talla_m), "precio": {"normal": 29.95}, "stock": {"cantidad": 4}},
                    ],
                },
                {
                    "color_id": str(uuid4()),
                    "skus": [{"talla_id": str(talla_s), "precio": {"normal": 31}}],
                },
            ],
            **overrides,
        }
    )


class _Arbol:
    """Parchea validaciones, repositories e integration del create en un solo paso."""

    def __enter__(self) -> "_Arbol":
        self.patches = {
            "seccion": patch.object(SeccionRepository, "get_by_id", new=AsyncMock(return_value=object())),
            "categorias": patch.object(CategoriaProductoService, "validate_categorias", new=AsyncMock()),
            "color": patch.object(ProductoColorService, "validate_color", new=AsyncMock()),
            "talla": patch.object(SkuService, "validate_talla", new=AsyncMock()),
            "codigo": patch.object(SkuService, "validate_unique_codigo_barras", new=AsyncMock()),
            "producto_add": patch.object(ProductoRepository, "add"),
            "link_add": patch.object(CategoriaProductoRepository, "add"),
            "color_add": patch.object(ProductoColorRepository, "add"),
            "imagen_add": patch.object(ImagenRepository, "add"),
            "sku_add": patch.object(SkuRepository, "add"),
            "confirm": patch.object(CloudinaryService, "confirm_pending_uploads", new=AsyncMock()),
            "url_libre": patch.object(ImagenRepository, "get_active_by_url", new=AsyncMock(return_value=None)),
            "get": patch.object(ProductoService, "get_detail", new=AsyncMock(return_value="detail")),
        }
        self.mocks = {name: p.start() for name, p in self.patches.items()}
        return self

    def __exit__(self, *_: object) -> None:
        for p in self.patches.values():
            p.stop()

    def added(self, name: str) -> list[object]:
        return [c.args[0] for c in self.mocks[name].call_args_list]


@pytest.mark.asyncio
async def test_create_arbol_crea_todo_enlazado_y_con_auditoria() -> None:
    session = _session()
    actor_id = uuid4()
    data = _arbol()

    with _Arbol() as arbol:
        result = await ProductoService.create(session, data, actor_id, _settings())

    [producto] = arbol.added("producto_add")
    [link] = arbol.added("link_add")
    colores = arbol.added("color_add")
    [imagen] = arbol.added("imagen_add")
    skus = arbol.added("sku_add")

    assert link.producto_id == producto.id and link.categoria_id == data.categoria_ids[0]
    assert [c.producto_id for c in colores] == [producto.id, producto.id]
    assert [c.color_id for c in colores] == [c.color_id for c in data.colores]
    assert imagen.producto_color_id == colores[0].id
    assert [s.producto_color_id for s in skus] == [colores[0].id, colores[0].id, colores[1].id]
    assert skus[0].precio == {"normal": 29.95, "rebajado": None, "rebaja_hasta": None}
    assert skus[1].stock["cantidad"] == 4 and skus[1].stock["actualizado"] is not None
    for registro in [producto, link, *colores, imagen, *skus]:
        assert registro.created_by == actor_id and registro.updated_by == actor_id

    session.commit.assert_awaited_once()
    # La foto se mueve a la carpeta de su producto y del color al que pertenece.
    destino = f"productos/{producto.id}/{colores[0].id}"
    assert arbol.mocks["confirm"].await_args.args[0] == {PENDIENTE.format("azul1"): destino}
    arbol.mocks["get"].assert_awaited_once_with(session, producto.id, ANY)
    assert result == "detail"


@pytest.mark.asyncio
async def test_create_arbol_valida_cada_talla_una_sola_vez() -> None:
    with _Arbol() as arbol:
        await ProductoService.create(_session(), _arbol(), uuid4(), _settings())

    assert arbol.mocks["talla"].await_count == 2  # S se repite en dos colores
    assert arbol.mocks["codigo"].await_count == 1


@pytest.mark.asyncio
async def test_create_arbol_rechaza_imagen_que_no_es_pendiente_sin_guardar_nada() -> None:
    session = _session()
    data = _arbol()
    data.colores[0].imagenes[0].url = "https://res.cloudinary.com/otra/image/upload/v1/x/pendientes/a.jpg"

    with _Arbol() as arbol:
        with pytest.raises(AppException) as error:
            await ProductoService.create(session, data, uuid4(), _settings())

    assert error.value.status_code == 422
    assert list(error.value.details) == ["colores -> 0 -> imagenes -> 0 -> url"]
    arbol.mocks["producto_add"].assert_not_called()
    session.commit.assert_not_awaited()
    arbol.mocks["confirm"].assert_not_awaited()


@pytest.mark.asyncio
async def test_create_arbol_indica_la_ruta_del_error_del_hijo() -> None:
    session = _session()
    error_talla = AppException("La talla no existe.", 422, details={"talla_id": "La talla no existe."})

    with _Arbol() as arbol:
        arbol.mocks["talla"].side_effect = [None, error_talla]
        with pytest.raises(AppException) as error:
            await ProductoService.create(session, _arbol(), uuid4(), _settings())

    assert error.value.details == {"colores -> 0 -> skus -> 1 -> talla_id": "La talla no existe."}
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_arbol_no_confirma_imagenes_si_falla_el_commit() -> None:
    session = _session()
    session.commit = AsyncMock(side_effect=RuntimeError("db caída"))

    with _Arbol() as arbol:
        with pytest.raises(RuntimeError):
            await ProductoService.create(session, _arbol(), uuid4(), _settings())

    arbol.mocks["confirm"].assert_not_awaited()


# --- Resumen del listado ------------------------------------------------------


@pytest.mark.asyncio
async def test_resumen_agrega_precios_vigentes_stock_colores_y_portada() -> None:
    con_skus, sin_hijos = uuid4(), uuid4()
    rows = (
        [(con_skus, "Azul", "#1E3A8A"), (con_skus, "Blanco", "#FFFFFF")],
        [
            (con_skus, {"normal": 30, "rebajado": 20, "rebaja_hasta": None}, {"cantidad": 4}),
            (con_skus, {"normal": 35, "rebajado": None, "rebaja_hasta": None}, {"cantidad": 6}),
        ],
        [(con_skus, "https://res.cloudinary.com/demo/image/upload/a.jpg")],
    )

    with patch.object(ProductoRepository, "list_resumen_rows", new=AsyncMock(return_value=rows)):
        resumenes = await ProductoService._resumenes(
            _session(), [con_skus, sin_hijos], MagicMock(TIMEZONE_OFFSET_HOURS=-4)
        )

    resumen = resumenes[con_skus]
    assert (float(resumen.precio_desde), float(resumen.precio_hasta)) == (20.0, 35.0)
    assert resumen.stock_total == 10
    assert [c.nombre for c in resumen.colores] == ["Azul", "Blanco"]
    assert resumen.portada_url.endswith("a.jpg")
    vacio = resumenes[sin_hijos]
    assert (vacio.portada_url, vacio.precio_desde, vacio.stock_total, vacio.colores) == (
        None, None, 0, [],
    )
