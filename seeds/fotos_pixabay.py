"""
Sondeo y selección de fotos de Pixabay para el seed de productos.

No toca la base de datos. Busca en Pixabay según las fichas, filtra por tags,
mide el color de la prenda sobre la miniatura y elige las fotos de cada color.

Uso:
    python -m seeds.fotos_pixabay [--max-minutos 9]

Es reanudable: las búsquedas y miniaturas quedan en caché, así que si se corta
por tiempo, la siguiente ejecución continúa donde quedó sin repetir peticiones.

Salidas en seeds/data/:
    seleccion_fotos.json → fotos elegidas por producto y color
    galeria.html         → revisión visual; marca las fotos que no sirven
    rechazadas.json      → (opcional) ids de Pixabay a excluir en la próxima ejecución
"""

import argparse
import asyncio
import hashlib
import html
import io
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import httpx
from PIL import Image

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from seeds.catalogos import SEED_COLORES
from seeds.fichas_productos import FICHAS, Ficha


logger = get_logger(__name__)

API_URL = "https://pixabay.com/api/"
DATA_DIR = Path(__file__).parent / "data"
SEARCH_DIR = DATA_DIR / "pixabay_cache" / "busquedas"
PREVIEW_DIR = DATA_DIR / "pixabay_cache" / "previews"
SELECCION_PATH = DATA_DIR / "seleccion_fotos.json"
RECHAZADAS_PATH = DATA_DIR / "rechazadas.json"
GALERIA_PATH = DATA_DIR / "galeria.html"

MAX_DELTA_E = 25.0  # diferencia máxima (CIEDE2000) entre la prenda y su color
TAGS_PRINCIPALES = 3  # la prenda debe estar entre los primeros tags (Pixabay los ordena por relevancia)
MIN_PROPORCION = 0.15  # parte mínima de la zona medida que ocupa el color
MAX_COLORES = 4
MIN_COLORES = 2

HEX_COLORES: dict[str, str] = dict(SEED_COLORES)

# Cada color del catálogo es uno de los filtros `colors` de Pixabay.
FAMILIA_PIXABAY: dict[str, str] = {
    "Negro": "black", "Blanco": "white", "Gris": "gray", "Marrón": "brown",
    "Rojo": "red", "Naranja": "orange", "Amarillo": "yellow", "Verde": "green",
    "Turquesa": "turquoise", "Azul": "blue", "Lila": "lilac", "Rosa": "pink",
}

# Palabras de color en los tags y los colores del catálogo con los que son compatibles.
PALABRAS_COLOR: dict[str, set[str]] = {
    "black": {"Negro"}, "white": {"Blanco"}, "cream": {"Blanco", "Marrón"},
    "ivory": {"Blanco"}, "gray": {"Gris"}, "grey": {"Gris"}, "silver": {"Gris"},
    "brown": {"Marrón"}, "beige": {"Marrón", "Blanco"}, "tan": {"Marrón"},
    "camel": {"Marrón"}, "chocolate": {"Marrón"}, "khaki": {"Marrón", "Verde"},
    "red": {"Rojo"}, "burgundy": {"Rojo"}, "maroon": {"Rojo"}, "wine": {"Rojo"},
    "orange": {"Naranja"}, "yellow": {"Amarillo"}, "mustard": {"Amarillo"},
    "gold": {"Amarillo"}, "green": {"Verde"}, "olive": {"Verde"},
    "turquoise": {"Turquesa"}, "teal": {"Turquesa"}, "aqua": {"Turquesa"},
    "blue": {"Azul"}, "navy": {"Azul", "Negro"}, "purple": {"Lila"},
    "lilac": {"Lila"}, "lavender": {"Lila"}, "violet": {"Lila"}, "pink": {"Rosa"},
}

# Escenas donde la prenda suele ser un detalle; una ficha puede permitir alguna.
ESCENAS = (
    "landscape", "mountain", "sky", "sunset", "sunrise", "forest", "lake", "river",
    "waterfall", "architecture", "building", "airplane", "aircraft", "plane", "car",
    "motorcycle", "vehicle", "dog", "cat", "animal", "food", "coffee", "christmas",
    "santa", "3d", "render", "figure", "figurine", "gnome", "karate", "martial arts",
    "golf", "soccer", "tea", "book", "water polo", "kayak", "canoe", "swimming",
    "ship", "container",
)

PERSONAS = (
    "woman", "man", "girl", "boy", "child", "children", "kid", "baby", "toddler",
    "model", "person", "people", "lady", "ladies", "guy", "female", "male",
    "teen", "teenager", "adult", "mother", "father", "family", "couple", "infant",
)
DETALLE = (
    "texture", "fabric", "close-up", "closeup", "close up", "detail", "macro",
    "textile", "stitch", "stitching", "material", "thread", "yarn", "weave",
)
SENALES_PRENDA = (
    "clothes", "clothing", "hanger", "isolated", "flat lay", "flatlay", "product",
    "folded", "shop", "store", "boutique", "apparel", "garment", "wardrobe",
    "white background", "studio", "outfit",
)
PROHIBIDAS_GLOBAL = (
    "nude", "naked", "erotic", "sexy", "sensual", "lingerie", "underwear", "bikini",
    "swimsuit", "bra", "halloween", "costume", "cosplay", "toy", "doll", "drawing",
    "illustration", "cartoon", "painting", "statue", "sculpture", "horse", "wedding",
    "bride", "groom", "military", "soldier", "police", "smoking", "cigarette",
    "zombie", "horror", "witch", "blood", "fantasy", "gothic",
)
PROHIBIDAS_PUBLICO: dict[str, tuple[str, ...]] = {
    "mujer": ("man", "men", "boy", "guy", "male", "beard", "child", "children", "kid",
              "baby", "toddler", "couple", "family", "father"),
    "hombre": ("woman", "women", "girl", "female", "lady", "ladies", "child", "children",
               "kid", "baby", "toddler", "couple", "family", "mother", "dress", "skirt",
               "makeup", "lipstick"),
    "ninos": ("woman", "women", "man", "men", "adult", "couple", "mother", "father",
              "lady", "guy"),
    "neutro": (),
}
EXIGIDAS_NINOS = (
    "child", "children", "kid", "baby", "toddler", "infant", "childhood",
    "little girl", "little boy", "son", "daughter", "preschool", "kindergarten",
)

# Zona de la foto donde se mide la prenda cuando la lleva una persona: (x0, y0, x1, y1).
ZONAS_MODELO: dict[str, tuple[float, float, float, float]] = {
    "superior": (0.30, 0.25, 0.70, 0.60),
    "inferior": (0.30, 0.55, 0.70, 0.90),
    "completo": (0.30, 0.30, 0.70, 0.75),
    "accesorio": (0.25, 0.25, 0.75, 0.75),
    "pies": (0.15, 0.40, 0.85, 0.95),
}
ZONA_PRENDA = (0.20, 0.20, 0.80, 0.80)
ZONA_DETALLE = (0.10, 0.10, 0.90, 0.90)


# --------------------------------------------------------------------------
# Color
# --------------------------------------------------------------------------

def srgb_a_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def lineal(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lineal(c) for c in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """Diferencia de color CIEDE2000."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    c_media = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(c_media**7 / (c_media**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0

    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dhp_grande = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))

    lp_media = (l1 + l2) / 2
    cp_media = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hp_media = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_media = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hp_media = (h1p + h2p + 360) / 2
    else:
        hp_media = (h1p + h2p - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(hp_media - 30))
        + 0.24 * math.cos(math.radians(2 * hp_media))
        + 0.32 * math.cos(math.radians(3 * hp_media + 6))
        - 0.20 * math.cos(math.radians(4 * hp_media - 63))
    )
    d_theta = 30 * math.exp(-(((hp_media - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cp_media**7 / (cp_media**7 + 25**7))
    sl = 1 + (0.015 * (lp_media - 50) ** 2) / math.sqrt(20 + (lp_media - 50) ** 2)
    sc = 1 + 0.045 * cp_media
    sh = 1 + 0.015 * cp_media * t
    rt = -math.sin(math.radians(2 * d_theta)) * rc
    return math.sqrt(
        (dlp / sl) ** 2
        + (dcp / sc) ** 2
        + (dhp_grande / sh) ** 2
        + rt * (dcp / sc) * (dhp_grande / sh)
    )


def hex_a_rgb(codigo: str) -> tuple[int, int, int]:
    return int(codigo[1:3], 16), int(codigo[3:5], 16), int(codigo[5:7], 16)


def rgb_a_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


LAB_COLORES: dict[str, tuple[float, float, float]] = {
    nombre: srgb_a_lab(hex_a_rgb(codigo)) for nombre, codigo in SEED_COLORES
}


def es_piel(lab: tuple[float, float, float]) -> bool:
    l, a, b = lab
    return 35 <= l <= 85 and 6 <= a <= 28 and 12 <= b <= 38


def medir_color(
    imagen: Image.Image,
    zona: tuple[float, float, float, float],
    es_modelo: bool,
    ignorar_fondo: bool,
) -> tuple[tuple[int, int, int], float] | None:
    """Color dominante de la prenda dentro de la zona, ignorando fondo y piel."""
    ancho, alto = imagen.size
    pixeles = imagen.load()

    # Color del fondo: mediana del marco exterior.
    marco: list[tuple[int, int, int]] = []
    borde = max(2, int(min(ancho, alto) * 0.06))
    for y in range(alto):
        for x in range(ancho):
            if x < borde or y < borde or x >= ancho - borde or y >= alto - borde:
                marco.append(pixeles[x, y])
    fondo = tuple(int(median(c[i] for c in marco)) for i in range(3))
    lab_fondo = srgb_a_lab(fondo)  # type: ignore[arg-type]

    x0, y0, x1, y1 = zona
    recorte = imagen.crop((int(ancho * x0), int(alto * y0), int(ancho * x1), int(alto * y1)))
    cuantizada = recorte.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    paleta = cuantizada.getpalette() or []
    conteos = sorted(cuantizada.getcolors() or [], reverse=True)
    total = sum(c for c, _ in conteos)
    if not total:
        return None

    candidatos: list[tuple[tuple[int, int, int], float]] = []
    for conteo, indice in conteos:
        rgb = tuple(paleta[indice * 3 : indice * 3 + 3])
        proporcion = conteo / total
        lab = srgb_a_lab(rgb)  # type: ignore[arg-type]
        if ignorar_fondo and delta_e(lab, lab_fondo) < 10:
            continue
        if es_modelo and es_piel(lab) and proporcion < 0.35:
            continue
        candidatos.append((rgb, proporcion))  # type: ignore[arg-type]

    if not candidatos:
        conteo, indice = conteos[0]
        candidatos = [(tuple(paleta[indice * 3 : indice * 3 + 3]), conteo / total)]  # type: ignore[list-item]
    return candidatos[0]


def color_mas_cercano(rgb: tuple[int, int, int]) -> tuple[str, float]:
    lab = srgb_a_lab(rgb)
    return min(((nombre, delta_e(lab, ref)) for nombre, ref in LAB_COLORES.items()), key=lambda x: x[1])


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------

def _patron(palabra: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z]){re.escape(palabra)}(?:s|es)?(?![a-z])")


_PATRONES: dict[str, re.Pattern[str]] = {}


def contiene(texto: str, palabras: tuple[str, ...] | list[str] | set[str]) -> list[str]:
    encontradas = []
    for palabra in palabras:
        patron = _PATRONES.get(palabra)
        if patron is None:
            patron = _PATRONES[palabra] = _patron(palabra)
        if patron.search(texto):
            encontradas.append(palabra)
    return encontradas


@dataclass
class Candidata:
    hit: dict
    tipo: str
    color: str
    delta_e: float
    color_medido: str
    puntaje: float


def clasificar_tipo(texto: str) -> str:
    if contiene(texto, PERSONAS):
        return "MODELO"
    if contiene(texto, DETALLE):
        return "DETALLE"
    return "PRENDA"


def pasa_tags(ficha: Ficha, texto: str) -> list[str] | None:
    """Devuelve las palabras requeridas encontradas, o None si la foto se descarta."""
    principales = ", ".join(texto.split(", ")[:TAGS_PRINCIPALES])
    if not contiene(principales, ficha.requeridas):
        return None
    requeridas = contiene(texto, ficha.requeridas)
    if contiene(texto, PROHIBIDAS_GLOBAL) or contiene(texto, PROHIBIDAS_PUBLICO[ficha.publico]):
        return None
    escenas = tuple(e for e in ESCENAS if e not in ficha.permitidas)
    if contiene(texto, escenas):
        return None
    if ficha.publico == "ninos" and not contiene(texto, EXIGIDAS_NINOS):
        return None
    return requeridas


def colores_en_tags(ficha: Ficha, tags: list[str]) -> tuple[set[str], set[str]]:
    """Colores compatibles mencionados junto a la prenda (fuertes) y sueltos (débiles)."""
    fuertes: set[str] = set()
    debiles: set[str] = set()
    for tag in tags:
        for palabra, compatibles in PALABRAS_COLOR.items():
            if not contiene(tag, (palabra,)):
                continue
            if tag.strip() == palabra:
                debiles |= compatibles
            elif contiene(tag, ficha.requeridas):
                fuertes |= compatibles
    return fuertes, debiles


# --------------------------------------------------------------------------
# Pixabay
# --------------------------------------------------------------------------

class Pixabay:
    def __init__(self, client: httpx.AsyncClient, key: str, limite_tiempo: float) -> None:
        self.client = client
        self.key = key
        self.limite_tiempo = limite_tiempo
        self.restantes: int | None = None
        self.reinicio = 60.0
        self.peticiones = 0

    @staticmethod
    def _ruta_cache(params: dict) -> Path:
        clave = json.dumps(params, sort_keys=True, ensure_ascii=False)
        return SEARCH_DIR / f"{hashlib.sha1(clave.encode()).hexdigest()}.json"

    def sin_tiempo(self) -> bool:
        return time.monotonic() > self.limite_tiempo

    async def buscar(self, q: str, color: str | None) -> list[dict] | None:
        """Hits de una búsqueda; None si se acabó el tiempo antes de consultarla."""
        params = {
            "q": q,
            "image_type": "photo",
            "safesearch": "true",
            "per_page": 100,
            "min_width": 1000,
            "min_height": 1000,
        }
        if color:
            params["colors"] = color
        ruta = self._ruta_cache(params)
        if ruta.exists():
            return json.loads(ruta.read_text(encoding="utf-8"))
        if self.sin_tiempo():
            return None

        while True:
            if self.restantes is not None and self.restantes <= 1:
                await asyncio.sleep(self.reinicio + 1)
                self.restantes = None
            respuesta = await self.client.get(API_URL, params={**params, "key": self.key})
            self.peticiones += 1
            self.restantes = int(respuesta.headers.get("X-RateLimit-Remaining", 50))
            self.reinicio = float(respuesta.headers.get("X-RateLimit-Reset", 60))
            if respuesta.status_code == 429:
                await asyncio.sleep(max(self.reinicio, 10) + 1)
                continue
            respuesta.raise_for_status()
            break

        campos = ("id", "tags", "pageURL", "previewURL", "webformatURL", "largeImageURL",
                  "imageWidth", "imageHeight", "downloads", "likes", "user")
        hits = [{c: h.get(c) for c in campos} for h in respuesta.json().get("hits", [])]
        ruta.write_text(json.dumps(hits, ensure_ascii=False), encoding="utf-8")
        return hits


async def descargar_previews(client: httpx.AsyncClient, hits: dict[int, dict]) -> None:
    pendientes = [h for i, h in hits.items() if not (PREVIEW_DIR / f"{i}.jpg").exists()]
    semaforo = asyncio.Semaphore(16)

    async def una(hit: dict) -> None:
        async with semaforo:
            try:
                respuesta = await client.get(hit["previewURL"])
                respuesta.raise_for_status()
                (PREVIEW_DIR / f"{hit['id']}.jpg").write_bytes(respuesta.content)
            except httpx.HTTPError as error:
                logger.warning("No se pudo descargar la miniatura %s: %s", hit["id"], error)

    if pendientes:
        logger.info("Descargando %s miniaturas...", len(pendientes))
        await asyncio.gather(*(una(h) for h in pendientes))


# --------------------------------------------------------------------------
# Evaluación y selección
# --------------------------------------------------------------------------

def evaluar(ficha: Ficha, hit: dict, imagenes: dict[int, Image.Image]) -> Candidata | None:
    tags = [t.strip().lower() for t in (hit.get("tags") or "").split(",") if t.strip()]
    texto = ", ".join(tags)
    requeridas = pasa_tags(ficha, texto)
    if requeridas is None:
        return None
    imagen = imagenes.get(hit["id"])
    if imagen is None:
        return None

    tipo = clasificar_tipo(texto)
    if ficha.zona in ("accesorio", "pies") and tipo == "DETALLE":
        tipo = "PRENDA"
    if tipo == "MODELO":
        zona = ZONAS_MODELO[ficha.zona]
    elif tipo == "DETALLE":
        zona = ZONA_DETALLE
    else:
        zona = ZONA_PRENDA

    medido = medir_color(imagen, zona, es_modelo=tipo == "MODELO", ignorar_fondo=tipo != "DETALLE")
    if medido is None:
        return None
    rgb, proporcion = medido
    if proporcion < MIN_PROPORCION:
        return None
    color, distancia = color_mas_cercano(rgb)
    if color not in ficha.colores or distancia > MAX_DELTA_E:
        return None

    fuertes, debiles = colores_en_tags(ficha, tags)
    if fuertes and color not in fuertes:
        return None

    puntaje = (
        (15 - distancia) / 5
        + 3 * (color in fuertes)
        + 1 * (color in debiles)
        + 0.5 * len(requeridas)
        + 0.5 * (hit["imageHeight"] >= hit["imageWidth"])
        + math.log10((hit.get("downloads") or 0) + 1) / 2
        + 0.5 * bool(tipo == "PRENDA" and contiene(texto, SENALES_PRENDA))
    )
    return Candidata(hit, tipo, color, round(distancia, 1), rgb_a_hex(rgb), round(puntaje, 2))


def seleccionar(
    hits_por_ficha: list[list[dict]],
    imagenes: dict[int, Image.Image],
    rechazadas: set[int],
) -> list[dict]:
    usadas: set[int] = set(rechazadas)
    resultado: list[dict] = []

    for ficha, hits in zip(FICHAS, hits_por_ficha):
        por_color: dict[str, dict[str, list[Candidata]]] = {c: {"MODELO": [], "PRENDA": [], "DETALLE": []} for c in ficha.colores}
        vistos: set[int] = set()
        for hit in hits:
            if hit["id"] in vistos:
                continue
            vistos.add(hit["id"])
            candidata = evaluar(ficha, hit, imagenes)
            if candidata is not None:
                por_color[candidata.color][candidata.tipo].append(candidata)
        for tipos in por_color.values():
            for lista in tipos.values():
                lista.sort(key=lambda c: c.puntaje, reverse=True)

        def libres(lista: list[Candidata]) -> list[Candidata]:
            return [c for c in lista if c.hit["id"] not in usadas]

        def cobertura(color: str) -> float:
            tipos = por_color[color]
            modelo, prenda = libres(tipos["MODELO"]), libres(tipos["PRENDA"])
            mejor = max([c.puntaje for c in modelo + prenda] or [0])
            return 2 * bool(modelo) + 1 * bool(prenda) + 0.3 * bool(libres(tipos["DETALLE"])) + mejor / 10

        orden = sorted(
            (c for c in ficha.colores if libres(por_color[c]["MODELO"]) or libres(por_color[c]["PRENDA"])),
            key=cobertura,
            reverse=True,
        )[:MAX_COLORES]

        colores_elegidos = []
        for posicion, color in enumerate(orden):
            elegidas: list[Candidata] = []
            tipos_a_elegir = ["MODELO", "PRENDA"] + (["DETALLE"] if posicion == 0 else [])
            for tipo in tipos_a_elegir:
                opciones = libres(por_color[color][tipo])
                if opciones:
                    elegidas.append(opciones[0])
                    usadas.add(opciones[0].hit["id"])
            if not elegidas:
                continue
            colores_elegidos.append({
                "color": color,
                "hex": HEX_COLORES[color],
                "imagenes": [
                    {
                        "tipo": c.tipo,
                        "pixabay_id": c.hit["id"],
                        "page_url": c.hit["pageURL"],
                        "preview_url": c.hit["previewURL"],
                        "web_url": c.hit["webformatURL"],
                        "tags": c.hit["tags"],
                        "color_medido": c.color_medido,
                        "delta_e": c.delta_e,
                        "puntaje": c.puntaje,
                    }
                    for c in elegidas
                ],
            })

        candidatas_por_color = {
            color: {tipo: len(lista) for tipo, lista in tipos.items()}
            for color, tipos in por_color.items()
        }
        n = len(colores_elegidos)
        resultado.append({
            "seccion": ficha.seccion,
            "categoria": list(ficha.categoria),
            "nombre": ficha.nombre,
            "estado": "ok" if n >= MIN_COLORES else ("debil" if n == 1 else "sin_fotos"),
            "colores": colores_elegidos,
            "candidatas_por_color": candidatas_por_color,
        })
    return resultado


# --------------------------------------------------------------------------
# Galería
# --------------------------------------------------------------------------

def generar_galeria(seleccion: list[dict]) -> str:
    e = html.escape
    bloques = []
    seccion_actual = None
    for producto in seleccion:
        if producto["seccion"] != seccion_actual:
            seccion_actual = producto["seccion"]
            bloques.append(f"<h2>{e(seccion_actual)}</h2>")
        filas = []
        for color in producto["colores"]:
            fotos = []
            for img in color["imagenes"]:
                fotos.append(
                    f'<figure><a href="{e(img["page_url"])}" target="_blank" rel="noopener">'
                    f'<img loading="lazy" src="{e(img["web_url"])}" alt=""></a>'
                    f'<figcaption><b>{img["tipo"]}</b> · ΔE {img["delta_e"]} '
                    f'<span class="sw" style="background:{img["color_medido"]}" title="medido {img["color_medido"]}"></span>'
                    f'<label><input type="checkbox" data-id="{img["pixabay_id"]}"> rechazar</label>'
                    f'<small>{e(img["tags"])}</small></figcaption></figure>'
                )
            filas.append(
                f'<div class="fila"><div class="color"><span class="sw grande" style="background:{color["hex"]}"></span>'
                f'{e(color["color"])}</div><div class="fotos">{"".join(fotos)}</div></div>'
            )
        categoria = " › ".join(c for c in producto["categoria"] if c)
        bloques.append(
            f'<section class="producto {producto["estado"]}"><h3>{e(producto["nombre"])} '
            f'<span class="estado">{producto["estado"]}</span> <small>{e(categoria)}</small></h3>'
            f'{"".join(filas) or "<p>Sin fotos válidas.</p>"}</section>'
        )

    total = len(seleccion)
    ok = sum(p["estado"] == "ok" for p in seleccion)
    imagenes = sum(len(c["imagenes"]) for p in seleccion for c in p["colores"])
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisión de fotos</title>
<style>
:root {{ --bg:#fafafa; --fg:#1c1c1c; --card:#fff; --line:#e3e3e3; --muted:#666; --bad:#c0392b; --warn:#b7791f; --good:#2f855a; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141414; --fg:#eee; --card:#1f1f1f; --line:#333; --muted:#aaa; }} }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg); font:14px/1.4 system-ui, sans-serif; }}
header {{ position:sticky; top:0; background:var(--bg); padding:8px 0; border-bottom:1px solid var(--line); z-index:1; display:flex; gap:12px; flex-wrap:wrap; align-items:center; }}
button {{ padding:6px 12px; cursor:pointer; }}
.producto {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; margin:12px 0; }}
.producto h3 {{ margin:0 0 8px; }} .producto small {{ color:var(--muted); font-weight:normal; }}
.estado {{ font-size:12px; padding:2px 6px; border-radius:4px; color:#fff; background:var(--good); }}
.debil .estado {{ background:var(--warn); }} .sin_fotos .estado {{ background:var(--bad); }}
.fila {{ display:flex; gap:12px; padding:8px 0; border-top:1px solid var(--line); flex-wrap:wrap; }}
.color {{ width:120px; display:flex; gap:6px; align-items:center; font-weight:600; }}
.fotos {{ display:flex; gap:10px; flex-wrap:wrap; }}
figure {{ margin:0; width:200px; }} figure img {{ width:200px; height:200px; object-fit:cover; border-radius:6px; display:block; }}
figcaption {{ font-size:12px; display:flex; flex-direction:column; gap:2px; margin-top:4px; }}
figcaption small {{ color:var(--muted); max-height:3em; overflow:hidden; }}
.sw {{ display:inline-block; width:14px; height:14px; border-radius:3px; border:1px solid var(--line); vertical-align:middle; }}
.sw.grande {{ width:22px; height:22px; }}
figure:has(input:checked) img {{ opacity:.3; outline:3px solid var(--bad); }}
</style></head><body>
<header><b>{ok}/{total} productos con 2+ colores · {imagenes} imágenes</b>
<span id="cuenta">0 rechazadas</span>
<button id="copiar">Copiar ids rechazados</button>
<span style="color:var(--muted)">Pega la lista en seeds/data/rechazadas.json o envíamela.</span></header>
{"".join(bloques)}
<script>
const KEY = "rechazadas-pixabay";
const cajas = [...document.querySelectorAll("input[data-id]")];
let guardadas = [];
try {{ guardadas = JSON.parse(localStorage.getItem(KEY) || "[]"); }} catch (e) {{}}
cajas.forEach(c => {{ if (guardadas.includes(Number(c.dataset.id))) c.checked = true; }});
function ids() {{ return cajas.filter(c => c.checked).map(c => Number(c.dataset.id)); }}
function actualizar() {{
  document.getElementById("cuenta").textContent = ids().length + " rechazadas";
  try {{ localStorage.setItem(KEY, JSON.stringify(ids())); }} catch (e) {{}}
}}
cajas.forEach(c => c.addEventListener("change", actualizar));
document.getElementById("copiar").addEventListener("click", () => {{
  const texto = JSON.stringify(ids());
  navigator.clipboard.writeText(texto).then(() => alert("Copiado: " + texto), () => prompt("Copia:", texto));
}});
actualizar();
</script></body></html>"""


# --------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------

async def sondear(max_minutos: float) -> bool:
    """Devuelve True si completó todas las búsquedas."""
    settings = get_settings()
    if settings.PIXABAY_API_KEY is None:
        raise RuntimeError("Falta PIXABAY_API_KEY en el .env.")
    SEARCH_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    rechazadas: set[int] = set()
    if RECHAZADAS_PATH.exists():
        rechazadas = {int(i) for i in json.loads(RECHAZADAS_PATH.read_text(encoding="utf-8"))}

    limite = time.monotonic() + max_minutos * 60
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "PinodoSeed/1.0"}) as client:
        api = Pixabay(client, settings.PIXABAY_API_KEY.get_secret_value(), limite)

        hits_por_ficha: list[list[dict]] = []
        completo = True
        for indice, ficha in enumerate(FICHAS, start=1):
            familias = sorted({FAMILIA_PIXABAY[c] for c in ficha.colores})
            hits: list[dict] = []
            for q in ficha.busquedas:
                for familia in [None, *familias]:
                    resultado = await api.buscar(q, familia)
                    if resultado is None:
                        completo = False
                        break
                    hits.extend(resultado)
                if not completo:
                    break
            if not completo:
                logger.info("Tiempo agotado en la ficha %s/%s; vuelve a ejecutar para continuar.", indice, len(FICHAS))
                break
            hits_por_ficha.append(hits)
            if indice % 10 == 0:
                logger.info("Búsquedas: %s/%s fichas (%s peticiones nuevas).", indice, len(FICHAS), api.peticiones)

        logger.info("Peticiones nuevas a Pixabay: %s.", api.peticiones)
        if not completo:
            return False

        # Solo se descargan miniaturas de las fotos que pasan los filtros de tags de su ficha.
        necesarias: dict[int, dict] = {}
        for ficha, hits in zip(FICHAS, hits_por_ficha):
            for hit in hits:
                texto = ", ".join(t.strip().lower() for t in (hit.get("tags") or "").split(","))
                if pasa_tags(ficha, texto) is not None:
                    necesarias[hit["id"]] = hit
        await descargar_previews(client, necesarias)

    imagenes: dict[int, Image.Image] = {}
    for id_hit in necesarias:
        ruta = PREVIEW_DIR / f"{id_hit}.jpg"
        if ruta.exists():
            try:
                imagenes[id_hit] = Image.open(io.BytesIO(ruta.read_bytes())).convert("RGB")
            except OSError:
                logger.warning("Miniatura corrupta: %s", ruta.name)

    seleccion = seleccionar(hits_por_ficha, imagenes, rechazadas)
    SELECCION_PATH.write_text(json.dumps(seleccion, ensure_ascii=False, indent=2), encoding="utf-8")
    GALERIA_PATH.write_text(generar_galeria(seleccion), encoding="utf-8")

    estados = {e: sum(p["estado"] == e for p in seleccion) for e in ("ok", "debil", "sin_fotos")}
    colores = sum(len(p["colores"]) for p in seleccion)
    total_imagenes = sum(len(c["imagenes"]) for p in seleccion for c in p["colores"])
    logger.info(
        "Selección: %s productos ok, %s débiles, %s sin fotos; %s colores y %s imágenes. Rechazadas excluidas: %s.",
        estados["ok"], estados["debil"], estados["sin_fotos"], colores, total_imagenes, len(rechazadas),
    )
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-minutos", type=float, default=9.0)
    args = parser.parse_args()
    setup_logging(get_settings())
    asyncio.run(sondear(args.max_minutos))
