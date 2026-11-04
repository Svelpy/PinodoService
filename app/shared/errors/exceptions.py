from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

class AppException(Exception):
    """
    Excepción personalizada para errores operacionales esperados.

    ``code`` y ``details`` son opcionales para mantener compatibilidad con
    las llamadas existentes. Cuando no se proporcionan, el manejador global
    utiliza ``APP_ERROR`` y un objeto de detalles vacío.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code or "APP_ERROR"
        self.details = details or {}
        self.is_operational = True


def body_validation_error(
    error: ValidationError,
    renamed_fields: dict[str, str] | None = None,
) -> RequestValidationError:
    """
    Convierte la validación manual de un schema (por ejemplo, de un formulario)
    en el mismo 422 traducido que produce FastAPI con el body.

    renamed_fields permite informar un campo con el nombre que usa el cliente.
    """
    renamed_fields = renamed_fields or {}
    return RequestValidationError(
        [
            {
                **item,
                "loc": ("body", *(renamed_fields.get(str(part), part) for part in item["loc"])),
            }
            for item in error.errors()
        ]
    )
