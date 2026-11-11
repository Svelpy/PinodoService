from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from app.domains.tallas.schemas import TallaResponse
from app.shared.services.validators import (
    validator_barcode,
    validator_boolean,
    validator_date,
    validator_non_negative_integer,
    validator_non_negative_money,
    validator_positive_money,
)


class SkuPrecio(BaseModel):
    """Contenido del JSONB precio. Se usa tanto en la entrada como en la respuesta."""

    normal: Decimal = Field(..., max_digits=10, decimal_places=2)
    rebajado: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    rebaja_hasta: date | None = Field(default=None)

    @field_validator("normal", mode="before")
    @classmethod
    def validate_normal(cls, value: object) -> Decimal:
        if value is None:
            raise ValueError("El precio normal no puede ser null.")
        return validator_positive_money(value)

    @field_validator("rebajado", mode="before")
    @classmethod
    def validate_rebajado(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return validator_positive_money(value)

    @field_validator("rebaja_hasta", mode="before")
    @classmethod
    def validate_rebaja_hasta(cls, value: object) -> date | None:
        if value is None:
            return None
        return validator_date(value)

    @model_validator(mode="after")
    def validate_rebaja(self) -> "SkuPrecio":
        if self.rebajado is not None and self.rebajado >= self.normal:
            raise ValueError("El precio rebajado debe ser menor que el precio normal.")
        if self.rebaja_hasta is not None and self.rebajado is None:
            raise ValueError("rebaja_hasta solo puede indicarse junto con un precio rebajado.")
        return self

    @field_serializer("normal", "rebajado", when_used="json")
    def serialize_money(self, value: Decimal | None) -> float | None:
        # JSONB y la API guardan y exponen los importes como números JSON.
        return None if value is None else float(value)

    def vigente(self, today: date) -> Decimal:
        """
        Precio que se cobra en la fecha today: el rebajado mientras la rebaja
        siga vigente (rebaja_hasta incluido, o sin fecha de fin) y, si no, el normal.
        """
        if self.rebajado is not None and (self.rebaja_hasta is None or self.rebaja_hasta >= today):
            return self.rebajado
        return self.normal

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "normal": 29.95,
                "rebajado": 19.95,
                "rebaja_hasta": "2026-12-31",
            }
        },
    )


class SkuStockInput(BaseModel):
    """Stock que envía el cliente. La fecha actualizado la asigna el service."""

    cantidad: int = Field(default=0, ge=0)
    minimo: int = Field(default=0, ge=0)

    @field_validator("cantidad", "minimo", mode="before")
    @classmethod
    def validate_non_negative(cls, value: object) -> int:
        if value is None:
            raise ValueError("El valor de stock no puede ser null.")
        return validator_non_negative_integer(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "cantidad": 12,
                "minimo": 3,
            }
        },
    )


class SkuStockUpdate(BaseModel):
    """
    Entrada de PATCH /skus/{id}/stock: minimo es el stock a partir del cual el
    SKU aparece como bajo mínimo. La cantidad no se cambia aquí: entra y sale
    con movimientos del kardex (POST /movimientos-inventario/).
    """

    minimo: int = Field(..., ge=0)

    @field_validator("minimo", mode="before")
    @classmethod
    def validate_minimo(cls, value: object) -> int:
        if value is None:
            raise ValueError("El mínimo no puede ser null.")
        return validator_non_negative_integer(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"minimo": 2}},
    )


class SkuStock(BaseModel):
    """Contenido del JSONB stock tal como se expone en la respuesta."""

    cantidad: int
    minimo: int
    actualizado: datetime | None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cantidad": 12,
                "minimo": 3,
                "actualizado": "2026-10-29T15:00:00Z",
            }
        },
    )


class SkuDetailCreate(BaseModel):
    """
    SKU dentro de ProductoColorDetailCreate (create en un solo paso).

    No lleva producto_color_id: lo asigna el service al crear su color. Es la
    base de SkuCreate, para que ambos apliquen las mismas validaciones.

    costo es lo que cuesta cada prenda; no se devuelve en la respuesta del SKU
    (se consulta en GET /movimientos-inventario/costos). stock.cantidad entra
    al kardex como un INGRESO inicial a ese costo.
    """

    talla_id: UUID = Field(...)
    codigo_barras: str | None = Field(default=None, min_length=1, max_length=50)
    is_visible: bool = Field(default=True)
    precio: SkuPrecio = Field(...)
    costo: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    stock: SkuStockInput = Field(default_factory=SkuStockInput)

    @field_validator("codigo_barras", mode="before")
    @classmethod
    def validate_codigo_barras(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_barcode(value)

    @field_validator("is_visible", mode="before")
    @classmethod
    def validate_is_visible(cls, value: object) -> bool:
        if value is None:
            raise ValueError("La visibilidad no puede ser null.")
        return validator_boolean(value)

    @field_validator("costo", mode="before")
    @classmethod
    def validate_costo(cls, value: object) -> Decimal:
        if value is None:
            raise ValueError("El costo no puede ser null.")
        return validator_non_negative_money(value)

    @field_validator("stock", mode="before")
    @classmethod
    def validate_stock(cls, value: object) -> object:
        if value is None:
            raise ValueError("El stock no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "talla_id": "99999999-9999-4999-8999-999999999999",
                "codigo_barras": "8412345678905",
                "is_visible": True,
                "precio": {"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
                "costo": 12.5,
                "stock": {"cantidad": 12, "minimo": 3},
            }
        },
    )


class SkuCreate(SkuDetailCreate):
    """SKU creado de forma individual dentro de un color que ya existe."""

    producto_color_id: UUID = Field(...)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                **SkuDetailCreate.model_config["json_schema_extra"]["example"],
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
            }
        },
    )


class SkuDetailUpdate(SkuDetailCreate):
    """
    Fila de la tabla de tallas en PATCH /producto-colores/{id}: la misma fila
    del formulario de creación, más el id de las que ya existen.

    - Sin id: crea un SKU nuevo, con las mismas reglas que SkuDetailCreate;
      stock es opcional y vale 0 si se omite.
    - Con id: actualiza ese SKU. Solo cambian los campos enviados; precio se
      envía completo y reemplaza al anterior. costo corrige el costo promedio
      sin registrar un movimiento. No admite stock: el de un SKU que ya existe
      entra y sale con movimientos del kardex (POST /movimientos-inventario/),
      para no pisar lo que las ventas descontaron mientras el formulario
      estaba abierto.

    Por esa exclusión, el ejemplo muestra una fila existente y omite stock.
    """

    stock: SkuStockInput | None = Field(default=None)
    id: UUID | None = Field(default=None)

    @model_validator(mode="after")
    def validate_stock_solo_en_nuevas(self) -> "SkuDetailUpdate":
        if self.id is not None and self.stock is not None:
            raise ValueError(
                "El stock de un SKU existente no se cambia aquí; registra un "
                "movimiento en POST /movimientos-inventario/."
            )
        return self

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "talla_id": "99999999-9999-4999-8999-999999999999",
                "codigo_barras": "8412345678905",
                "is_visible": True,
                "precio": {"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
                "costo": 12.5,
                "id": "11111111-1111-4111-8111-111111111111",
            }
        },
    )


class CodigoBarrasSugerido(BaseModel):
    """
    Respuesta de POST /skus/sugerir-codigo-barras: un EAN-13 de uso interno
    (prefijo GS1 20) que ningún SKU usa. No queda reservado.
    """

    codigo_barras: str

    model_config = ConfigDict(
        json_schema_extra={"example": {"codigo_barras": "2001234567893"}},
    )


class SkuResponse(BaseModel):
    id: UUID
    producto_color_id: UUID
    talla_id: UUID
    codigo_barras: str | None
    is_visible: bool
    precio: SkuPrecio
    stock: SkuStock
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
                "talla_id": "99999999-9999-4999-8999-999999999999",
                "codigo_barras": "8412345678905",
                "is_visible": True,
                "precio": {"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
                "stock": {"cantidad": 12, "minimo": 3, "actualizado": "2026-10-29T15:00:00Z"},
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class SkuInventarioItem(SkuResponse):
    """
    SKU con el producto, el color y la talla a los que pertenece, para el
    inventario y la búsqueda en caja.

    Schema especial de lectura: a diferencia de SkuListItem, muestra datos del
    dueño. Son campos planos porque skus no puede importar los schemas de
    productos sin crear un ciclo de imports.

    precio_vigente es el precio que se cobra hoy: el rebajado mientras la rebaja
    esté vigente (rebaja_hasta incluido o sin fecha) y, si no, el normal.
    """

    precio_vigente: Decimal
    producto_id: UUID
    producto_nombre: str
    color_id: UUID
    color_nombre: str
    color_codigo_hex: str
    talla_etiqueta: str

    @field_serializer("precio_vigente", when_used="json")
    def serialize_precio_vigente(self, value: Decimal) -> float:
        return float(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                **SkuResponse.model_config["json_schema_extra"]["example"],
                "precio_vigente": 19.95,
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "producto_nombre": "Camisa Oxford",
                "color_id": "77777777-7777-4777-8777-777777777777",
                "color_nombre": "Azul marino",
                "color_codigo_hex": "#1E3A8A",
                "talla_etiqueta": "M",
            }
        },
    )


class SkuResponseAudit(SkuResponse):
    created_by: UUID | None
    updated_by: UUID | None
    is_deleted: bool
    deleted_at: datetime | None
    deleted_by: UUID | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
                "talla_id": "99999999-9999-4999-8999-999999999999",
                "codigo_barras": "8412345678905",
                "is_visible": True,
                "precio": {"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
                "stock": {"cantidad": 12, "minimo": 3, "actualizado": "2026-10-29T15:00:00Z"},
                "created_at": "2026-10-29T14:30:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-10-29T15:00:00Z",
                "updated_by": "22222222-2222-4222-8222-222222222222",
                "is_deleted": True,
                "deleted_at": "2026-10-30T09:00:00Z",
                "deleted_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )


class SkuListItem(SkuResponse):
    """talla es referencia y se embebe; producto_color_id es dueño y queda como id."""

    talla: TallaResponse

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **SkuResponse.model_json_schema()["example"],
                "talla": TallaResponse.model_json_schema()["example"],
            }
        },
    )


class _ConPrecioVigente:
    """Presenta un Sku con su precio vigente calculado, sin añadir campos al model."""

    def __init__(self, sku: object, precio_vigente: Decimal) -> None:
        self._sku = sku
        self.precio_vigente = precio_vigente

    def __getattr__(self, name: str) -> object:
        return getattr(self._sku, name)


class SkuDetail(SkuListItem):
    """
    Sin hijos propios. Añade precio_vigente, el precio que se cobra hoy (ver
    SkuPrecio.vigente).

    Al construirlo desde un Sku, la fecha de hoy en la zona horaria de la tienda
    llega en el contexto de validación (context={"today": date}), que el service
    obtiene de la configuración; el contexto alcanza también a los SkuDetail
    embebidos en ProductoColorDetail y ProductoDetail.
    """

    precio_vigente: Decimal

    @model_validator(mode="before")
    @classmethod
    def add_precio_vigente(cls, data: object, info: ValidationInfo) -> object:
        if isinstance(data, dict):
            if "precio_vigente" in data:
                return data
            precio = data.get("precio")
        else:
            if "precio_vigente" in getattr(data, "__dict__", {}):
                return data
            precio = getattr(data, "precio", None)

        today = (info.context or {}).get("today")
        if today is None:
            raise ValueError("SkuDetail necesita la fecha de hoy en el contexto para calcular precio_vigente.")
        precio_vigente = SkuPrecio.model_validate(precio).vigente(today)

        if isinstance(data, dict):
            return {**data, "precio_vigente": precio_vigente}
        return _ConPrecioVigente(data, precio_vigente)

    @field_serializer("precio_vigente", when_used="json")
    def serialize_precio_vigente(self, value: Decimal) -> float:
        return float(value)

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **SkuListItem.model_json_schema()["example"],
                "precio_vigente": 19.95,
            }
        },
    )
