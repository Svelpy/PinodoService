from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.usuarios.models import Usuario
from app.shared.enums import Role


class UsuarioRepository:
    """Acceso a datos de usuarios. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_by_id(
        self,
        usuario_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Usuario | None:
        statement = select(Usuario).where(Usuario.id == usuario_id)
        if not include_deleted:
            statement = statement.where(Usuario.is_deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_by_email(
        self,
        email: str,
        *,
        exclude_id: UUID | None = None,
    ) -> Usuario | None:
        statement = select(Usuario).where(
            Usuario.email == email,
            Usuario.is_deleted.is_(False),
        )
        if exclude_id is not None:
            statement = statement.where(Usuario.id != exclude_id)

        result = await self.db_session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        rol: Role | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[Usuario], int]:
        filters = []
        if not include_deleted:
            filters.append(Usuario.is_deleted.is_(False))
        if rol is not None:
            filters.append(Usuario.rol == rol)

        total_result = await self.db_session.execute(
            select(func.count()).select_from(Usuario).where(*filters)
        )
        total = int(total_result.scalar_one())

        result = await self.db_session.execute(
            select(Usuario)
            .where(*filters)
            .order_by(Usuario.created_at.desc(), Usuario.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    def add(self, usuario: Usuario) -> None:
        self.db_session.add(usuario)
