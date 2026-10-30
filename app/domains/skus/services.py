from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.domains.skus.schemas import (
    SkuCreate,
    SkuListItem,
    SkuPrecio,
    SkuStockInput,
    SkuUpdate,
)
from app.domains.tallas.repositories import TallaRepository
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse


logger = get_logger(__name__)


class SkuService:
    """Reglas de negocio de los SKUs (color de producto × talla)."""

    @staticmethod
    def _duplicate_talla() -> AppException:
        return AppException(
            "El color del producto ya tiene un SKU con esa talla.",
            409,
            ErrorCode.CONFLICT,
            {"talla_id": "El color del producto ya tiene un SKU con esa talla."},
        )

    @staticmethod
    def _duplicate_codigo_barras() -> AppException:
        return AppException(
            "El código de barras ya está registrado.",
            409,
            ErrorCode.CONFLICT,
            {"codigo_barras": "El código de barras ya está registrado."},
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

        if constraint_name == "uq_skus_color_talla":
            return cls._duplicate_talla()
        if constraint_name == "uq_skus_codigo_barras":
            return cls._duplicate_codigo_barras()

        return AppException(
            "Los datos del SKU entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(cls, db_session: AsyncSession, sku: Sku) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        await db_session.refresh(sku)

    @staticmethod
    def _precio_json(precio: SkuPrecio) -> dict[str, Any]:
        return precio.model_dump(mode="json")

    @staticmethod
    def _stock_json(stock: SkuStockInput) -> dict[str, Any]:
        """El stock se guarda con la fecha de su última modificación."""
        return {**stock.model_dump(), "actualizado": utc_now().isoformat()}

    @classmethod
    async def _validate_talla(cls, db_session: AsyncSession, talla_id: UUID) -> None:
        if await TallaRepository(db_session).get_by_id(talla_id) is None:
            raise cls._invalid_reference("talla_id", "La talla no existe.")

    @classmethod
    async def _validate_unique_talla(
        cls,
        repository: SkuRepository,
        producto_color_id: UUID,
        talla_id: UUID,
        exclude_id: UUID | None = None,
    ) -> None:
        existing = await repository.get_active_by_color_and_talla(
            producto_color_id,
            talla_id,
            exclude_id=exclude_id,
        )
        if existing is not None:
            raise cls._duplicate_talla()

    @classmethod
    async def _validate_unique_codigo_barras(
        cls,
        repository: SkuRepository,
        codigo_barras: str,
        exclude_id: UUID | None = None,
    ) -> None:
        existing = await repository.get_active_by_codigo_barras(
            codigo_barras,
            exclude_id=exclude_id,
        )
        if existing is not None:
            raise cls._duplicate_codigo_barras()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        sku_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
        load_detail: bool = False,
    ) -> Sku:
        sku = await SkuRepository(db_session).get_by_id(
            sku_id,
            include_deleted=include_deleted,
            for_update=for_update,
            load_detail=load_detail,
        )
        if sku is None:
            raise AppException(
                "SKU no encontrado.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return sku

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        producto_color_id: UUID | None = None,
        talla_id: UUID | None = None,
        is_visible: bool | None = None,
        bajo_minimo: bool | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[SkuListItem]:
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

        skus, total = await SkuRepository(db_session).list(
            offset=(page - 1) * per_page,
            limit=per_page,
            producto_color_id=producto_color_id,
            talla_id=talla_id,
            is_visible=is_visible,
            bajo_minimo=bajo_minimo,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[SkuListItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=skus,
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: SkuCreate,
        actor_id: UUID,
    ) -> Sku:
        if await ProductoColorRepository(db_session).get_by_id(data.producto_color_id) is None:
            raise cls._invalid_reference("producto_color_id", "El color del producto no existe.")
        await cls._validate_talla(db_session, data.talla_id)

        repository = SkuRepository(db_session)
        await cls._validate_unique_talla(repository, data.producto_color_id, data.talla_id)
        if data.codigo_barras is not None:
            await cls._validate_unique_codigo_barras(repository, data.codigo_barras)

        sku = Sku(
            **data.model_dump(exclude={"precio", "stock"}),
            precio=cls._precio_json(data.precio),
            stock=cls._stock_json(data.stock),
            created_by=actor_id,
            updated_by=actor_id,
        )
        repository.add(sku)
        await cls._commit(db_session, sku)

        logger.info("SKU creado: sku_id=%s actor_id=%s", sku.id, actor_id)
        return sku

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        sku_id: UUID,
        data: SkuUpdate,
        actor_id: UUID,
    ) -> Sku:
        """
        Actualiza un SKU. precio y stock se reemplazan completos; al enviar stock
        se renueva su fecha de actualización. codigo_barras acepta null.
        """
        changes = data.model_dump(exclude_unset=True, exclude={"precio", "stock"})
        sku = await cls.get(
            db_session,
            sku_id,
            for_update=bool(changes) or data.precio is not None or data.stock is not None,
        )
        repository = SkuRepository(db_session)

        if changes.get("talla_id", sku.talla_id) != sku.talla_id:
            await cls._validate_talla(db_session, changes["talla_id"])
            await cls._validate_unique_talla(
                repository,
                sku.producto_color_id,
                changes["talla_id"],
                exclude_id=sku.id,
            )

        codigo_barras = changes.get("codigo_barras")
        if codigo_barras is not None and codigo_barras != sku.codigo_barras:
            await cls._validate_unique_codigo_barras(repository, codigo_barras, exclude_id=sku.id)

        if data.precio is not None:
            changes["precio"] = cls._precio_json(data.precio)
        if data.stock is not None:
            changes["stock"] = cls._stock_json(data.stock)
        if not changes:
            return sku

        for field_name, value in changes.items():
            setattr(sku, field_name, value)
        sku.updated_at = utc_now()
        sku.updated_by = actor_id
        await cls._commit(db_session, sku)

        logger.info("SKU actualizado: sku_id=%s actor_id=%s", sku.id, actor_id)
        return sku

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        sku_id: UUID,
        actor_id: UUID,
    ) -> Sku:
        sku = await cls.get(db_session, sku_id, for_update=True)

        now = utc_now()
        sku.is_deleted = True
        sku.deleted_at = now
        sku.deleted_by = actor_id
        sku.updated_at = now
        sku.updated_by = actor_id
        await cls._commit(db_session, sku)

        logger.info("SKU eliminado: sku_id=%s actor_id=%s", sku.id, actor_id)
        return sku
