from datetime import date, datetime

import pytest

from app.shared.services.validators import (
    validator_barcode,
    validator_boolean,
    validator_date,
    validator_hex_color,
    validator_schedule,
    validator_social_links,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(" 1e3a8a ", "#1E3A8A"), ("#ffffff", "#FFFFFF")],
)
def test_hex_color_normaliza(value: str, expected: str) -> None:
    assert validator_hex_color(value) == expected


@pytest.mark.parametrize("value", ["#FFF", "ZZZZZZ", "#1E3A8A0", 123])
def test_hex_color_rechaza_invalidos(value: object) -> None:
    with pytest.raises(ValueError):
        validator_hex_color(value)


def test_barcode_normaliza_espacios_externos() -> None:
    assert validator_barcode(" 8412345678905 ") == "8412345678905"


@pytest.mark.parametrize("value", ["84 123", "", "x" * 51, 8412345678905])
def test_barcode_rechaza_invalidos(value: object) -> None:
    with pytest.raises(ValueError):
        validator_barcode(value)


@pytest.mark.parametrize("value", [True, False])
def test_boolean_acepta_booleanos(value: bool) -> None:
    assert validator_boolean(value) is value


@pytest.mark.parametrize("value", ["true", 1, 0, None])
def test_boolean_rechaza_no_booleanos(value: object) -> None:
    with pytest.raises(ValueError):
        validator_boolean(value)


def test_date_acepta_date_y_texto_iso() -> None:
    assert validator_date("2026-12-31") == date(2026, 12, 31)
    assert validator_date(date(2026, 1, 1)) == date(2026, 1, 1)


@pytest.mark.parametrize("value", [datetime(2026, 1, 1), "31/12/2026", 20261231])
def test_date_rechaza_invalidos(value: object) -> None:
    with pytest.raises(ValueError):
        validator_date(value)


def test_schedule_normaliza_dias_y_horas() -> None:
    result = validator_schedule(
        {"Lunes": "09:00-20:00", "miercoles": " 10:00-14:00 ", "SÁBADO": "10:00-13:30"}
    )

    assert result == {
        "lunes": "09:00-20:00",
        "miércoles": "10:00-14:00",
        "sábado": "10:00-13:30",
    }


@pytest.mark.parametrize(
    "value",
    [
        {"funday": "09:00-20:00"},
        {"lunes": "20:00-09:00"},
        {"lunes": "9-20"},
        {"lunes": "24:00-25:00"},
        {"lunes": "09:00-20:00", "LUNES": "10:00-11:00"},
        ["lunes"],
    ],
)
def test_schedule_rechaza_invalidos(value: object) -> None:
    with pytest.raises(ValueError):
        validator_schedule(value)


def test_social_links_normaliza_red() -> None:
    assert validator_social_links({" Instagram ": "https://instagram.com/tienda"}) == {
        "instagram": "https://instagram.com/tienda"
    }


@pytest.mark.parametrize(
    "value",
    [
        {"instagram": "instagram.com/tienda"},
        {"mi red": "https://x.com"},
        {"instagram": "https://a.com", "Instagram": "https://b.com"},
        "https://instagram.com",
    ],
)
def test_social_links_rechaza_invalidos(value: object) -> None:
    with pytest.raises(ValueError):
        validator_social_links(value)
