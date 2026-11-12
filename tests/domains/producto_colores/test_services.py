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
        patch.object(
            ProductoColorService,
            "get",
            new=AsyncMock(side_effect=lambda *a, **k: add.call_args.args[0]),
        ) as get,
    ):
        producto_color = await ProductoColorService.create(
            session,
            ProductoColorCreate(producto_id=producto.id, color_id=color.id),
            actor_id,
            MagicMock(),
        )

    get.assert_awaited_once_with(session, producto_color.id, load_detail=True)

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
        patch.object(
            ProductoColorRepository,
            "get_active_by_producto_and_color",
            new=AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(AppException) as error:
            await ProductoColorService.create(
                _session(),
                ProductoColorCreate(producto_id=uuid4(), color_id=uuid4()),
                uuid4(),
                MagicMock(),
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
                MagicMock(),
            )

    assert error.value.status_code == 409
    assert "color_id" in error.value.details
    session.commit.assert_not_awaited()




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


# --- Create con imágenes y SKUs ---------------------------------------------

from app.domains.skus.services import SkuService  # noqa: E402
from app.integrations.cloudinary import CloudinaryService  # noqa: E402

PENDIENTE = "https://res.cloudinary.com/demo/image/upload/v1/pinodo/imagenes/{}.jpg"


def _settings() -> MagicMock:
    return MagicMock(CLOUDINARY_CLOUD_NAME="demo", CLOUDINARY_FOLDER_NAME="pinodo")


def _arbol(**overrides: object) -> ProductoColorCreate:
    return ProductoColorCreate.model_validate(
        {
            "producto_id": str(uuid4()),
            "color_id": str(uuid4()),
            "imagenes": [{"url": PENDIENTE.format("rojo1"), "tipo": "MODELO"}],
            "skus": [
                {"talla_id": str(uuid4()), "codigo_barras": "841", "precio": {"normal": 29.95}},
                {"talla_id": str(uuid4()), "precio": {"normal": 29.95}, "stock": {"cantidad": 4}},
            ],
            **overrides,
        }
    )


class _Arbol:
    def __enter__(self) -> "_Arbol":
        self.patches = {
            "producto": patch.object(ProductoRepository, "get_by_id", new=AsyncMock(return_value=_producto())),
            "unico": patch.object(ProductoColorRepository, "get_active_by_producto_and_color", new=AsyncMock(return_value=None)),
            "color": patch.object(ProductoColorService, "validate_color", new=AsyncMock()),
            "talla": patch.object(SkuService, "validate_talla", new=AsyncMock()),
            "codigo": patch.object(SkuService, "validate_unique_codigo_barras", new=AsyncMock()),
            "color_add": patch.object(ProductoColorRepository, "add"),
            "imagen_add": patch.object(ImagenRepository, "add"),
            "sku_add": patch.object(SkuRepository, "add"),
            "confirm": patch.object(CloudinaryService, "confirm_pending_uploads", new=AsyncMock()),
            "url_libre": patch.object(ImagenRepository, "get_active_by_url", new=AsyncMock(return_value=None)),
            "get": patch.object(ProductoColorService, "get", new=AsyncMock(return_value="detail")),
        }
        self.mocks = {name: p.start() for name, p in self.patches.items()}
        return self

    def __exit__(self, *_: object) -> None:
        for p in self.patches.values():
            p.stop()

    def added(self, name: str) -> list[object]:
        return [c.args[0] for c in self.mocks[name].call_args_list]


@pytest.mark.asyncio
async def test_create_con_hijos_los_enlaza_al_color_en_una_transaccion() -> None:
    session = _session()
    actor_id = uuid4()
    data = _arbol()

    with _Arbol() as arbol:
        result = await ProductoColorService.create(session, data, actor_id, _settings())

    [color] = arbol.added("color_add")
    [imagen] = arbol.added("imagen_add")
    skus = arbol.added("sku_add")
    assert color.producto_id == data.producto_id
    assert imagen.producto_color_id == color.id
    assert [s.producto_color_id for s in skus] == [color.id, color.id]
    assert skus[1].stock["cantidad"] == 4
    for registro in [color, imagen, *skus]:
        assert registro.created_by == actor_id
    session.commit.assert_awaited_once()
    # La foto se mueve a la carpeta de su producto y color.
    destino = f"productos/{data.producto_id}/{color.id}"
    assert arbol.mocks["confirm"].await_args.args[0] == {PENDIENTE.format("rojo1"): destino}
    assert result == "detail"


@pytest.mark.asyncio
async def test_create_color_repetido_responde_409_sin_validar_los_hijos() -> None:
    with _Arbol() as arbol:
        arbol.mocks["unico"].return_value = _producto_color()
        with pytest.raises(AppException) as error:
            await ProductoColorService.create(_session(), _arbol(), uuid4(), _settings())

    assert error.value.status_code == 409
    arbol.mocks["talla"].assert_not_awaited()
    arbol.mocks["color_add"].assert_not_called()


@pytest.mark.asyncio
async def test_create_indica_la_ruta_del_error_sin_prefijo() -> None:
    session = _session()
    error_talla = AppException("La talla no existe.", 422, details={"talla_id": "La talla no existe."})

    with _Arbol() as arbol:
        arbol.mocks["talla"].side_effect = [None, error_talla]
        with pytest.raises(AppException) as error:
            await ProductoColorService.create(session, _arbol(), uuid4(), _settings())

    assert error.value.details == {"skus -> 1 -> talla_id": "La talla no existe."}
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rechaza_imagen_que_no_es_pendiente() -> None:
    data = _arbol()
    data.imagenes[0].url = "https://res.cloudinary.com/otra/image/upload/v1/x/pendientes/a.jpg"

    with _Arbol() as arbol:
        with pytest.raises(AppException) as error:
            await ProductoColorService.create(_session(), data, uuid4(), _settings())

    assert list(error.value.details) == ["imagenes -> 0 -> url"]
    arbol.mocks["color_add"].assert_not_called()


# --- PATCH con imágenes y SKUs ----------------------------------------------

from app.domains.imagenes.models import Imagen  # noqa: E402
from app.domains.skus.models import Sku  # noqa: E402
from app.shared.enums import TipoImagen  # noqa: E402

PRECIO = {"normal": 29.95, "rebajado": None, "rebaja_hasta": None}


def _sku(producto_color: ProductoColor, codigo: str | None = None) -> Sku:
    return Sku(
        producto_color_id=producto_color.id,
        talla_id=uuid4(),
        codigo_barras=codigo,
        precio=dict(PRECIO),
        stock={"cantidad": 7, "minimo": 1, "actualizado": None},
    )


def _imagen(producto_color: ProductoColor, nombre: str, tipo: TipoImagen = TipoImagen.MODELO) -> Imagen:
    return Imagen(producto_color_id=producto_color.id, url=PENDIENTE.format(nombre), tipo=tipo)


def _fila(sku: Sku, **cambios: object) -> dict[str, object]:
    return {"id": str(sku.id), "talla_id": str(sku.talla_id), "precio": dict(PRECIO), **cambios}


class _Patch:
    """Color con sus imágenes y SKUs actuales, y los repositories simulados."""

    def __init__(
        self,
        producto_color: ProductoColor,
        imagenes: list[Imagen] | None = None,
        skus: list[Sku] | None = None,
    ) -> None:
        self.producto_color = producto_color
        self.imagenes = imagenes or []
        self.skus = skus or []

    def __enter__(self) -> "_Patch":
        def get(*_: object, load_detail: bool = False, **__: object) -> object:
            return "detail" if load_detail else self.producto_color

        def borrar(ids: list[object], *_: object) -> int:
            return len(ids)

        self.patches = {
            "get": patch.object(ProductoColorService, "get", new=AsyncMock(side_effect=get)),
            "imagenes": patch.object(
                ImagenRepository, "list_active_by_producto_color", new=AsyncMock(return_value=self.imagenes)
            ),
            "imagenes_borrar": patch.object(ImagenRepository, "soft_delete_by_ids", new=AsyncMock(side_effect=borrar)),
            "imagen_add": patch.object(ImagenRepository, "add"),
            "url_libre": patch.object(ImagenRepository, "get_active_by_url", new=AsyncMock(return_value=None)),
            "skus": patch.object(
                SkuRepository, "list_active_by_producto_color", new=AsyncMock(return_value=self.skus)
            ),
            "skus_borrar": patch.object(SkuRepository, "soft_delete_by_ids", new=AsyncMock(side_effect=borrar)),
            "sku_add": patch.object(SkuRepository, "add"),
            "codigo": patch.object(SkuRepository, "get_active_by_codigo_barras", new=AsyncMock(return_value=None)),
            "talla": patch.object(SkuService, "validate_talla", new=AsyncMock()),
            "confirm": patch.object(CloudinaryService, "confirm_pending_uploads", new=AsyncMock()),
        }
        self.mocks = {name: p.start() for name, p in self.patches.items()}
        return self

    def __exit__(self, *_: object) -> None:
        for p in self.patches.values():
            p.stop()

    def added(self, name: str) -> list[object]:
        return [c.args[0] for c in self.mocks[name].call_args_list]


async def _update(
    session: MagicMock, contexto: _Patch, body: dict[str, object], actor_id: object = None
) -> object:
    return await ProductoColorService.update(
        session,
        contexto.producto_color.id,
        ProductoColorUpdate.model_validate(body),
        actor_id or uuid4(),
        _settings(),
    )


@pytest.mark.asyncio
async def test_patch_corrige_el_color_sin_tocar_sus_hijos() -> None:
    session = _session()
    actor_id = uuid4()
    producto_color = _producto_color()
    nuevo = uuid4()

    with (
        _Patch(producto_color) as contexto,
        patch.object(ColorRepository, "get_by_id", new=AsyncMock(return_value=_color())),
        patch.object(
            ProductoColorRepository,
            "get_active_by_producto_and_color",
            new=AsyncMock(return_value=None),
        ) as unico,
    ):
        await _update(session, contexto, {"color_id": str(nuevo)}, actor_id)

    assert producto_color.color_id == nuevo
    assert producto_color.updated_by == actor_id
    unico.assert_awaited_once_with(producto_color.producto_id, nuevo, exclude_id=producto_color.id)
    contexto.mocks["imagenes"].assert_not_awaited()
    contexto.mocks["skus"].assert_not_awaited()
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("color_existe", "repetido", "status_code"),
    [(False, False, 422), (True, True, 409)],
)
@pytest.mark.asyncio
async def test_patch_rechaza_color_inexistente_o_repetido_sin_tocar_nada(
    color_existe: bool,
    repetido: bool,
    status_code: int,
) -> None:
    session = _session()
    producto_color = _producto_color()
    color_anterior = producto_color.color_id

    with (
        _Patch(producto_color) as contexto,
        patch.object(
            ColorRepository, "get_by_id", new=AsyncMock(return_value=_color() if color_existe else None)
        ),
        patch.object(
            ProductoColorRepository,
            "get_active_by_producto_and_color",
            new=AsyncMock(return_value=_producto_color() if repetido else None),
        ),
        pytest.raises(AppException) as error,
    ):
        await _update(session, contexto, {"color_id": str(uuid4()), "is_visible": False})

    assert error.value.status_code == status_code
    assert "color_id" in error.value.details
    assert producto_color.color_id == color_anterior
    assert producto_color.is_visible is True
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_con_el_mismo_color_cambia_la_visibilidad() -> None:
    session = _session()
    actor_id = uuid4()
    producto_color = _producto_color()

    with _Patch(producto_color) as contexto:
        result = await _update(
            session, contexto, {"color_id": str(producto_color.color_id), "is_visible": False}, actor_id
        )

    assert result == "detail"
    assert producto_color.is_visible is False
    assert producto_color.updated_by == actor_id
    session.commit.assert_awaited_once()
    # Sin imagenes ni skus no se leen ni se bloquean sus hijos.
    contexto.mocks["imagenes"].assert_not_awaited()
    contexto.mocks["skus"].assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_sin_cambios_no_hace_commit() -> None:
    session = _session()
    producto_color = _producto_color()
    sku = _sku(producto_color, "841")

    with _Patch(producto_color, [_imagen(producto_color, "a")], [sku]) as contexto:
        result = await _update(
            session,
            contexto,
            {
                "is_visible": True,
                "imagenes": [{"url": PENDIENTE.format("a"), "tipo": "MODELO"}],
                "skus": [_fila(sku, codigo_barras="841")],
            },
        )

    assert result == "detail"
    session.commit.assert_not_awaited()
    assert sku.updated_by is None


@pytest.mark.asyncio
async def test_patch_reemplaza_la_galeria_por_url() -> None:
    session = _session()
    actor_id = uuid4()
    producto_color = _producto_color()
    sigue = _imagen(producto_color, "sigue")
    cambia = _imagen(producto_color, "cambia")
    sale = _imagen(producto_color, "sale")

    with _Patch(producto_color, [sigue, cambia, sale]) as contexto:
        await _update(
            session,
            contexto,
            {
                "imagenes": [
                    {"url": sigue.url, "tipo": "MODELO"},
                    {"url": cambia.url, "tipo": "DETALLE"},
                    {"url": PENDIENTE.format("nueva1"), "tipo": "PRENDA"},
                    {"url": PENDIENTE.format("nueva2"), "tipo": "PRENDA"},
                ]
            },
            actor_id,
        )

    assert sigue.updated_by is None
    assert cambia.tipo == TipoImagen.DETALLE and cambia.updated_by == actor_id
    contexto.mocks["imagenes_borrar"].assert_awaited_once()
    assert contexto.mocks["imagenes_borrar"].await_args.args[0] == [sale.id]
    nuevas = contexto.added("imagen_add")
    assert [i.url for i in nuevas] == [PENDIENTE.format("nueva1"), PENDIENTE.format("nueva2")]
    # Conservan el orden enviado aunque el reloj repita el mismo instante.
    assert nuevas[0].created_at < nuevas[1].created_at
    # Solo las nuevas se validan como subidas pendientes y se confirman.
    assert contexto.mocks["url_libre"].await_count == 2
    destino = f"productos/{producto_color.producto_id}/{producto_color.id}"
    assert contexto.mocks["confirm"].await_args.args[0] == {
        PENDIENTE.format("nueva1"): destino,
        PENDIENTE.format("nueva2"): destino,
    }
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_edita_crea_y_elimina_skus() -> None:
    session = _session()
    actor_id = uuid4()
    producto_color = _producto_color()
    editado = _sku(producto_color, "841")
    intacto = _sku(producto_color)
    eliminado = _sku(producto_color)
    talla_nueva = uuid4()

    with _Patch(producto_color, skus=[editado, intacto, eliminado]) as contexto:
        await _update(
            session,
            contexto,
            {
                "skus": [
                    _fila(editado, precio={"normal": 35}, is_visible=False, stock={"minimo": 4}),
                    {"talla_id": str(talla_nueva), "precio": {"normal": 20}, "stock": {"cantidad": 5}},
                ],
                "sku_ids_eliminar": [str(eliminado.id)],
            },
            actor_id,
        )

    # El SKU editado cambia solo lo enviado: el código omitido se conserva y,
    # del stock, solo cambia el mínimo.
    assert editado.precio["normal"] == 35.0
    assert editado.is_visible is False
    assert editado.codigo_barras == "841"
    assert (editado.stock["cantidad"], editado.stock["minimo"]) == (7, 4)
    assert editado.stock["actualizado"] is not None
    assert editado.updated_by == actor_id
    # Un SKU que no se envía no cambia.
    assert intacto.updated_by is None
    contexto.mocks["skus_borrar"].assert_awaited_once()
    assert contexto.mocks["skus_borrar"].await_args.args[0] == [eliminado.id]
    [nuevo] = contexto.added("sku_add")
    assert (nuevo.producto_color_id, nuevo.talla_id) == (producto_color.id, talla_nueva)
    assert nuevo.stock["cantidad"] == 5 and nuevo.created_by == actor_id
    # Los SKUs se bloquean para no chocar con las ventas.
    assert contexto.mocks["skus"].await_args.kwargs == {"for_update": True}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_libera_la_talla_y_el_codigo_de_un_sku_eliminado() -> None:
    session = _session()
    producto_color = _producto_color()
    viejo = _sku(producto_color, "841")

    with _Patch(producto_color, skus=[viejo]) as contexto:
        contexto.mocks["codigo"].return_value = viejo  # aún activo hasta aplicar el borrado
        await _update(
            session,
            contexto,
            {
                "skus": [{"talla_id": str(viejo.talla_id), "codigo_barras": "841", "precio": {"normal": 20}}],
                "sku_ids_eliminar": [str(viejo.id)],
            },
        )

    [nuevo] = contexto.added("sku_add")
    assert (nuevo.talla_id, nuevo.codigo_barras) == (viejo.talla_id, "841")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_rechaza_sku_de_otro_color() -> None:
    session = _session()
    producto_color = _producto_color()
    ajeno = _sku(_producto_color())

    with _Patch(producto_color, skus=[_sku(producto_color)]) as contexto, pytest.raises(AppException) as error:
        await _update(session, contexto, {"skus": [_fila(ajeno)]})

    assert error.value.status_code == 422
    assert list(error.value.details) == ["skus -> 0 -> id"]
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_rechaza_eliminar_sku_de_otro_color() -> None:
    session = _session()
    producto_color = _producto_color()
    ajeno = uuid4()

    with _Patch(producto_color, skus=[_sku(producto_color)]) as contexto, pytest.raises(AppException) as error:
        await _update(session, contexto, {"sku_ids_eliminar": [str(ajeno)]})

    assert error.value.status_code == 422
    assert str(ajeno) in error.value.details["sku_ids_eliminar"]
    contexto.mocks["skus_borrar"].assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_rechaza_talla_de_otro_sku_que_se_conserva() -> None:
    session = _session()
    producto_color = _producto_color()
    s, m = _sku(producto_color), _sku(producto_color)

    with _Patch(producto_color, skus=[s, m]) as contexto, pytest.raises(AppException) as error:
        await _update(session, contexto, {"skus": [_fila(s, talla_id=str(m.talla_id))]})

    assert error.value.status_code == 409
    assert list(error.value.details) == ["skus -> 0 -> talla_id"]
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_rechaza_intercambiar_tallas_en_una_peticion() -> None:
    session = _session()
    producto_color = _producto_color()
    s, m = _sku(producto_color), _sku(producto_color)

    with _Patch(producto_color, skus=[s, m]) as contexto, pytest.raises(AppException) as error:
        await _update(
            session,
            contexto,
            {"skus": [_fila(s, talla_id=str(m.talla_id)), _fila(m, talla_id=str(s.talla_id))]},
        )

    assert error.value.status_code == 422
    assert "dos guardados" in error.value.details["skus -> 0 -> talla_id"]


@pytest.mark.asyncio
async def test_patch_rechaza_codigo_de_barras_de_otro_color() -> None:
    session = _session()
    producto_color = _producto_color()

    with _Patch(producto_color) as contexto, pytest.raises(AppException) as error:
        contexto.mocks["codigo"].return_value = _sku(_producto_color(), "999")
        await _update(
            session,
            contexto,
            {"skus": [{"talla_id": str(uuid4()), "codigo_barras": "999", "precio": {"normal": 20}}]},
        )

    assert error.value.status_code == 409
    assert list(error.value.details) == ["skus -> 0 -> codigo_barras"]
    contexto.mocks["sku_add"].assert_not_called()


@pytest.mark.asyncio
async def test_patch_rechaza_rebaja_vencida_en_un_sku_existente() -> None:
    session = _session()
    producto_color = _producto_color()
    sku = _sku(producto_color)

    with _Patch(producto_color, skus=[sku]) as contexto, pytest.raises(AppException) as error:
        await _update(
            session,
            contexto,
            {"skus": [_fila(sku, precio={"normal": 30, "rebajado": 20, "rebaja_hasta": "2020-01-01"})]},
        )

    assert list(error.value.details) == ["skus -> 0 -> precio"]
    assert sku.precio == PRECIO


@pytest.mark.asyncio
async def test_patch_valida_todo_antes_de_cambiar_nada() -> None:
    session = _session()
    producto_color = _producto_color()
    sale = _imagen(producto_color, "sale")
    ajeno = _sku(_producto_color())

    with _Patch(producto_color, [sale]) as contexto, pytest.raises(AppException):
        await _update(session, contexto, {"is_visible": False, "imagenes": [], "skus": [_fila(ajeno)]})

    assert producto_color.is_visible is True
    contexto.mocks["imagenes_borrar"].assert_not_awaited()
