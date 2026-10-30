from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel


def _models() -> Iterator[type[BaseModel]]:
    pending = list(BaseModel.__subclasses__())
    while pending:
        model = pending.pop()
        pending.extend(model.__subclasses__())
        yield model


def _examples_by_name() -> dict[str, Any]:
    """Ejemplo de json_schema_extra de cada schema, por nombre de clase."""
    examples: dict[str, Any] = {}
    duplicated: set[str] = set()
    for model in _models():
        extra = model.model_config.get("json_schema_extra")
        if not isinstance(extra, dict) or "example" not in extra:
            continue
        if model.__name__ in examples and examples[model.__name__] is not extra["example"]:
            duplicated.add(model.__name__)
        examples[model.__name__] = extra["example"]
    for name in duplicated:
        del examples[name]
    return examples


def setup_openapi(app: FastAPI) -> None:
    """
    Restaura en el OpenAPI los ejemplos tal como están escritos en los schemas.

    Pydantic ordena alfabéticamente las claves de los ejemplos y FastAPI elimina
    sus valores null al generar el documento; aquí se reemplaza cada ejemplo por
    el original para conservar el orden de los campos y sus null.
    """
    generate_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = generate_openapi()
        examples = _examples_by_name()
        for name, component in schema.get("components", {}).get("schemas", {}).items():
            # FastAPI separa en "-Input" y "-Output" los schemas que cambian según el uso.
            example = examples.get(name.removesuffix("-Input").removesuffix("-Output"))
            if example is not None and "example" in component:
                component["example"] = jsonable_encoder(example)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
