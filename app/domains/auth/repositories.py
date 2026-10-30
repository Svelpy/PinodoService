from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.models import AuthSession


class AuthSessionRepository:
    """Acceso a datos de sesiones de autenticación. No hace commit: lo controla el service."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def add(self, auth_session: AuthSession) -> None:
        self.db_session.add(auth_session)
        await self.db_session.flush()

    async def get_by_refresh_token_hash_for_update(
        self,
        refresh_token_hash: str,
    ) -> AuthSession | None:
        result = await self.db_session.execute(
            select(AuthSession)
            .where(
                AuthSession.refresh_token_hash == refresh_token_hash,
                AuthSession.is_deleted.is_(False),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def revoke_family(
        self,
        family_id: UUID,
        reason: str,
        now: datetime,
    ) -> None:
        await self.db_session.execute(
            update(AuthSession)
            .where(
                AuthSession.family_id == family_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.is_deleted.is_(False),
            )
            .values(
                revoked_at=now,
                revocation_reason=reason,
                updated_at=now,
                updated_by=AuthSession.user_id,
            )
        )

    async def revoke_for_user(
        self,
        user_id: UUID,
        reason: str,
        now: datetime,
    ) -> None:
        await self.db_session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.is_deleted.is_(False),
            )
            .values(
                revoked_at=now,
                revocation_reason=reason,
                updated_at=now,
                updated_by=user_id,
            )
        )

    async def rotate(
        self,
        session_id: UUID,
        replaced_by: UUID,
        user_id: UUID,
        now: datetime,
    ) -> bool:
        """Revoca la sesión por rotación solo si sigue vigente. Devuelve si se rotó."""
        result = await self.db_session.execute(
            update(AuthSession)
            .where(
                AuthSession.id == session_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                AuthSession.is_deleted.is_(False),
            )
            .values(
                revoked_at=now,
                last_used_at=now,
                revocation_reason="rotated",
                replaced_by=replaced_by,
                updated_at=now,
                updated_by=user_id,
            )
        )
        return result.rowcount == 1
