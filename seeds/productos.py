"""
Seed masivo de productos con sus colores, imágenes y SKUs.

Requiere haber ejecutado antes seeds.user y seeds.catalogos, y tener las fotos
aprobadas en seeds/data/fotos_aprobadas.json (ver seeds.fotos_pixabay).

Uso:
    python -m seeds.productos [--max-minutos 9]

Fases, ambas reanudables:
1. Subida: descarga cada foto de Pixabay y la sube a Cloudinary por el mismo
   camino que POST /imagenes/uploads. Las URLs quedan en seeds/data/subidas.json.
2. Creación: crea cada producto con ProductoService.create (create en un solo
   paso). Los productos que ya existen se saltan.

Orden de creación: los productos completados en la segunda ronda de revisión
primero y los de la primera ronda al final, para que estos, los más completos,
encabecen el listado de novedades (created_at descendente).
"""

import argparse
import asyncio
import io
import json
import random
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from starlette.datastructures import Headers

from app.core.config import Settings, get_settings
from app.core.database import check_database_connection, close_database, initialize_database
from app.core.logging import get_logger, setup_logging
import app.domains.model_registry  # noqa: F401
from app.domains.categorias.repositories import CategoriaRepository
from app.domains.colores.repositories import ColorRepository
from app.domains.imagenes.services import ImagenService
from app.domains.productos.models import Producto
from app.domains.productos.schemas import ProductoDetailCreate
from app.domains.productos.services import ProductoService
from app.domains.secciones.repositories import SeccionRepository
from app.domains.tallas.repositories import TallaRepository
from app.integrations.cloudinary import configure_cloudinary
from app.shared.enums import TipoImagen
from app.shared.services.slug import generate_slug
from seeds.catalogos import _get_actor_id
from seeds.fichas_productos import FICHAS, GRUPOS_TALLAS, MATERIALES, Ficha


logger = get_logger(__name__)

DATA_DIR = Path(__file__).parent / "data"
APROBADAS_PATH = DATA_DIR / "fotos_aprobadas.json"
SUBIDAS_PATH = DATA_DIR / "subidas.json"
BUSQUEDAS_DIR = DATA_DIR / "pixabay_cache" / "busquedas"
PIXABAY_API = "https://pixabay.com/api/"
PARALELOS = 6  # productos creados a la vez, cada uno en su propia sesión

HOY = date(2026, 11, 11)
REBAJA_VIGENTE = date(2026, 12, 31)
REBAJA_VENCIDA = date(2026, 10, 31)


# --------------------------------------------------------------------------
# Fase 1: subida de fotos
# --------------------------------------------------------------------------

def _hits_en_cache() -> dict[int, dict]:
    hits: dict[int, dict] = {}
    for ruta in BUSQUEDAS_DIR.glob("*.json"):
        for hit in json.loads(ruta.read_text(encoding="utf-8")):
            hits[hit["id"]] = hit
    return hits


async def _descargar(client: httpx.AsyncClient, hit: dict, settings: Settings) -> bytes:
    """Descarga la foto en 1280 px; si la URL de la caché caducó, la pide de nuevo por id."""
    for url in (hit.get("largeImageURL"), hit.get("webformatURL")):
        if not url:
            continue
        respuesta = await client.get(url)
        if respuesta.status_code == 200:
            return respuesta.content
    key = settings.PIXABAY_API_KEY.get_secret_value() if settings.PIXABAY_API_KEY else ""
    respuesta = await client.get(PIXABAY_API, params={"key": key, "id": hit["id"]})
    respuesta.raise_for_status()
    nuevo = respuesta.json()["hits"][0]
    respuesta = await client.get(nuevo["largeImageURL"])
    respuesta.raise_for_status()
    return respuesta.content


async def subir_fotos(settings: Settings, actor_id: UUID, ids: list[int], limite: float) -> dict[str, str]:
    subidas: dict[str, str] = (
        json.loads(SUBIDAS_PATH.read_text(encoding="utf-8")) if SUBIDAS_PATH.exists() else {}
    )
    pendientes = [i for i in ids if str(i) not in subidas]
    if not pendientes:
        return subidas
    logger.info("Subiendo %s fotos a Cloudinary...", len(pendientes))
    hits = _hits_en_cache()
    semaforo = asyncio.Semaphore(8)

    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "PinodoSeed/1.0"}) as client:
        async def una(pixabay_id: int) -> None:
            async with semaforo:
                if time.monotonic() > limite:
                    return
                contenido = await _descargar(client, hits[pixabay_id], settings)
                archivo = UploadFile(
                    file=io.BytesIO(contenido),
                    filename=f"{pixabay_id}.jpg",
                    headers=Headers({"content-type": "image/jpeg"}),
                )
                url = await ImagenService.upload_pending(archivo, settings, actor_id)
                subidas[str(pixabay_id)] = url
                SUBIDAS_PATH.write_text(json.dumps(subidas, indent=1), encoding="utf-8")

        resultados = await asyncio.gather(*(una(i) for i in pendientes), return_exceptions=True)
    errores = [r for r in resultados if isinstance(r, Exception)]
    for error in errores[:5]:
        logger.error("Error subiendo una foto: %r", error)
    logger.info("Subida: %s fotos en Cloudinary, %s errores.", len(subidas), len(errores))
    return subidas


# --------------------------------------------------------------------------
# Fase 2: creación de productos
# --------------------------------------------------------------------------

def _ean13(secuencia: int) -> str:
    """EAN-13 con prefijo 777 (Bolivia) y dígito de control."""
    base = f"777{secuencia:09d}"
    suma = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(base))
    return base + str((10 - suma % 10) % 10)


def _precio(ficha: Ficha, rng: random.Random, vencida: bool) -> dict:
    normal = Decimal(ficha.precio)
    if ficha.seccion == "Outlet":
        descuento = rng.uniform(0.30, 0.50)
    elif vencida or rng.random() < 0.20:
        descuento = rng.uniform(0.15, 0.30)
    else:
        return {"normal": normal}
    rebajado = Decimal(round(float(normal) * (1 - descuento)))
    hasta = REBAJA_VENCIDA if vencida else rng.choice([REBAJA_VIGENTE, None])
    return {"normal": normal, "rebajado": rebajado, "rebaja_hasta": hasta}


def _stock(rng: random.Random) -> dict:
    r = rng.random()
    if r < 0.10:
        return {"cantidad": 0, "minimo": 3}
    if r < 0.25:
        return {"cantidad": rng.randint(1, 2), "minimo": 3}
    return {"cantidad": rng.randint(5, 60), "minimo": 3}


class Catalogo:
    """Ids de secciones, categorías, colores y tallas, resueltos una sola vez."""

    def __init__(self) -> None:
        self.secciones: dict[str, UUID] = {}
        self.categorias: dict[tuple[str, str, str], UUID] = {}
        self.colores: dict[str, UUID] = {}
        self.tallas: dict[str, UUID] = {}

    async def cargar(self, db: AsyncSession) -> None:
        secciones = SeccionRepository(db)
        categorias = CategoriaRepository(db)
        for ficha in FICHAS:
            if ficha.seccion not in self.secciones:
                seccion = await secciones.get_active_by_slug(generate_slug(ficha.seccion))
                if seccion is None:
                    raise ValueError(f"Falta la sección {ficha.seccion}; ejecuta seeds.catalogos.")
                self.secciones[ficha.seccion] = seccion.id
            for raiz, sub in filter(None, (ficha.categoria, ficha.categoria_extra)):
                clave = (ficha.seccion, raiz, sub)
                if clave in self.categorias:
                    continue
                seccion_id = self.secciones[ficha.seccion]
                categoria = await categorias.get_active_sibling_by_slug(seccion_id, None, generate_slug(raiz))
                if categoria is not None and sub:
                    categoria = await categorias.get_active_sibling_by_slug(
                        seccion_id, categoria.id, generate_slug(sub)
                    )
                if categoria is None:
                    raise ValueError(f"Falta la categoría {clave}; ejecuta seeds.catalogos.")
                self.categorias[clave] = categoria.id
        self.colores = {c.nombre: c.id for c in await ColorRepository(db).find_many()}
        self.tallas = {t.etiqueta: t.id for t in await TallaRepository(db).find_many()}


def construir(
    posicion: int,
    ficha: Ficha,
    fotos: list[dict],
    subidas: dict[str, str],
    catalogo: Catalogo,
    secuencia: list[int],
) -> ProductoDetailCreate:
    rng = random.Random(f"producto-{posicion}")
    composicion, cuidados = MATERIALES[ficha.material]
    sin_detalles = posicion % 5 == 4  # ~20% deja vacíos los campos nullable
    vencida = posicion % 24 == 11  # ~5 productos con la rebaja ya vencida

    tallas = list(GRUPOS_TALLAS[ficha.tallas])
    if ficha.seccion == "Outlet":
        tallas = sorted(rng.sample(tallas, k=min(len(tallas), rng.choice([2, 3]))), key=tallas.index)
    precio = _precio(ficha, rng, vencida)
    tipo = TipoImagen.PRENDA if ficha.zona in ("pies", "accesorio") else TipoImagen.MODELO

    por_color: dict[str, list[str]] = {}
    for foto in fotos:
        por_color.setdefault(foto["color"], []).append(subidas[str(foto["pixabay_id"])])

    colores = []
    for indice, (color, urls) in enumerate(por_color.items()):
        skus = []
        for talla in tallas:
            secuencia[0] += 1
            skus.append({
                "talla_id": catalogo.tallas[talla],
                "codigo_barras": _ean13(secuencia[0]) if rng.random() < 0.85 else None,
                "is_visible": rng.random() >= 0.03,
                "precio": precio,
                # Costo de compra aproximado: entre 40 % y 55 % del precio normal.
                "costo": (Decimal(precio["normal"]) * Decimal(str(rng.uniform(0.40, 0.55)))).quantize(Decimal("0.01")),
                "stock": _stock(rng),
            })
        colores.append({
            "color_id": catalogo.colores[color],
            "is_visible": not (indice > 0 and rng.random() < 0.05),
            "imagenes": [{"url": url, "tipo": tipo} for url in urls],
            "skus": skus,
        })

    categoria_ids = [catalogo.categorias[(ficha.seccion, *ficha.categoria)]]
    if ficha.categoria_extra:
        categoria_ids.append(catalogo.categorias[(ficha.seccion, *ficha.categoria_extra)])

    return ProductoDetailCreate(
        seccion_id=catalogo.secciones[ficha.seccion],
        nombre=ficha.nombre,
        descripcion=ficha.descripcion,
        composicion=None if sin_detalles else composicion,
        cuidados=None if sin_detalles else cuidados,
        is_visible=posicion % 20 != 7,  # ~6 productos ocultos
        categoria_ids=categoria_ids,
        colores=colores,
    )


async def _existe(db: AsyncSession, seccion_id: UUID, nombre: str) -> bool:
    resultado = await db.execute(
        select(Producto.id).where(
            Producto.seccion_id == seccion_id,
            Producto.nombre == nombre,
            Producto.is_deleted.is_(False),
        )
    )
    return resultado.first() is not None


async def seed_productos(settings: Settings, max_minutos: float) -> None:
    if settings.ENVIRONMENT == "production":
        raise RuntimeError("El seed de productos no se ejecuta en producción.")
    configure_cloudinary(settings)
    limite = time.monotonic() + max_minutos * 60

    aprobadas = json.loads(APROBADAS_PATH.read_text(encoding="utf-8"))
    if [a["nombre"] for a in aprobadas] != [f.nombre for f in FICHAS]:
        raise ValueError("fotos_aprobadas.json no coincide con las fichas actuales.")
    con_fotos = [k for k, a in enumerate(aprobadas) if a["fotos"]]
    # Primero los completados en la segunda ronda; los de la primera, al final.
    orden = [k for k in con_fotos if not aprobadas[k]["primera_ronda"]] + [
        k for k in con_fotos if aprobadas[k]["primera_ronda"]
    ]

    engine, session_factory = initialize_database(settings)
    try:
        await check_database_connection(engine)
        async with session_factory() as db:
            actor_id = await _get_actor_id(db, settings)

        ids = [f["pixabay_id"] for k in orden for f in aprobadas[k]["fotos"]]
        subidas = await subir_fotos(settings, actor_id, ids, limite)
        if any(str(i) not in subidas for i in ids):
            logger.info("Faltan fotos por subir; vuelve a ejecutar para continuar.")
            return

        async with session_factory() as db:
            catalogo = Catalogo()
            await catalogo.cargar(db)

        # La secuencia de códigos de barras depende solo de la posición de la
        # ficha, así un producto ya creado no desplaza los códigos de los demás.
        creados = existentes = 0
        semaforo = asyncio.Semaphore(PARALELOS)

        async def crear(posicion: int) -> None:
            nonlocal creados, existentes
            async with semaforo:
                if time.monotonic() > limite:
                    return
                ficha = FICHAS[posicion]
                datos = construir(
                    posicion, ficha, aprobadas[posicion]["fotos"], subidas, catalogo, [posicion * 1000]
                )
                async with session_factory() as db:
                    if await _existe(db, datos.seccion_id, ficha.nombre):
                        existentes += 1
                        return
                    await ProductoService.create(db, datos, actor_id, settings)
                creados += 1
                logger.info(
                    "[%s/%s] %s › %s: %s colores, %s SKUs",
                    existentes + creados, len(orden), ficha.seccion, ficha.nombre,
                    len(datos.colores), sum(len(c.skus) for c in datos.colores),
                )

        # Un grupo termina antes de empezar el siguiente, para respetar el orden
        # de novedades entre grupos.
        segunda_ronda = [k for k in orden if not aprobadas[k]["primera_ronda"]]
        primera_ronda = [k for k in orden if aprobadas[k]["primera_ronda"]]
        for grupo in (segunda_ronda, primera_ronda):
            await asyncio.gather(*(crear(k) for k in grupo))
            if time.monotonic() > limite:
                logger.info("Tiempo agotado; vuelve a ejecutar para continuar.")
                break

        logger.info(
            "Seed de productos: %s creados, %s ya existían, %s en total con fotos.",
            creados, existentes, len(orden),
        )
    except Exception:
        logger.exception("Error durante la ejecución del seed de productos")
        raise
    finally:
        await close_database(engine)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-minutos", type=float, default=9.0)
    args = parser.parse_args()
    app_settings = get_settings()
    setup_logging(app_settings)
    asyncio.run(seed_productos(app_settings, args.max_minutos))
