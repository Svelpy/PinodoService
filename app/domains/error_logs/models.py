from uuid import UUID

from sqlalchemy import Index, Text
from sqlmodel import Field

from app.core.base_model import BaseModel


class ErrorLog(BaseModel, table=True):
    __tablename__ = "errors"
    __table_args__ = (
        Index("ix_errors_created_at", "created_at"),
        {"schema": "public"},
    )

    status: str = Field(default="error", nullable=False)
    message: str = Field(sa_type=Text, nullable=False)
    stack: str = Field(sa_type=Text, nullable=False)
    path: str | None = Field(default=None)
    method: str | None = Field(default=None)
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None, sa_type=Text)
    user_id: UUID | None = Field(default=None)
