from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Formato común de error que consume el frontend."""

    status: Literal["fail", "error"]
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "fail",
                "code": "ERROR_CODE",
                "message": "La solicitud no pudo procesarse.",
                "details": {},
            }
        }
    )
