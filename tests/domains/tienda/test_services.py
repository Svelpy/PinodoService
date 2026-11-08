from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.domains.categorias.models import Categoria
from app.domains.categorias.schemas import CategoriaArbolSeccion, CategoriaResponse
from app.domains.categorias.services import CategoriaService
from app.domains.colores.models import Color
from app.domains.config.models import Config
from app.domains.config.services import ConfigService
from app.domains.imagenes.models import Imagen
from app.domains.producto_colores.models import ProductoColor
from app.domains.productos.models import Producto
from app.domains.secciones.models import Seccion
from app.domains.secciones.schemas import SeccionResponse
from app.domains.skus.models import Sku
from app.domains.skus.services import SkuService
from app.domains.tallas.models import Talla
from app.domains.tienda.repositories import TiendaRepository
from app.domains.tienda.services import TiendaService
from app.shared.enums import OrdenTienda, TipoImagen
from app.shared.errors.exceptions import AppException
from app.shared.schemas.tree import TreeNodeResponse, TreeResponse


HOY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def _precio(normal: float, rebajado: float | None = None, hasta: str | None = None) -> dict[str, object]:
    return {"normal": normal, "rebajado": rebajado, "rebaja_hasta": hasta}


def _stock(cantidad: int) -> dict[str, object]:
    return {"cantidad": cantidad, "minimo": 0, "actualizado": None}


def _categoria(
    seccion_id: UUID,
    nombre: str,
    slug: str,
    children: list[TreeNodeResponse[CategoriaResponse]] | None = None,
) -> TreeNodeResponse[CategoriaResponse]:
    return TreeNodeResponse[CategoriaResponse](
        data=CategoriaResponse(
            id=uuid4(),
            seccion_id=seccion_id,
            parent_id=None,
            nombre=nombre,
            slug=slug,
            is_visible=True,
            created_at=NOW,
            updated_at=NOW,
        ),
        children=children or [],
    )


def _arbol() -> tuple[list[CategoriaArbolSeccion], UUID, TreeNodeResponse[CategoriaResponse]]:
    """Mujer > Vestidos > Vestidos midi, ya filtrado por visibilidad."""
    seccion_id = uuid4()
    midi = _categoria(seccion_id, "Vestidos midi", "vestidos-midi")
    vestidos = _categoria(seccion_id, "Vestidos", "vestidos", [midi])
    arbol = [
        CategoriaArbolSeccion(
            seccion=SeccionResponse(
                id=seccion_id,
                nombre="Mujer",
                slug="mujer",
                is_visible=True,
                created_at=NOW,
                updated_at=NOW,
            ),
            categorias=TreeResponse[CategoriaResponse](total=2, data=[vestidos]),
        )
    ]
    return arbol, seccion_id, vestidos


@pytest.mark.asyncio
async def test_verificar_abierta_responde_503_en_mantenimiento() -> None:
    config = Config(nombre_tienda="Tienda", en_mantenimiento=True)

    with patch.object(ConfigService, "get", new=AsyncMock(return_value=config)):
        with pytest.raises(AppException) as error:
            await TiendaService.verificar_abierta(MagicMock())

    assert error.value.status_code == 503
    assert error.value.code == "MAINTENANCE"


@pytest.mark.asyncio
async def test_navegacion_slug_con_seccion_y_categoria() -> None:
    arbol, _, _ = _arbol()

    with patch.object(CategoriaService, "arbol", new=AsyncMock(return_value=arbol)) as service:
        secciones = await TiendaService.navegacion(MagicMock())

    service.assert_awaited_once()
    assert service.await_args.kwargs["is_visible"] is True
    vestidos = secciones[0].categorias.data[0]
    assert secciones[0].categorias.total == 2
    assert vestidos.data.slug == "mujer-vestidos"
    assert vestidos.children[0].data.slug == "mujer-vestidos-midi"


@pytest.mark.asyncio
async def test_listar_por_categoria_incluye_subcategorias_visibles() -> None:
    arbol, _, vestidos = _arbol()

    with (
        patch.object(CategoriaService, "arbol", new=AsyncMock(return_value=arbol)),
        patch.object(SkuService, "local_today", return_value=HOY),
        patch.object(TiendaRepository, "find_productos", new=AsyncMock(return_value=([], 0))) as find,
        patch.object(TiendaRepository, "list_resumen_rows", new=AsyncMock(return_value=([], [], []))),
    ):
        await TiendaService.listar_productos(MagicMock(), MagicMock(), categoria_id=vestidos.data.id)

    assert find.await_args.kwargs["categoria_ids"] == [
        vestidos.data.id,
        vestidos.children[0].data.id,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["seccion_id", "categoria_id"])
async def test_listar_seccion_o_categoria_no_visible_404(campo: str) -> None:
    arbol, _, _ = _arbol()

    with (
        patch.object(CategoriaService, "arbol", new=AsyncMock(return_value=arbol)),
        patch.object(TiendaRepository, "find_productos", new=AsyncMock()) as find,
    ):
        with pytest.raises(AppException) as error:
            await TiendaService.listar_productos(MagicMock(), MagicMock(), **{campo: uuid4()})

    assert error.value.status_code == 404
    find.assert_not_awaited()


@pytest.mark.asyncio
async def test_listar_rechaza_precio_min_mayor_que_max() -> None:
    with patch.object(TiendaRepository, "find_productos", new=AsyncMock()) as find:
        with pytest.raises(AppException) as error:
            await TiendaService.listar_productos(
                MagicMock(),
                MagicMock(),
                precio_min=Decimal("50"),
                precio_max=Decimal("10"),
            )

    assert error.value.status_code == 422
    assert "precio_min" in error.value.details
    find.assert_not_awaited()


@pytest.mark.asyncio
async def test_listar_arma_tarjeta_con_precios_vigentes_y_agotado() -> None:
    producto = Producto(id=uuid4(), seccion_id=uuid4(), nombre="Vestido Ágil")
    negro_id = uuid4()
    rows = (
        [(producto.id, negro_id, "Negro", "#000000")],
        [
            (producto.id, _precio(50, 40, "2026-11-07"), _stock(0)),  # rebaja vencida
            (producto.id, _precio(80, 60), _stock(0)),  # rebaja sin fecha de fin
        ],
        [(producto.id, "https://x/portada.jpg")],
    )

    with (
        patch.object(SkuService, "local_today", return_value=HOY),
        patch.object(TiendaRepository, "find_productos", new=AsyncMock(return_value=([producto], 1))) as find,
        patch.object(TiendaRepository, "list_resumen_rows", new=AsyncMock(return_value=rows)),
    ):
        page = await TiendaService.listar_productos(
            MagicMock(),
            MagicMock(),
            orden=OrdenTienda.PRECIO_ASC,
            q="  vestido ",
        )

    assert find.await_args.kwargs["q"] == "vestido"
    assert find.await_args.kwargs["today"] == HOY
    card = page.data[0]
    assert card.slug == "vestido-agil"
    assert (card.precio_desde, card.precio_hasta) == (Decimal("50"), Decimal("60"))
    assert (card.precio_normal_desde, card.precio_normal_hasta) == (Decimal("50"), Decimal("80"))
    assert card.en_rebaja is True
    assert card.agotado is True
    assert card.portada_url == "https://x/portada.jpg"
    assert [color.id for color in card.colores] == [negro_id]


def _producto_con_colores() -> tuple[Producto, ProductoColor, ProductoColor]:
    seccion = Seccion(id=uuid4(), nombre="Mujer", slug="mujer")
    producto = Producto(id=uuid4(), seccion_id=seccion.id, nombre="Vestido")
    producto.seccion = seccion
    producto.categorias = []
    talla = Talla(id=uuid4(), etiqueta="M")

    con_tallas = ProductoColor(id=uuid4(), producto_id=producto.id, color_id=uuid4())
    con_tallas.color = Color(id=con_tallas.color_id, nombre="Negro", slug="negro", codigo_hex="#000000")
    con_tallas.imagenes = [Imagen(producto_color_id=con_tallas.id, url="https://x/1.jpg", tipo=TipoImagen.MODELO)]
    sku = Sku(
        id=uuid4(),
        producto_color_id=con_tallas.id,
        talla_id=talla.id,
        precio=_precio(30, 20, "2026-12-31"),
        stock=_stock(2),
    )
    sku.talla = talla
    con_tallas.skus = [sku]

    sin_tallas = ProductoColor(id=uuid4(), producto_id=producto.id, color_id=uuid4())
    sin_tallas.color = Color(id=sin_tallas.color_id, nombre="Rojo", slug="rojo", codigo_hex="#FF0000")
    sin_tallas.imagenes = []
    sin_tallas.skus = []

    producto.colores = [sin_tallas, con_tallas]
    return producto, con_tallas, sin_tallas


@pytest.mark.asyncio
async def test_ficha_descarta_colores_sin_tallas_y_categorias_ocultas() -> None:
    producto, con_tallas, _ = _producto_con_colores()
    arbol, seccion_id, vestidos = _arbol()
    producto.seccion_id = seccion_id
    visible = Categoria(id=vestidos.data.id, seccion_id=seccion_id, nombre="Vestidos", slug="vestidos")
    oculta = Categoria(id=uuid4(), seccion_id=seccion_id, nombre="Oculta", slug="oculta")
    producto.categorias = [oculta, visible]

    with (
        patch.object(SkuService, "local_today", return_value=HOY),
        patch.object(TiendaRepository, "get_producto", new=AsyncMock(return_value=producto)),
        patch.object(CategoriaService, "arbol", new=AsyncMock(return_value=arbol)) as service,
    ):
        ficha = await TiendaService.get_producto(MagicMock(), MagicMock(), producto.id)

    assert service.await_args.kwargs["seccion_id"] == seccion_id
    assert [color.id for color in ficha.colores] == [con_tallas.id]
    sku = ficha.colores[0].skus[0]
    assert (sku.precio_vigente, sku.en_rebaja, sku.rebaja_hasta) == (Decimal("20"), True, date(2026, 12, 31))
    assert sku.disponible is True
    assert ficha.agotado is False
    assert [(categoria.id, categoria.slug) for categoria in ficha.categorias] == [
        (visible.id, "mujer-vestidos")
    ]


@pytest.mark.asyncio
async def test_ficha_sin_ningun_color_con_tallas_404() -> None:
    producto, con_tallas, _ = _producto_con_colores()
    con_tallas.skus = []

    with (
        patch.object(SkuService, "local_today", return_value=HOY),
        patch.object(TiendaRepository, "get_producto", new=AsyncMock(return_value=producto)),
    ):
        with pytest.raises(AppException) as error:
            await TiendaService.get_producto(MagicMock(), MagicMock(), producto.id)

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_ficha_inexistente_o_no_visible_404() -> None:
    with patch.object(TiendaRepository, "get_producto", new=AsyncMock(return_value=None)):
        with pytest.raises(AppException) as error:
            await TiendaService.get_producto(MagicMock(), MagicMock(), uuid4())

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_filtros_convierte_filas() -> None:
    color_id, talla_id = uuid4(), uuid4()
    rows = (
        [(color_id, "Negro", "#000000")],
        [(talla_id, "M")],
        (Decimal("10"), Decimal("90"), True),
    )

    with (
        patch.object(SkuService, "local_today", return_value=HOY),
        patch.object(TiendaRepository, "get_filtros", new=AsyncMock(return_value=rows)) as get,
    ):
        filtros = await TiendaService.filtros(MagicMock(), MagicMock(), q=" camisa ")

    assert get.await_args.kwargs == {"today": HOY, "seccion_id": None, "categoria_ids": None, "q": "camisa"}
    assert [color.id for color in filtros.colores] == [color_id]
    assert [talla.id for talla in filtros.tallas] == [talla_id]
    assert (filtros.precio_min, filtros.precio_max, filtros.hay_rebajas) == (Decimal("10"), Decimal("90"), True)
