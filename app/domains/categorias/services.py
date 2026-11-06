from collections import defaultdict
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.categoria_productos.repositories import CategoriaProductoRepository
from app.domains.categorias.models import Categoria
from app.domains.categorias.repositories import CategoriaRepository
from app.domains.categorias.schemas import (
    CategoriaArbolSeccion,
    CategoriaCreate,
    CategoriaDetail,
    CategoriaListItem,
    CategoriaResponse,
    CategoriaUpdate,
)
from app.domains.secciones.models import Seccion
from app.domains.secciones.repositories import SeccionRepository
from app.domains.secciones.schemas import SeccionResponse
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.schemas.tree import TreeNodeResponse, TreeResponse
from app.shared.services.slug import generate_slug


logger = get_logger(__name__)


class CategoriaService:
    """Reglas de negocio del dominio de categorías."""

    @staticmethod
    def _slug_conflict() -> AppException:
        return AppException(
            "Ya existe una categoría con ese nombre en la sección.",
            409,
            ErrorCode.CONFLICT,
            {"nombre": "Ya existe una categoría con ese nombre en la sección."},
        )

    @staticmethod
    def _invalid_reference(field_name: str, message: str) -> AppException:
        return AppException(message, 422, ErrorCode.VALIDATION_ERROR, {field_name: message})

    @classmethod
    def _integrity_exception(cls, error: IntegrityError) -> AppException:
        original_error = error.orig
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "__cause__", None),
                "constraint_name",
                None,
            )

        if constraint_name == "uq_categorias_seccion_slug":
            return cls._slug_conflict()

        return AppException(
            "Los datos de la categoría entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        categoria: Categoria | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        if categoria is not None:
            await db_session.refresh(categoria)

    @classmethod
    async def _validate_seccion(cls, db_session: AsyncSession, seccion_id: UUID) -> None:
        if await SeccionRepository(db_session).get_by_id(seccion_id) is None:
            raise cls._invalid_reference("seccion_id", "La sección no existe.")

    @classmethod
    async def _validate_parent(
        cls,
        repository: CategoriaRepository,
        parent_id: UUID,
        seccion_id: UUID,
        categoria_id: UUID | None = None,
    ) -> None:
        """
        El padre debe existir, pertenecer a la misma sección, no tener productos
        asignados y, al mover una categoría existente, no ser ella misma ni una
        de sus descendientes.

        Los productos solo se asignan a categorías hoja: si el padre tuviera
        productos, al darle una subcategoría quedarían asignados a un padre.
        """
        if parent_id == categoria_id:
            raise cls._invalid_reference(
                "parent_id",
                "Una categoría no puede ser su propia categoría padre.",
            )

        parent = await repository.get_by_id(parent_id)
        if parent is None:
            raise cls._invalid_reference("parent_id", "La categoría padre no existe.")
        if parent.seccion_id != seccion_id:
            raise cls._invalid_reference(
                "parent_id",
                "La categoría padre pertenece a otra sección.",
            )
        if await repository.has_active_products(parent_id):
            raise AppException(
                "La categoría padre tiene productos asignados.",
                409,
                ErrorCode.CONFLICT,
                {
                    "parent_id": (
                        "Quita antes sus productos: solo las categorías sin "
                        "subcategorías pueden tener productos."
                    )
                },
            )

        if categoria_id is None:
            return

        visited: set[UUID] = set()
        ancestor = parent
        while ancestor.parent_id is not None and ancestor.parent_id not in visited:
            if ancestor.parent_id == categoria_id:
                raise cls._invalid_reference(
                    "parent_id",
                    "La categoría padre no puede ser una de sus subcategorías.",
                )
            visited.add(ancestor.id)
            ancestor = await repository.get_by_id(ancestor.parent_id)
            if ancestor is None:
                return

    @classmethod
    async def _validate_unique_slug(
        cls,
        repository: CategoriaRepository,
        seccion_id: UUID,
        slug: str,
        exclude_id: UUID | None = None,
    ) -> None:
        existing = await repository.get_active_by_slug(seccion_id, slug, exclude_id=exclude_id)
        if existing is not None:
            raise cls._slug_conflict()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        categoria_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> Categoria:
        categoria = await CategoriaRepository(db_session).get_by_id(
            categoria_id,
            include_deleted=include_deleted,
            for_update=for_update,
            load_detail=load_detail,
        )
        if categoria is None:
            raise AppException(
                "Categoría no encontrada.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return categoria

    @staticmethod
    def _build_tree(
        parent_id: UUID | None,
        children_by_parent: dict[UUID | None, list[Categoria]],
    ) -> tuple[list[TreeNodeResponse[CategoriaResponse]], int]:
        """Arma los nodos bajo parent_id y devuelve también cuántos nodos colocó."""
        nodes: list[TreeNodeResponse[CategoriaResponse]] = []
        total = 0
        for categoria in children_by_parent.get(parent_id, []):
            children, children_total = CategoriaService._build_tree(
                categoria.id,
                children_by_parent,
            )
            nodes.append(
                TreeNodeResponse[CategoriaResponse](
                    data=CategoriaResponse.model_validate(categoria),
                    children=children,
                )
            )
            total += 1 + children_total
        return nodes, total

    @staticmethod
    def _filter_by_visibility(
        secciones: list[Seccion],
        categorias: list[Categoria],
        is_visible: bool,
    ) -> tuple[list[Seccion], list[tuple[Categoria, UUID | None]]]:
        """
        Filtra el árbol por visibilidad efectiva y devuelve cada categoría con el
        padre bajo el que se coloca.

        Una categoría es efectivamente visible si ella, todas sus categorías padre
        y su sección son visibles; así, ocultar una categoría o una sección oculta
        también todo lo que cuelga de ella.

        - True: secciones visibles y categorías efectivamente visibles.
        - False: categorías no visibles efectivamente. La raíz de cada rama oculta
          cuelga directamente de su sección, porque su padre visible no se
          incluye. Se incluyen las secciones ocultas y las visibles que tengan
          alguna categoría oculta.
        """
        seccion_visible = {seccion.id: seccion.is_visible for seccion in secciones}
        by_id = {categoria.id: categoria for categoria in categorias}
        efectiva: dict[UUID, bool] = {}

        def visible(categoria: Categoria) -> bool:
            if categoria.id not in efectiva:
                parent = by_id.get(categoria.parent_id) if categoria.parent_id else None
                padre_visible = (
                    visible(parent)
                    if parent is not None
                    else seccion_visible.get(categoria.seccion_id, False)
                )
                efectiva[categoria.id] = padre_visible and categoria.is_visible
            return efectiva[categoria.id]

        seleccion: list[tuple[Categoria, UUID | None]] = []
        for categoria in categorias:
            if visible(categoria) != is_visible:
                continue
            parent_id = categoria.parent_id
            if not is_visible and parent_id is not None and visible(by_id[parent_id]):
                parent_id = None
            seleccion.append((categoria, parent_id))

        if is_visible:
            secciones = [seccion for seccion in secciones if seccion.is_visible]
        else:
            con_ocultas = {categoria.seccion_id for categoria, _ in seleccion}
            secciones = [
                seccion
                for seccion in secciones
                if not seccion.is_visible or seccion.id in con_ocultas
            ]
        return secciones, seleccion

    @classmethod
    async def arbol(
        cls,
        db_session: AsyncSession,
        *,
        seccion_id: UUID | None = None,
        is_visible: bool | None = None,
    ) -> list[CategoriaArbolSeccion]:
        """
        Árbol completo de categorías agrupado por sección.

        Sin seccion_id devuelve todas las secciones, incluidas las que no tienen
        categorías; con seccion_id, solo esa sección (404 si no existe).
        is_visible filtra por visibilidad efectiva (ver _filter_by_visibility).
        """
        seccion_repository = SeccionRepository(db_session)
        if seccion_id is None:
            secciones = await seccion_repository.find_many()
        else:
            seccion = await seccion_repository.get_by_id(seccion_id)
            if seccion is None:
                raise AppException(
                    "Sección no encontrada.",
                    404,
                    ErrorCode.RESOURCE_NOT_FOUND,
                )
            secciones = [seccion]

        categorias = await CategoriaRepository(db_session).list_for_tree(seccion_id)
        if is_visible is None:
            colocadas = [(categoria, categoria.parent_id) for categoria in categorias]
        else:
            secciones, colocadas = cls._filter_by_visibility(secciones, categorias, is_visible)

        children_by_seccion: dict[UUID, dict[UUID | None, list[Categoria]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for categoria, parent_id in colocadas:
            children_by_seccion[categoria.seccion_id][parent_id].append(categoria)

        arbol: list[CategoriaArbolSeccion] = []
        for seccion in secciones:
            nodes, total = cls._build_tree(None, children_by_seccion[seccion.id])
            arbol.append(
                CategoriaArbolSeccion(
                    seccion=SeccionResponse.model_validate(seccion),
                    categorias=TreeResponse[CategoriaResponse](total=total, data=nodes),
                )
            )
        return arbol

    @classmethod
    async def get_detail(cls, db_session: AsyncSession, categoria_id: UUID) -> CategoriaDetail:
        """
        La categoría con su sección y el árbol completo de categorías de esa
        sección, visibles y ocultas. Lo usan GET /{id}, POST y PATCH.
        """
        categoria = await cls.get(db_session, categoria_id, load_detail=True)
        categorias = await CategoriaRepository(db_session).list_for_tree(categoria.seccion_id)

        children_by_parent: dict[UUID | None, list[Categoria]] = defaultdict(list)
        for item in categorias:
            children_by_parent[item.parent_id].append(item)
        nodes, total = cls._build_tree(None, children_by_parent)

        return CategoriaDetail(
            **CategoriaListItem.model_validate(categoria).model_dump(),
            arbol=TreeResponse[CategoriaResponse](total=total, data=nodes),
        )

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        seccion_id: UUID | None = None,
        parent_id: UUID | None = None,
        is_visible: bool | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[CategoriaListItem]:
        if page < 1:
            raise AppException(
                "La página debe ser mayor o igual a 1.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )
        if per_page < 1 or per_page > 100:
            raise AppException(
                "La cantidad por página debe estar entre 1 y 100.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )

        categorias, total = await CategoriaRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            seccion_id=seccion_id,
            parent_id=parent_id,
            is_visible=is_visible,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[CategoriaListItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=categorias,
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: CategoriaCreate,
        actor_id: UUID,
    ) -> CategoriaDetail:
        repository = CategoriaRepository(db_session)
        await cls._validate_seccion(db_session, data.seccion_id)
        if data.parent_id is not None:
            await cls._validate_parent(repository, data.parent_id, data.seccion_id)

        slug = generate_slug(data.nombre)
        await cls._validate_unique_slug(repository, data.seccion_id, slug)

        categoria = Categoria(
            **data.model_dump(),
            slug=slug,
            created_by=actor_id,
            updated_by=actor_id,
        )
        repository.add(categoria)
        await cls._commit(db_session, categoria)

        logger.info("Categoría creada: categoria_id=%s actor_id=%s", categoria.id, actor_id)
        # Responde lo mismo que GET /{id}: se recarga con su Detail, tomando
        # antes el id para no disparar una carga implícita.
        categoria_id = categoria.id
        db_session.expire_all()
        return await cls.get_detail(db_session, categoria_id)

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        categoria_id: UUID,
        data: CategoriaUpdate,
        actor_id: UUID,
    ) -> CategoriaDetail:
        """
        Actualiza una categoría. Si cambia el nombre o la sección se regenera y
        revalida el slug. Una categoría con subcategorías activas o productos
        asignados no cambia de sección.
        """
        changes = data.model_dump(exclude_unset=True)
        categoria = await cls.get(db_session, categoria_id, for_update=bool(changes))
        if not changes:
            return await cls.get_detail(db_session, categoria_id)

        repository = CategoriaRepository(db_session)
        target_seccion_id = changes.get("seccion_id", categoria.seccion_id)
        target_parent_id = changes.get("parent_id", categoria.parent_id)
        seccion_changed = target_seccion_id != categoria.seccion_id

        if seccion_changed:
            await cls._validate_seccion(db_session, target_seccion_id)
            if await repository.has_active_children(categoria.id):
                raise AppException(
                    "No se puede cambiar de sección una categoría con subcategorías activas.",
                    409,
                    ErrorCode.CONFLICT,
                    {"seccion_id": "Mueve o elimina antes sus subcategorías."},
                )
            if await repository.has_active_products(categoria.id):
                raise AppException(
                    "No se puede cambiar de sección una categoría con productos asignados.",
                    409,
                    ErrorCode.CONFLICT,
                    {"seccion_id": "Quita antes sus productos: deben ser de su misma sección."},
                )

        if target_parent_id is not None and (seccion_changed or "parent_id" in changes):
            await cls._validate_parent(
                repository,
                target_parent_id,
                target_seccion_id,
                categoria.id,
            )

        if "nombre" in changes or seccion_changed:
            slug = generate_slug(changes.get("nombre", categoria.nombre))
            await cls._validate_unique_slug(
                repository,
                target_seccion_id,
                slug,
                exclude_id=categoria.id,
            )
            changes["slug"] = slug

        for field_name, value in changes.items():
            setattr(categoria, field_name, value)
        categoria.updated_at = utc_now()
        categoria.updated_by = actor_id
        await cls._commit(db_session, categoria)

        logger.info("Categoría actualizada: categoria_id=%s actor_id=%s", categoria.id, actor_id)
        # Responde lo mismo que GET /{id}: se recarga con su Detail.
        db_session.expire_all()
        return await cls.get_detail(db_session, categoria_id)


    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        categoria_id: UUID,
        actor_id: UUID,
    ) -> Categoria:
        """
        Eliminación lógica (AGENTS.md §5). Se rechaza si tiene subcategorías
        activas; sus productos no se eliminan, solo salen de la categoría.
        """
        categoria = await cls.get(db_session, categoria_id, for_update=True)
        if await CategoriaRepository(db_session).has_active_children(categoria.id):
            raise AppException(
                "No se puede eliminar una categoría con subcategorías activas.",
                409,
                ErrorCode.CONFLICT,
            )

        now = utc_now()
        enlaces = await CategoriaProductoRepository(db_session).soft_delete_by_categoria(
            categoria.id,
            actor_id,
            now,
        )
        categoria.is_deleted = True
        categoria.deleted_at = now
        categoria.deleted_by = actor_id
        categoria.updated_at = now
        categoria.updated_by = actor_id
        await cls._commit(db_session, categoria)

        logger.info(
            "Categoría eliminada: categoria_id=%s enlaces=%s actor_id=%s",
            categoria.id,
            enlaces,
            actor_id,
        )
        return categoria
