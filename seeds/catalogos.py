import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import (
    check_database_connection,
    close_database,
    initialize_database,
)
from app.core.logging import get_logger, setup_logging
import app.domains.model_registry  # noqa: F401
from app.domains.categorias.repositories import CategoriaRepository
from app.domains.categorias.schemas import CategoriaCreate
from app.domains.categorias.services import CategoriaService
from app.domains.colores.repositories import ColorRepository
from app.domains.colores.schemas import ColorCreate
from app.domains.colores.services import ColorService
from app.domains.secciones.repositories import SeccionRepository
from app.domains.secciones.schemas import SeccionCreate
from app.domains.secciones.services import SeccionService
from app.domains.tallas.repositories import TallaRepository
from app.domains.tallas.schemas import TallaCreate
from app.domains.tallas.services import TallaService
from app.domains.usuarios.repositories import UsuarioRepository
from app.shared.enums import Role
from app.shared.services.slug import generate_slug


logger = get_logger(__name__)


# Tallas y secciones/categorías se listan por created_at: el orden de estas
# listas es el orden en que se muestran en el frontend.
SEED_TALLAS: list[str] = [
    # Letras
    "XS", "S", "M", "L", "XL", "XXL",
    # Numéricas en orden continuo: cintura de pantalón (28–40) y calzado (35–44)
    "28", "30", "32", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44",
    # Accesorios y prendas sin talla
    "Única",
]

# Los 12 colores del filtro `colors` de Pixabay, para que cada color del
# catálogo tenga búsqueda directa de fotos. Se listan por nombre.
SEED_COLORES: list[tuple[str, str]] = [
    ("Negro", "#000000"),     # black
    ("Blanco", "#FFFFFF"),    # white
    ("Gris", "#9E9E9E"),      # gray
    ("Marrón", "#795548"),    # brown
    ("Rojo", "#D32F2F"),      # red
    ("Naranja", "#F57C00"),   # orange
    ("Amarillo", "#FBC02D"),  # yellow
    ("Verde", "#388E3C"),     # green
    ("Turquesa", "#26A69A"),  # turquoise
    ("Azul", "#1976D2"),      # blue
    ("Lila", "#9575CD"),      # lilac
    ("Rosa", "#EC407A"),      # pink
]

# (nombre, is_visible, [(categoría raíz, [subcategorías])]).
# Solo la sección Outlet está oculta; todas las categorías son visibles.
SEED_SECCIONES: list[tuple[str, bool, list[tuple[str, list[str]]]]] = [
    (
        "Mujer",
        True,
        [
            ("Tops", ["Blusas", "Camisetas"]),
            ("Pantalones", ["Jeans", "De vestir"]),
            ("Vestidos", ["Casuales", "De fiesta"]),
            ("Faldas", ["Cortas", "Largas"]),
            ("Abrigos", ["Chaquetas", "Abrigos largos"]),
        ],
    ),
    (
        "Hombre",
        True,
        [
            ("Camisas", ["Formales", "Casuales"]),
            ("Camisetas", ["Básicas", "Polos"]),
            ("Pantalones", ["Jeans", "Chinos"]),
            ("Sudaderas", ["Con capucha", "Sin capucha"]),
            ("Abrigos", ["Chaquetas", "Parkas"]),
        ],
    ),
    (
        "Calzado",
        True,
        [
            ("Zapatillas", ["Urbanas", "Deportivas"]),
            ("Botas", ["Botines", "Botas altas"]),
            ("Zapatos", ["De vestir", "Mocasines"]),
            ("Tacones", ["Clásicos", "Sandalias de tacón"]),
            ("Sandalias", ["Planas", "Chanclas"]),
        ],
    ),
    (
        "Accesorios",
        True,
        [
            ("Bolsos", ["Carteras", "Mochilas"]),
            ("Cinturones", ["De cuero", "De tela"]),
            ("Gorros", ["Gorras", "Gorros de lana"]),
            ("Bufandas y pañuelos", ["Bufandas", "Pañuelos"]),
            ("Calcetines", ["Cortos", "Largos"]),
        ],
    ),
    (
        "Outlet",
        False,
        [
            ("Liquidación", []),
            ("Última talla", []),
            ("Temporada pasada", []),
        ],
    ),
]


async def _get_actor_id(db_session: AsyncSession, settings: Settings) -> UUID:
    """El catálogo se registra a nombre del primer SUPERADMIN del seed de usuarios."""
    email = (settings.SEED_ADMIN_EMAIL_1 or "").strip().lower()
    actor = await UsuarioRepository(db_session).get_active_by_email(email) if email else None
    if actor is None or actor.rol != Role.SUPERADMIN:
        raise ValueError(
            "No existe el SUPERADMIN de SEED_ADMIN_EMAIL_1; ejecuta antes seeds.user."
        )
    return actor.id


async def _seed_tallas(db_session: AsyncSession, actor_id: UUID) -> int:
    repository = TallaRepository(db_session)
    created = 0
    for etiqueta in SEED_TALLAS:
        if await repository.get_active_by_etiqueta(etiqueta) is not None:
            continue
        await TallaService.create(db_session, TallaCreate(etiqueta=etiqueta), actor_id)
        created += 1
    return created


async def _seed_colores(db_session: AsyncSession, actor_id: UUID) -> int:
    repository = ColorRepository(db_session)
    created = 0
    for nombre, codigo_hex in SEED_COLORES:
        if await repository.get_active_by_slug(generate_slug(nombre)) is not None:
            continue
        await ColorService.create(
            db_session,
            ColorCreate(nombre=nombre, codigo_hex=codigo_hex),
            actor_id,
        )
        created += 1
    return created


async def _get_or_create_categoria(
    db_session: AsyncSession,
    actor_id: UUID,
    seccion_id: UUID,
    parent_id: UUID | None,
    nombre: str,
) -> tuple[UUID, bool]:
    existing = await CategoriaRepository(db_session).get_active_sibling_by_slug(
        seccion_id, parent_id, generate_slug(nombre)
    )
    if existing is not None:
        return existing.id, False

    categoria = await CategoriaService.create(
        db_session,
        CategoriaCreate(seccion_id=seccion_id, parent_id=parent_id, nombre=nombre),
        actor_id,
    )
    return categoria.id, True


async def _seed_secciones_y_categorias(
    db_session: AsyncSession,
    actor_id: UUID,
) -> tuple[int, int]:
    repository = SeccionRepository(db_session)
    secciones_created = 0
    categorias_created = 0

    for nombre, is_visible, categorias in SEED_SECCIONES:
        seccion = await repository.get_active_by_slug(generate_slug(nombre))
        if seccion is None:
            seccion = await SeccionService.create(
                db_session,
                SeccionCreate(nombre=nombre, is_visible=is_visible),
                actor_id,
            )
            secciones_created += 1
        seccion_id = seccion.id

        for raiz, subcategorias in categorias:
            raiz_id, created = await _get_or_create_categoria(
                db_session, actor_id, seccion_id, None, raiz
            )
            categorias_created += created
            for subcategoria in subcategorias:
                _, created = await _get_or_create_categoria(
                    db_session, actor_id, seccion_id, raiz_id, subcategoria
                )
                categorias_created += created

    return secciones_created, categorias_created


async def seed_catalogos(settings: Settings) -> None:
    """Crea tallas, colores, secciones y categorías faltantes; nunca modifica los existentes."""
    if settings.ENVIRONMENT == "production":
        raise RuntimeError("El seed de catálogos no se ejecuta en producción.")

    engine, session_factory = initialize_database(settings)

    try:
        await check_database_connection(engine)

        async with session_factory() as db_session:
            actor_id = await _get_actor_id(db_session, settings)

            tallas = await _seed_tallas(db_session, actor_id)
            colores = await _seed_colores(db_session, actor_id)
            secciones, categorias = await _seed_secciones_y_categorias(db_session, actor_id)

            logger.info(
                "Seed de catálogos finalizado: %s tallas, %s colores, %s secciones y "
                "%s categorías nuevas.",
                tallas,
                colores,
                secciones,
                categorias,
            )
    except Exception:
        logger.exception("Error durante la ejecución del seed de catálogos")
        raise
    finally:
        await close_database(engine)


if __name__ == "__main__":
    app_settings = get_settings()
    setup_logging(app_settings)
    asyncio.run(seed_catalogos(app_settings))
