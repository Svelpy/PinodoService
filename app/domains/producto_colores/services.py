from collections.abc import Awaitable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domains.ajustes_inventario.services import CargaInicial
from app.domains.colores.repositories import ColorRepository
from app.domains.imagenes.models import Imagen
from app.domains.imagenes.repositories import ImagenRepository
from app.domains.imagenes.schemas import ImagenDetailCreate
from app.domains.imagenes.services import ImagenService
from app.domains.producto_colores.models import ProductoColor
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.producto_colores.schemas import (
    ProductoColorCreate,
    ProductoColorDetail,
    ProductoColorDetailCreate,
    ProductoColorListItem,
    ProductoColorUpdate,
)
from app.domains.productos.repositories import ProductoRepository
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.domains.skus.schemas import SkuDetailUpdate
from app.domains.skus.services import SkuService
from app.integrations.cloudinary import CloudinaryService
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)


class ProductoColorService:
    """Reglas de negocio de los colores de cada producto."""

    @staticmethod
    def _duplicate_color() -> AppException:
        return AppException(
            "El producto ya tiene ese color.",
            409,
            ErrorCode.CONFLICT,
            {"color_id": "El producto ya tiene ese color."},
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

        if constraint_name == "uq_producto_colores_producto_color":
            return cls._duplicate_color()
        # El PATCH del color también crea y edita SKUs.
        if constraint_name == "uq_skus_color_talla":
            return SkuService.duplicate_talla()
        if constraint_name == "uq_skus_codigo_barras":
            return SkuService.duplicate_codigo_barras()

        return AppException(
            "Los datos del color del producto entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        producto_color: ProductoColor | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        if producto_color is not None:
            await db_session.refresh(producto_color)

    @classmethod
    async def validate_color(cls, db_session: AsyncSession, color_id: UUID) -> None:
        if await ColorRepository(db_session).get_by_id(color_id) is None:
            raise cls._invalid_reference("color_id", "El color no existe.")

    @classmethod
    async def _validate_unique_color(
        cls,
        repository: ProductoColorRepository,
        producto_id: UUID,
        color_id: UUID,
        exclude_id: UUID | None = None,
    ) -> None:
        existing = await repository.get_active_by_producto_and_color(
            producto_id,
            color_id,
            exclude_id=exclude_id,
        )
        if existing is not None:
            raise cls._duplicate_color()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        producto_color_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> ProductoColor:
        producto_color = await ProductoColorRepository(db_session).get_by_id(
            producto_color_id,
            include_deleted=include_deleted,
            for_update=for_update,
            load_detail=load_detail,
        )
        if producto_color is None:
            raise AppException(
                "Color del producto no encontrado.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return producto_color

    @staticmethod
    def detail(producto_color: ProductoColor, settings: Settings) -> ProductoColorDetail:
        """
        ProductoColorDetail del color cargado con load_detail, con el precio
        vigente hoy de cada SKU. Lo usan GET /{id}, POST y PATCH.
        """
        return ProductoColorDetail.model_validate(
            producto_color,
            context=SkuService.detail_context(settings),
        )

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
        is_visible: bool | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[ProductoColorListItem]:
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

        producto_colores, total = await ProductoColorRepository(db_session).find_many(
            offset=(page - 1) * per_page,
            limit=per_page,
            producto_id=producto_id,
            color_id=color_id,
            is_visible=is_visible,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[ProductoColorListItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=producto_colores,
        )

    @staticmethod
    def _with_path(path: str, error: AppException) -> AppException:
        """Indica en los detalles del error la ruta dentro del árbol."""
        if path:
            error.details = {f"{path} -> {key}": message for key, message in error.details.items()}
        return error

    @classmethod
    async def _at(cls, path: str, check: Awaitable[None]) -> None:
        """Ejecuta una validación e indica en sus detalles la ruta dentro del árbol."""
        try:
            await check
        except AppException as error:
            raise cls._with_path(path, error)

    @classmethod
    async def validate_detail_create(
        cls,
        db_session: AsyncSession,
        data: ProductoColorDetailCreate,
        settings: Settings,
        *,
        path: str = "",
        valid_talla_ids: set[UUID] | None = None,
    ) -> None:
        """
        Valida un color con sus imágenes y SKUs con las mismas reglas que sus
        create individuales. La unicidad dentro del árbol ya la garantiza el
        schema; la del color en un producto existente la valida quien llama.

        path ubica los errores dentro de un árbol mayor (por ejemplo
        "colores -> 1"); valid_talla_ids evita validar dos veces la misma talla
        cuando se validan varios colores.
        """
        prefix = f"{path} -> " if path else ""
        valid_talla_ids = set() if valid_talla_ids is None else valid_talla_ids

        await cls._at(path, cls.validate_color(db_session, data.color_id))

        for imagen_index, imagen in enumerate(data.imagenes):
            await cls._at(
                f"{prefix}imagenes -> {imagen_index}",
                ImagenService.validate_upload_url(db_session, imagen.url, settings),
            )

        sku_repository = SkuRepository(db_session)
        for sku_index, sku in enumerate(data.skus):
            sku_path = f"{prefix}skus -> {sku_index}"
            if sku.talla_id not in valid_talla_ids:
                await cls._at(sku_path, SkuService.validate_talla(db_session, sku.talla_id))
                valid_talla_ids.add(sku.talla_id)
            if sku.codigo_barras is not None:
                await cls._at(
                    sku_path,
                    SkuService.validate_unique_codigo_barras(sku_repository, sku.codigo_barras),
                )

    @staticmethod
    def upload_destinations(
        producto_color: ProductoColor,
        data: ProductoColorDetailCreate,
    ) -> dict[str, str]:
        """Carpeta de Cloudinary a la que se mueve cada imagen del color al confirmarla."""
        folder = ImagenService.folder_for(producto_color.producto_id, producto_color.id)
        return {imagen.url: folder for imagen in data.imagenes}

    @staticmethod
    def add_detail_create(
        db_session: AsyncSession,
        producto_id: UUID,
        data: ProductoColorDetailCreate,
        actor_id: UUID,
        carga: CargaInicial | None = None,
    ) -> ProductoColor:
        """
        Añade a la sesión el color con sus imágenes y SKUs. No hace commit. El
        stock de sus SKUs entra por carga, el documento INICIAL de la petición;
        si no se recibe, el color crea el suyo.
        """
        audit = {"created_by": actor_id, "updated_by": actor_id}
        producto_color = ProductoColor(
            producto_id=producto_id,
            color_id=data.color_id,
            is_visible=data.is_visible,
            **audit,
        )
        ProductoColorRepository(db_session).add(producto_color)

        imagen_repository = ImagenRepository(db_session)
        for imagen in data.imagenes:
            imagen_repository.add(
                Imagen(producto_color_id=producto_color.id, **imagen.model_dump(), **audit)
            )

        carga = carga or CargaInicial(db_session, actor_id, utc_now())
        for sku in data.skus:
            SkuService.nuevo(db_session, producto_color.id, sku, carga)
        return producto_color

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: ProductoColorCreate,
        actor_id: UUID,
        settings: Settings,
    ) -> ProductoColor:
        """
        Añade a un producto existente un color con sus imágenes y SKUs, en una
        sola transacción. Todo se valida antes de insertar nada.

        Devuelve el color con su Detail cargado.
        """
        if await ProductoRepository(db_session).get_by_id(data.producto_id) is None:
            raise cls._invalid_reference("producto_id", "El producto no existe.")
        await cls._validate_unique_color(
            ProductoColorRepository(db_session), data.producto_id, data.color_id
        )
        await cls.validate_detail_create(db_session, data, settings)

        producto_color = cls.add_detail_create(db_session, data.producto_id, data, actor_id)
        await cls._commit(db_session)
        await CloudinaryService.confirm_pending_uploads(
            cls.upload_destinations(producto_color, data), settings
        )

        logger.info(
            "Color de producto creado: producto_color_id=%s imagenes=%s skus=%s actor_id=%s",
            producto_color.id,
            len(data.imagenes),
            len(data.skus),
            actor_id,
        )
        # Igual que en el create del producto: se expira para cargar el Detail
        # completo, tomando antes el id para no disparar una carga implícita.
        producto_color_id = producto_color.id
        db_session.expire_all()
        return await cls.get(db_session, producto_color_id, load_detail=True)

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        producto_color_id: UUID,
        data: ProductoColorUpdate,
        actor_id: UUID,
        settings: Settings,
    ) -> ProductoColor:
        """
        Edita el color con sus imágenes y SKUs en una sola transacción (ver
        ProductoColorUpdate). Todo se valida antes de cambiar nada; si algo
        falla, no se guarda nada.

        Bloquea el color y después sus SKUs en orden de id, el mismo orden que
        usan las ventas. Devuelve el color con su Detail cargado.
        """
        if not data.model_fields_set:
            return await cls.get(db_session, producto_color_id, load_detail=True)

        producto_color = await cls.get(db_session, producto_color_id, for_update=True)
        cambia_color = data.color_id is not None and data.color_id != producto_color.color_id
        if cambia_color:
            # Corrige la etiqueta: fotos, SKUs y stock siguen siendo los mismos.
            await cls.validate_color(db_session, data.color_id)
            await cls._validate_unique_color(
                ProductoColorRepository(db_session),
                producto_color.producto_id,
                data.color_id,
                exclude_id=producto_color.id,
            )

        toca_skus = bool(data.skus or data.sku_ids_eliminar)
        imagenes = (
            await ImagenRepository(db_session).list_active_by_producto_color(producto_color.id)
            if data.imagenes is not None
            else []
        )
        skus = (
            await SkuRepository(db_session).list_active_by_producto_color(
                producto_color.id, for_update=True
            )
            if toca_skus
            else []
        )

        if data.imagenes is not None:
            await cls._validate_imagenes(db_session, imagenes, data.imagenes, settings)
        if toca_skus:
            await cls._validate_skus(db_session, producto_color.id, skus, data)

        now = utc_now()
        changed = False
        if cambia_color:
            producto_color.color_id = data.color_id
            changed = True
        if data.is_visible is not None and data.is_visible != producto_color.is_visible:
            producto_color.is_visible = data.is_visible
            changed = True
        if changed:
            producto_color.updated_at = now
            producto_color.updated_by = actor_id

        destinations: dict[str, str] = {}
        if data.imagenes is not None:
            imagenes_changed, destinations = await cls._apply_imagenes(
                db_session, producto_color, imagenes, data.imagenes, actor_id, now
            )
            changed = changed or imagenes_changed
        if toca_skus:
            skus_changed = await cls._apply_skus(
                db_session, producto_color.id, skus, data, actor_id, now
            )
            changed = changed or skus_changed

        if changed:
            await cls._commit(db_session)
            await CloudinaryService.confirm_pending_uploads(destinations, settings)
            logger.info(
                "Color de producto actualizado: producto_color_id=%s imagenes_nuevas=%s "
                "skus_eliminados=%s actor_id=%s",
                producto_color_id,
                len(destinations),
                len(data.sku_ids_eliminar or []),
                actor_id,
            )
        # Responde lo mismo que GET /{id}: se recarga con su Detail, también
        # cuando no hubo cambios.
        db_session.expire_all()
        return await cls.get(db_session, producto_color_id, load_detail=True)

    @classmethod
    async def _validate_imagenes(
        cls,
        db_session: AsyncSession,
        actuales: Sequence[Imagen],
        imagenes: Sequence[ImagenDetailCreate],
        settings: Settings,
    ) -> None:
        """Las imágenes que ya tiene el color se conservan; las nuevas se validan como en el create."""
        urls_actuales = {imagen.url for imagen in actuales}
        for index, imagen in enumerate(imagenes):
            if imagen.url not in urls_actuales:
                await cls._at(
                    f"imagenes -> {index}",
                    ImagenService.validate_upload_url(db_session, imagen.url, settings),
                )

    @staticmethod
    async def _apply_imagenes(
        db_session: AsyncSession,
        producto_color: ProductoColor,
        actuales: Sequence[Imagen],
        imagenes: Sequence[ImagenDetailCreate],
        actor_id: UUID,
        now: datetime,
    ) -> tuple[bool, dict[str, str]]:
        """
        Reemplaza la galería emparejando por url. Devuelve si hubo cambios y la
        carpeta de Cloudinary de cada imagen nueva, para confirmarla tras el commit.
        """
        repository = ImagenRepository(db_session)
        por_url = {imagen.url: imagen for imagen in actuales}
        enviadas = {imagen.url for imagen in imagenes}
        quitadas = [imagen.id for imagen in actuales if imagen.url not in enviadas]
        await repository.soft_delete_by_ids(quitadas, actor_id, now)

        changed = bool(quitadas)
        folder = ImagenService.folder_for(producto_color.producto_id, producto_color.id)
        destinations: dict[str, str] = {}
        for posicion, imagen in enumerate(imagenes):
            actual = por_url.get(imagen.url)
            if actual is None:
                # Dentro de un mismo tipo, la galería se ordena por created_at:
                # cada imagen nueva recibe un instante distinto para conservar
                # el orden enviado aunque el reloj repita el mismo instante.
                created_at = now + timedelta(microseconds=posicion)
                repository.add(
                    Imagen(
                        producto_color_id=producto_color.id,
                        **imagen.model_dump(),
                        created_at=created_at,
                        created_by=actor_id,
                        updated_at=created_at,
                        updated_by=actor_id,
                    )
                )
                destinations[imagen.url] = folder
                changed = True
            elif actual.tipo != imagen.tipo:
                actual.tipo = imagen.tipo
                actual.updated_at = now
                actual.updated_by = actor_id
                changed = True
        return changed, destinations

    @staticmethod
    def _codigo_final(fila: SkuDetailUpdate, actual: Sku | None) -> str | None:
        """Código de barras que tendrá la fila: en un SKU existente, solo cambia si se envía."""
        if actual is None or "codigo_barras" in fila.model_fields_set:
            return fila.codigo_barras
        return actual.codigo_barras

    @staticmethod
    def _intercambio(field_name: str) -> AppException:
        message = (
            "Otro SKU de este color tiene ese valor y también lo cambia en esta "
            "petición; haz el intercambio en dos guardados."
        )
        return AppException(message, 422, ErrorCode.VALIDATION_ERROR, {field_name: message})

    @classmethod
    async def _validate_skus(
        cls,
        db_session: AsyncSession,
        producto_color_id: UUID,
        actuales: Sequence[Sku],
        data: ProductoColorUpdate,
    ) -> None:
        """
        Valida las filas con las mismas reglas que los create y PATCH
        individuales del SKU, sobre el estado final del color: las tallas y los
        códigos que liberan los SKUs eliminados quedan disponibles.
        """
        por_id = {sku.id: sku for sku in actuales}
        eliminar = set(data.sku_ids_eliminar or [])
        ajenos = [str(sku_id) for sku_id in data.sku_ids_eliminar or [] if sku_id not in por_id]
        if ajenos:
            message = "Estos SKUs no existen o no pertenecen al color: " + ", ".join(ajenos)
            raise cls._invalid_reference("sku_ids_eliminar", message)

        filas = data.skus or []
        restantes = [sku for sku in actuales if sku.id not in eliminar]
        talla_de = {sku.talla_id: sku for sku in restantes}
        codigo_de = {sku.codigo_barras: sku for sku in restantes if sku.codigo_barras is not None}
        fila_de = {fila.id: fila for fila in filas if fila.id is not None}

        sku_repository = SkuRepository(db_session)
        tallas_validas: set[UUID] = set()
        for index, fila in enumerate(filas):
            path = f"skus -> {index}"
            actual = None
            if fila.id is not None:
                actual = por_id.get(fila.id)
                if actual is None:
                    raise cls._invalid_reference(
                        f"{path} -> id", "El SKU no existe o no pertenece a este color."
                    )

            if actual is None or fila.talla_id != actual.talla_id:
                if fila.talla_id not in tallas_validas:
                    await cls._at(path, SkuService.validate_talla(db_session, fila.talla_id))
                    tallas_validas.add(fila.talla_id)
                titular = talla_de.get(fila.talla_id)
                if titular is not None and titular is not actual:
                    otra = fila_de.get(titular.id)
                    if otra is not None and otra.talla_id != titular.talla_id:
                        raise cls._intercambio(f"{path} -> talla_id")
                    raise cls._with_path(path, SkuService.duplicate_talla())

            codigo = cls._codigo_final(fila, actual)
            if codigo is not None and (actual is None or codigo != actual.codigo_barras):
                titular = codigo_de.get(codigo)
                if titular is not None and titular is not actual:
                    otra = fila_de.get(titular.id)
                    if otra is not None and cls._codigo_final(otra, titular) != codigo:
                        raise cls._intercambio(f"{path} -> codigo_barras")
                    raise cls._with_path(path, SkuService.duplicate_codigo_barras())
                existente = await sku_repository.get_active_by_codigo_barras(codigo)
                # Un código de este mismo color lo resuelven las reglas anteriores
                # (o queda libre porque su SKU se elimina en esta petición).
                if existente is not None and existente.producto_color_id != producto_color_id:
                    raise cls._with_path(path, SkuService.duplicate_codigo_barras())

            if actual is not None:
                try:
                    SkuService.replace_precio(actual.precio, fila.precio)
                except AppException as error:
                    raise cls._with_path(path, error) from error

    @staticmethod
    async def _apply_skus(
        db_session: AsyncSession,
        producto_color_id: UUID,
        actuales: Sequence[Sku],
        data: ProductoColorUpdate,
        actor_id: UUID,
        now: datetime,
    ) -> bool:
        """
        Aplica las filas ya validadas: primero elimina, para liberar tallas y
        códigos, después actualiza y al final crea. Devuelve si hubo cambios.
        """
        repository = SkuRepository(db_session)
        eliminados = await repository.soft_delete_by_ids(data.sku_ids_eliminar or [], actor_id, now)
        changed = eliminados > 0

        por_id = {sku.id: sku for sku in actuales}
        carga = CargaInicial(db_session, actor_id, now)
        for fila in data.skus or []:
            if fila.id is None:
                SkuService.nuevo(db_session, producto_color_id, fila, carga)
                changed = True
                continue

            sku = por_id[fila.id]
            enviados = fila.model_fields_set & {"talla_id", "codigo_barras", "is_visible", "costo"}
            cambios = {
                field_name: value
                for field_name, value in fila.model_dump(include=enviados).items()
                if getattr(sku, field_name) != value
            }
            precio = SkuService.replace_precio(sku.precio, fila.precio)
            if precio != sku.precio:
                cambios["precio"] = precio
            # De un SKU existente solo cambia el mínimo; la cantidad va por el kardex.
            if fila.stock is not None and fila.stock.minimo != sku.stock.get("minimo"):
                cambios["stock"] = {**sku.stock, "minimo": fila.stock.minimo, "actualizado": now.isoformat()}
            if cambios:
                for field_name, value in cambios.items():
                    setattr(sku, field_name, value)
                sku.updated_at = now
                sku.updated_by = actor_id
                changed = True
        return changed


    @staticmethod
    async def delete_children(
        db_session: AsyncSession,
        producto_color_ids: Sequence[UUID],
        actor_id: UUID,
        now: datetime,
    ) -> None:
        """
        Elimina lógicamente en cascada las imágenes y SKUs de esos colores de
        producto (AGENTS.md §5). No hace commit: lo hace quien coordina el borrado.
        """
        imagenes = await ImagenRepository(db_session).soft_delete_by_producto_color_ids(
            producto_color_ids,
            actor_id,
            now,
        )
        skus = await SkuRepository(db_session).soft_delete_by_producto_color_ids(
            producto_color_ids,
            actor_id,
            now,
        )
        logger.info(
            "Cascada de colores de producto: producto_color_ids=%s imagenes=%s skus=%s",
            list(producto_color_ids),
            imagenes,
            skus,
        )

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        producto_color_id: UUID,
        actor_id: UUID,
    ) -> ProductoColor:
        """
        Eliminación lógica en cascada: también elimina sus imágenes y SKUs. Los
        archivos de las imágenes se conservan en Cloudinary.
        """
        producto_color = await cls.get(db_session, producto_color_id, for_update=True)

        now = utc_now()
        await cls.delete_children(db_session, [producto_color.id], actor_id, now)
        producto_color.is_deleted = True
        producto_color.deleted_at = now
        producto_color.deleted_by = actor_id
        producto_color.updated_at = now
        producto_color.updated_by = actor_id
        await cls._commit(db_session, producto_color)

        logger.info(
            "Color de producto eliminado: producto_color_id=%s actor_id=%s",
            producto_color.id,
            actor_id,
        )
        return producto_color
