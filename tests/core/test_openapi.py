from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.core.openapi import setup_openapi


class OpenapiEjemplo(BaseModel):
    zeta: str
    alfa: str | None

    model_config = ConfigDict(json_schema_extra={"example": {"zeta": "z", "alfa": None}})


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/ejemplo", response_model=OpenapiEjemplo)
    async def ejemplo() -> OpenapiEjemplo:
        return OpenapiEjemplo(zeta="z", alfa=None)

    setup_openapi(app)
    return app


def test_conserva_el_orden_y_los_null_del_ejemplo() -> None:
    example = _app().openapi()["components"]["schemas"]["OpenapiEjemplo"]["example"]

    assert list(example) == ["zeta", "alfa"]
    assert example["alfa"] is None


def test_el_documento_se_genera_una_sola_vez() -> None:
    app = _app()

    assert app.openapi() is app.openapi()
