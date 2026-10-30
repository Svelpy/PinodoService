from typing import Any

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
