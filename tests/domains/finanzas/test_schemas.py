import pytest

from app.domains.finanzas.schemas import (
    ReportePeriodo,
    ReporteRentabilidad,
    ReporteRentabilidadLinea,
    ReporteRentabilidadMes,
    ReporteRentabilidadResumen,
    ReporteVentas,
    ReporteVentasLinea,
    ReporteVentasMetodo,
    ReporteVentasResumen,
)


@pytest.mark.parametrize(
    "schema",
    [
        ReportePeriodo,
        ReporteVentasResumen,
        ReporteVentasMetodo,
        ReporteVentasLinea,
        ReporteVentas,
        ReporteRentabilidadResumen,
        ReporteRentabilidadMes,
        ReporteRentabilidadLinea,
        ReporteRentabilidad,
    ],
)
def test_ejemplos_validan_su_schema_con_todos_los_campos(schema: type) -> None:
    example = schema.model_config["json_schema_extra"]["example"]

    assert None not in example.values()
    assert list(example) == list(schema.model_fields)
    schema.model_validate(example)


def test_importes_y_porcentajes_se_exponen_como_numeros() -> None:
    linea = ReporteRentabilidadLinea.model_validate(
        ReporteRentabilidadLinea.model_config["json_schema_extra"]["example"]
    ).model_dump(mode="json")

    assert isinstance(linea["ingreso_neto"], float)
    assert linea["margen_porcentaje"] == pytest.approx(0.5588)
