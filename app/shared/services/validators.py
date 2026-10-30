import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from app.shared.services.slug import generate_slug


WEEK_DAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


_WEEK_DAYS_BY_KEY = {_strip_accents(day): day for day in WEEK_DAYS}


def validator_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("El nombre debe ser texto.")
    normalized_name = value.strip()
    if not re.fullmatch(r"^[a-zA-ZáéíóúÁÉÍÓÚüÜñÑ\s'-]+$", normalized_name):
        raise ValueError(
            "El nombre solo permite letras, espacios, guiones y apóstrofes."
        )
    return normalized_name


def validator_phone(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("El número de teléfono debe ser texto.")
    normalized_phone = value.strip()
    if not re.fullmatch(r"(?:\d{6,20}|\+\d{6,19})", normalized_phone):
        raise ValueError(
            "El teléfono debe contener entre 6 y 20 dígitos, o comenzar con + seguido de entre 6 y 19 dígitos."
        )
    return normalized_phone


def validator_password(value: object) -> str:
    # Por el tipo de aplicación no se exige una complejidad alta.
    if not isinstance(value, str):
        raise ValueError("La contraseña debe ser texto.")
    if len(value) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    if len(value) > 20:
        raise ValueError("La contraseña debe tener menos de 20 caracteres.")
    return value


def validator_email(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("El email debe ser texto.")
    return value.strip().lower()


def validator_address(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("La dirección debe ser texto.")
    normalized_address = value.strip()
    if not normalized_address:
        raise ValueError("La dirección no puede estar vacía.")
    return normalized_address


def validator_text(value: object) -> str:
    """Normaliza texto libre, incluido el texto vacío."""
    if not isinstance(value, str):
        raise ValueError("El valor debe ser texto.")
    return value.strip()


def validator_non_empty_text(value: object) -> str:
    """Normaliza texto libre y rechaza valores vacíos."""
    normalized_text = validator_text(value)
    if not normalized_text:
        raise ValueError("El texto no puede estar vacío.")
    return normalized_text


def validator_http_url(value: object) -> str:
    """Normaliza una URL HTTP(S) absoluta."""
    if not isinstance(value, str):
        raise ValueError("La URL debe ser texto.")
    normalized_url = value.strip()
    parsed_url = urlparse(normalized_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("La URL debe ser una dirección HTTP o HTTPS válida.")
    return normalized_url


def validator_slug_source(value: object) -> str:
    """Valida texto no vacío capaz de producir un slug."""
    normalized_text = validator_non_empty_text(value)
    if not generate_slug(normalized_text):
        raise ValueError("El texto debe contener al menos una letra o un número válido.")
    return normalized_text


def validator_boolean(value: object) -> bool:
    """Valida un booleano real, sin convertir textos ni números."""
    if not isinstance(value, bool):
        raise ValueError("El valor debe ser verdadero o falso.")
    return value


def validator_non_negative_integer(value: object) -> int:
    """Valida un entero mayor o igual a cero sin aceptar booleanos."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("El valor debe ser un número entero.")
    if value < 0:
        raise ValueError("El valor debe ser mayor o igual a cero.")
    return value


def validator_positive_money(value: object) -> Decimal:
    """Convierte un importe finito y positivo a Decimal."""
    if isinstance(value, bool) or not isinstance(
        value,
        (Decimal, int, float, str),
    ):
        raise ValueError("El importe debe ser un número válido.")
    if isinstance(value, str) and not value.strip():
        raise ValueError("El importe no puede estar vacío.")
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation as error:
        raise ValueError("El importe debe ser un número válido.") from error
    if not amount.is_finite():
        raise ValueError("El importe debe ser finito.")
    if amount <= 0:
        raise ValueError("El importe debe ser mayor que cero.")
    return amount


def validator_date(value: object) -> date:
    """Valida una fecha sin hora, como objeto date o texto ISO AAAA-MM-DD."""
    if isinstance(value, datetime):
        raise ValueError("La fecha no debe incluir hora.")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("La fecha debe tener el formato AAAA-MM-DD.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError("La fecha debe tener el formato AAAA-MM-DD.") from error


def validator_hex_color(value: object) -> str:
    """Normaliza un color hexadecimal al formato #RRGGBB en mayúsculas."""
    if not isinstance(value, str):
        raise ValueError("El código de color debe ser texto.")
    normalized_color = value.strip().upper()
    if not normalized_color.startswith("#"):
        normalized_color = f"#{normalized_color}"
    if not re.fullmatch(r"#[0-9A-F]{6}", normalized_color):
        raise ValueError("El código de color debe tener el formato #RRGGBB.")
    return normalized_color


def validator_barcode(value: object) -> str:
    """Valida un código de barras de letras, dígitos o guiones, sin espacios."""
    if not isinstance(value, str):
        raise ValueError("El código de barras debe ser texto.")
    normalized_code = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,50}", normalized_code):
        raise ValueError(
            "El código de barras solo permite letras, dígitos y guiones, hasta 50 caracteres."
        )
    return normalized_code


def validator_schedule(value: object) -> dict[str, str]:
    """
    Valida el horario semanal {"lunes": "09:00-20:00", ...}.

    Las claves son días de la semana (sin distinguir mayúsculas ni tildes) y se
    normalizan a su forma canónica. Un día ausente se considera cerrado.
    """
    if not isinstance(value, dict):
        raise ValueError("El horario debe ser un objeto con días de la semana.")
    schedule: dict[str, str] = {}
    for raw_day, raw_hours in value.items():
        if not isinstance(raw_day, str):
            raise ValueError("Los días del horario deben ser texto.")
        day = _WEEK_DAYS_BY_KEY.get(_strip_accents(raw_day.strip().lower()))
        if day is None:
            raise ValueError(f"'{raw_day}' no es un día de la semana válido.")
        if day in schedule:
            raise ValueError(f"El día '{day}' está repetido en el horario.")
        if not isinstance(raw_hours, str):
            raise ValueError(f"El horario de '{day}' debe ser texto.")
        hours = raw_hours.strip()
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d", hours):
            raise ValueError(f"El horario de '{day}' debe tener el formato HH:MM-HH:MM.")
        opening, closing = hours.split("-")
        if opening >= closing:
            raise ValueError(f"En '{day}' la hora de apertura debe ser anterior a la de cierre.")
        schedule[day] = hours
    return schedule


def validator_social_links(value: object) -> dict[str, str]:
    """Valida redes sociales {"instagram": "https://...", ...}."""
    if not isinstance(value, dict):
        raise ValueError("Las redes sociales deben ser un objeto red → URL.")
    links: dict[str, str] = {}
    for raw_network, raw_url in value.items():
        if not isinstance(raw_network, str):
            raise ValueError("El nombre de la red social debe ser texto.")
        network = raw_network.strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,30}", network):
            raise ValueError(
                f"'{raw_network}' no es un nombre de red social válido; usa letras, dígitos, '_' o '-'."
            )
        if network in links:
            raise ValueError(f"La red social '{network}' está repetida.")
        links[network] = validator_http_url(raw_url)
    return links
