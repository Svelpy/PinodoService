from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.domains.tienda.schemas import (
    TiendaCategoria,
    TiendaColor,
    TiendaConfig,
    TiendaFiltros,
    TiendaImagen,
    TiendaNavegacionSeccion,
    TiendaProductoCard,
    TiendaProductoColor,
    TiendaProductoDetalle,
    TiendaSeccion,
    TiendaSku,
    TiendaTalla,
)


SCHEMAS: list[type[BaseModel]] = [
    TiendaConfig,
    TiendaSeccion,
    TiendaCategoria,
    TiendaNavegacionSeccion,
    TiendaColor,
    TiendaTalla,
    TiendaImagen,
    TiendaSku,
    TiendaProductoColor,
    TiendaProductoCard,
    TiendaProductoDetalle,
    TiendaFiltros,
]

# Lo que la tienda pública nunca expone.
CAMPOS_INTERNOS = {
    "is_visible",
    "is_deleted",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "deleted_at",
    "deleted_by",
    "codigo_barras",
    "stock",
    "cantidad",
    "minimo",
}


def _example(schema: type[BaseModel]) -> dict[str, object]:
    return schema.model_config["json_schema_extra"]["example"]  # type: ignore[index]


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda schema: schema.__name__)
def test_ejemplo_completo_valido_y_sin_null(schema: type[BaseModel]) -> None:
    example = _example(schema)

    instance = schema.model_validate(example)

    assert list(example) == list(schema.model_fields)
    assert instance.model_dump(mode="json") == example


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda schema: schema.__name__)
def test_no_expone_campos_internos(schema: type[BaseModel]) -> None:
    assert not CAMPOS_INTERNOS & set(schema.model_fields)


def test_importes_se_serializan_como_numeros() -> None:
    sku = TiendaSku(
        id=uuid4(),
        talla=TiendaTalla(id=uuid4(), etiqueta="M"),
        precio_normal=Decimal("29.95"),
        precio_vigente=Decimal("19.95"),
        en_rebaja=True,
        rebaja_hasta=None,
        disponible=False,
    )

    data = sku.model_dump(mode="json")

    assert data["precio_normal"] == 29.95
    assert data["precio_vigente"] == 19.95
    assert data["rebaja_hasta"] is None


def test_filtros_sin_productos_admiten_precios_null() -> None:
    filtros = TiendaFiltros(colores=[], tallas=[], precio_min=None, precio_max=None, hay_rebajas=False)

    assert filtros.model_dump(mode="json")["precio_min"] is None
