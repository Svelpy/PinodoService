import time
import traceback
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.shared.errors.exceptions import AppException
from app.core.logging import get_logger
from app.domains.error_logs.models import ErrorLog


logger = get_logger(__name__)

def _translate_validation_message(error: dict[str, Any]) -> str:
    error_type = error.get("type", "")
    context = error.get("ctx") or {}
    if error_type == "value_error":
        original_error = context.get("error")
        if original_error is not None:
            return str(original_error)
        return str(error.get("msg", "")).removeprefix("Value error, ")

    translations = {
        "uuid_parsing": "El valor debe ser un identificador UUID válido.",
        "uuid_type": "El valor debe ser un identificador UUID válido.",
        "missing": "Este campo es obligatorio.",
        "greater_than": (f"El valor debe ser mayor que {context.get('gt')}."),
        "greater_than_equal": (f"El valor debe ser mayor o igual que {context.get('ge')}."),
        "less_than": (f"El valor debe ser menor que {context.get('lt')}."),
        "less_than_equal": (f"El valor debe ser menor o igual que {context.get('le')}."),
        "int_parsing": "El valor debe ser un número entero válido.",
        "float_parsing": "El valor debe ser un número válido.",
        "decimal_parsing": "El valor debe ser un número decimal válido.",
        "string_type": "El valor debe ser texto.",
        "string_too_short": (f"El texto debe contener al menos {context.get('min_length')} caracteres."        ),
        "string_too_long": (f"El texto no debe superar {context.get('max_length')} caracteres."        ),
        "decimal_max_places": (f"El importe no debe tener más de {context.get('decimal_places')} decimales."),
    }

    return translations.get(error_type, str(error.get("msg", "")))

def register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    """Registra los handlers globales de errores."""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request,exc: AppException,) -> JSONResponse:
        headers = {}
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            headers["WWW-Authenticate"] = "Bearer"

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "fail",
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request,exc: RequestValidationError) -> JSONResponse:
        errors_details = {
            " -> ".join(str(x) for x in error["loc"][1:])
            if len(error["loc"]) > 1
            else str(error["loc"][0]): _translate_validation_message(error)
            for error in exc.errors()
        }

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "status": "fail",
                "code": "VALIDATION_ERROR",
                "message": "Los datos enviados no son válidos.",
                "details": errors_details,
            },
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, _exc: RateLimitExceeded) -> JSONResponse:
        rate_limit, identifiers = request.state.view_rate_limit
        limiter = request.app.state.limiter
        reset_at, remaining = limiter.limiter.get_window_stats(rate_limit,*identifiers)
        retry_after = max(int(reset_at - time.time()), 1)

        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "status": "fail",
                "code": "HTTP_429",
                "message": "Demasiadas solicitudes. Intenta nuevamente más tarde.",
                "details": {},
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(rate_limit.amount),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(int(reset_at)),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request,exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "fail",
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
                "details": {},
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request,exc: Exception) -> JSONResponse:
        stack_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.error("Error crítico detectado: %s\n%s", exc, stack_trace)
        
        if settings.DEBUG:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "status": "error",
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "details": {"stack": stack_trace},
                },
            )

        try:
            session_factory = getattr(request.app.state,"db_session_factory",None)
            if session_factory is None:
                raise RuntimeError("La fábrica de sesiones no está inicializada")
            user_id = None
            if hasattr(request.state, "user"):
                user_id = request.state.user.id

            error_log = ErrorLog(
                status="error",
                message=str(exc),
                stack=stack_trace,
                path=request.url.path,
                method=request.method,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                user_id=user_id,
            )

            async with session_factory() as session:
                session.add(error_log)
                await session.commit()    
        except Exception:
            logger.exception("No se pudo persistir el error interno en PostgreSQL")

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "code": "INTERNAL_ERROR",
                "message": "Ocurrió un error interno.",
                "details": {},
            },
        )
