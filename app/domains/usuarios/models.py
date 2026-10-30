from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import Index, text
from sqlmodel import Field

from app.core.base_model import BaseModel
from app.shared.enums import Role


class Usuario(BaseModel, table=True):
    __tablename__ = "usuarios"
    __table_args__ = (
        Index(
            "uq_usuarios_email",
            "email",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "public"},
    )

    email: str = Field(max_length=255, nullable=False)
    password_hash: str = Field(max_length=255, nullable=False)
    nombre: str = Field(max_length=100, nullable=False)
    apellidos: str | None = Field(default=None, max_length=150, nullable=True)
    telefono: str | None = Field(default=None, max_length=30, nullable=True)
    rol: Role = Field(sa_type=SQLAlchemyEnum(Role,name="rol_usuario",native_enum=False,create_constraint=True,length=20,),nullable=False)
