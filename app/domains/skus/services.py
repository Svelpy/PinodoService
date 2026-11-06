from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.domains.producto_colores.repositories import ProductoColorRepository
from app.domains.skus.models import Sku
from app.domains.skus.repositories import SkuRepository
from app.domains.skus.schemas import (
    SkuCreate,
    SkuDetail,
    SkuInventarioItem,
    SkuListItem,
    SkuPrecio,
    SkuPrecioUpdate,
    SkuResponse,
    SkuStockInput,
    SkuStockUpdate,
    SkuUpdate,
)
from app.domains.tallas.repositories import TallaRepository
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.services.validators import validator_barcode


logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


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
    def precio_json(precio: SkuPrecio) -> dict[str, Any]:
        return precio.model_dump(mode="json")

    @staticmethod
    def stock_json(stock: SkuStockInput) -> dict[str, Any]:
        """El stock se guarda con la fecha de su última modificación."""
        return {**stock.model_dump(), "actualizado": utc_now().isoformat()}

    @staticmethod
    def _merged(schema: type[ModelT], field_name: str, values: dict[str, Any]) -> ModelT:
        """Valida el valor resultante de combinar lo guardado con lo enviado."""
        try:
            return schema.model_validate(values)
        except ValidationError as error:
            item = error.errors()[0]
            message = str((item.get("ctx") or {}).get("error") or item["msg"])
            raise AppException(
                message,
                422,
                ErrorCode.VALIDATION_ERROR,
                {field_name: message},
            ) from error

    @classmethod
    def _merge_precio(cls, current: dict[str, Any], update: SkuPrecioUpdate) -> SkuPrecio:
        changes = update.model_dump(exclude_unset=True)
        if "rebajado" in changes and changes["rebajado"] is None:
            # Quitar la rebaja quita también su fecha.
            changes["rebaja_hasta"] = None
        precio = cls._merged(SkuPrecio, "precio", {**current, **changes})

        # Al tocar la rebaja, la fecha que se conserva no puede haber vencido:
        # si no, la rebaja nueva no se aplicaría nunca y nadie lo notaría.
        toca_rebaja = "rebajado" in changes or "rebaja_hasta" in changes
        if (
            toca_rebaja
            and precio.rebaja_hasta is not None
            and precio.rebaja_hasta < cls.local_today(get_settings())
        ):
            message = (
                "La fecha de fin de la rebaja ya pasó; envía una nueva "
                "rebaja_hasta o null para que no venza."
            )
            raise AppException(message, 422, ErrorCode.VALIDATION_ERROR, {"precio": message})
        return precio

    @classmethod
    def _merge_stock(cls, current: dict[str, Any], update: SkuStockUpdate) -> SkuStockInput:
        merged = {
            "cantidad": current.get("cantidad", 0),
            "minimo": current.get("minimo", 0),
            **update.model_dump(exclude_unset=True),
        }
        return cls._merged(SkuStockInput, "stock", merged)

    @classmethod
    async def validate_talla(cls, db_session: AsyncSession, talla_id: UUID) -> None:
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
    async def validate_unique_codigo_barras(
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

        skus, total = await SkuRepository(db_session).find_many(
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

    @staticmethod
    def local_today(settings: Settings) -> date:
        """Fecha actual en la zona horaria de la tienda, para decidir si una rebaja sigue vigente."""
        return (utc_now() + timedelta(hours=settings.TIMEZONE_OFFSET_HOURS)).date()

    @staticmethod
    def precio_vigente(precio: SkuPrecio, today: date) -> Decimal:
        """El rebajado mientras la rebaja siga vigente (rebaja_hasta incluido); si no, el normal."""
        return precio.vigente(today)

    @classmethod
    def detail_context(cls, settings: Settings) -> dict[str, date]:
        """
        Contexto de validación para construir SkuDetail, también embebido en
        ProductoColorDetail y ProductoDetail: la fecha de hoy en la tienda.
        """
        return {"today": cls.local_today(settings)}

    @classmethod
    def detail(cls, sku: Sku, settings: Settings) -> SkuDetail:
        """SkuDetail del SKU, con su precio vigente hoy. Lo usan GET /{id}, POST y PATCH."""
        return SkuDetail.model_validate(sku, context=cls.detail_context(settings))

    @classmethod
    async def list_inventario(
        cls,
        db_session: AsyncSession,
        settings: Settings,
        *,
        page: int = 1,
        per_page: int = 20,
        codigo_barras: str | None = None,
        nombre: str | None = None,
        producto_id: UUID | None = None,
        color_id: UUID | None = None,
        talla_id: UUID | None = None,
        is_visible: bool | None = None,
        bajo_minimo: bool | None = None,
        sin_codigo_barras: bool | None = None,
        en_rebaja: bool | None = None,
    ) -> PaginatedResponse[SkuInventarioItem]:
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
        if codigo_barras is not None:
            # El código escaneado se normaliza igual que al guardarlo.
            try:
                codigo_barras = validator_barcode(codigo_barras)
            except ValueError as error:
                raise AppException(
                    str(error),
                    422,
                    ErrorCode.VALIDATION_ERROR,
                    {"codigo_barras": str(error)},
                ) from error

        today = cls.local_today(settings)
        rows, total = await SkuRepository(db_session).list_inventario(
            offset=(page - 1) * per_page,
            limit=per_page,
            today=today,
            codigo_barras=codigo_barras,
            nombre=nombre.strip() if nombre else None,
            producto_id=producto_id,
            color_id=color_id,
            talla_id=talla_id,
            is_visible=is_visible,
            bajo_minimo=bajo_minimo,
            sin_codigo_barras=sin_codigo_barras,
            en_rebaja=en_rebaja,
        )

        items = []
        for sku, row_producto_id, producto_nombre, row_color_id, color_nombre, color_hex, talla in rows:
            response = SkuResponse.model_validate(sku)
            items.append(
                SkuInventarioItem(
                    **response.model_dump(),
                    precio_vigente=cls.precio_vigente(response.precio, today),
                    producto_id=row_producto_id,
                    producto_nombre=producto_nombre,
                    color_id=row_color_id,
                    color_nombre=color_nombre,
                    color_codigo_hex=color_hex,
                    talla_etiqueta=talla,
                )
            )
        return PaginatedResponse[SkuInventarioItem](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=items,
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
        await cls.validate_talla(db_session, data.talla_id)

        repository = SkuRepository(db_session)
        await cls._validate_unique_talla(repository, data.producto_color_id, data.talla_id)
        if data.codigo_barras is not None:
            await cls.validate_unique_codigo_barras(repository, data.codigo_barras)

        sku = Sku(
            **data.model_dump(exclude={"precio", "stock"}),
            precio=cls.precio_json(data.precio),
            stock=cls.stock_json(data.stock),
            created_by=actor_id,
            updated_by=actor_id,
        )
        repository.add(sku)
        await cls._commit(db_session, sku)

        logger.info("SKU creado: sku_id=%s actor_id=%s", sku.id, actor_id)
        # Responde lo mismo que GET /{id}: se recarga con su Detail, tomando
        # antes el id para no disparar una carga implícita.
        sku_id = sku.id
        db_session.expire_all()
        return await cls.get(db_session, sku_id, load_detail=True)

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        sku_id: UUID,
        data: SkuUpdate,
        actor_id: UUID,
    ) -> Sku:
        """
        Actualiza un SKU. Dentro de precio y stock solo cambia lo enviado; el
        resultado se valida con las mismas reglas que al crear. Al enviar stock
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
            await cls.validate_talla(db_session, changes["talla_id"])
            await cls._validate_unique_talla(
                repository,
                sku.producto_color_id,
                changes["talla_id"],
                exclude_id=sku.id,
            )

        codigo_barras = changes.get("codigo_barras")
        if codigo_barras is not None and codigo_barras != sku.codigo_barras:
            await cls.validate_unique_codigo_barras(repository, codigo_barras, exclude_id=sku.id)

        # Precio y stock solo se guardan si cambian: así stock.actualizado
        # conserva la fecha del último cambio real.
        if data.precio is not None:
            precio = cls.precio_json(cls._merge_precio(sku.precio, data.precio))
            if precio != sku.precio:
                changes["precio"] = precio
        if data.stock is not None:
            stock = cls._merge_stock(sku.stock, data.stock)
            if stock.model_dump() != {key: sku.stock.get(key, 0) for key in ("cantidad", "minimo")}:
                changes["stock"] = cls.stock_json(stock)
        if not changes:
            return await cls.get(db_session, sku_id, load_detail=True)

        for field_name, value in changes.items():
            setattr(sku, field_name, value)
        sku.updated_at = utc_now()
        sku.updated_by = actor_id
        await cls._commit(db_session, sku)

        logger.info("SKU actualizado: sku_id=%s actor_id=%s", sku.id, actor_id)
        # Responde lo mismo que GET /{id}: se recarga con su Detail.
        db_session.expire_all()
        return await cls.get(db_session, sku_id, load_detail=True)


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
