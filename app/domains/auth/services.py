import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_csrf_token,
    create_refresh_token,
    hash_refresh_token,
    verify_csrf_token,
    verify_password,
)
from app.domains.auth.models import AuthSession
from app.domains.auth.repositories import AuthSessionRepository
from app.domains.auth.schemas import AuthTokens, UserLogin
from app.domains.usuarios.models import Usuario
from app.domains.usuarios.repositories import UsuarioRepository
from app.shared.enums import Role
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException


logger = get_logger(__name__)


class AuthService:

    @staticmethod
    async def _commit(db_session: AsyncSession) -> None:
        try:
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    @staticmethod
    def _get_user_role(user: Usuario) -> Role:
        try:
            return user.rol if isinstance(user.rol, Role) else Role(user.rol)
        except (TypeError, ValueError) as error:
            raise AppException(
                "El rol del usuario no es válido.",
                401,
                ErrorCode.AUTHENTICATION_FAILED,
            ) from error

    @staticmethod
    def _build_session(
        user: Usuario,
        refresh_token: str,
        expires_at: datetime,
        family_id: UUID | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthSession:
        now = datetime.now(timezone.utc)
        return AuthSession(
            user_id=user.id,
            family_id=family_id or uuid4(),
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=expires_at,
            created_at=now,
            created_by=user.id,
            updated_at=now,
            updated_by=user.id,
            is_deleted=False,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    @staticmethod
    def validate_user_access(user: Usuario) -> None:
        """Valida que el usuario no haya sido eliminado."""
        if user.is_deleted:
            raise AppException(
                "Usuario no disponible.",
                401,
                ErrorCode.AUTHENTICATION_FAILED,
            )

    @staticmethod
    async def login(
        db_session: AsyncSession,
        credentials: UserLogin,
        settings: Settings,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthTokens:
        """Autentica un usuario y genera sus tokens."""
        user = await UsuarioRepository(db_session).get_active_by_email(
            str(credentials.email)
        )

        password_hash_to_verify = (
            user.password_hash
            if user is not None and user.password_hash
            else DUMMY_PASSWORD_HASH
        )
        password_is_valid = await asyncio.to_thread(
            verify_password,
            credentials.password,
            password_hash_to_verify,
        )
        if user is None or not password_is_valid:
            raise AppException(
                "Email o contraseña incorrectos.",
                401,
                ErrorCode.AUTHENTICATION_FAILED,
            )

        AuthService.validate_user_access(user)
        role = AuthService._get_user_role(user)

        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "role": role.value,
            },
            settings=settings,
        )

        refresh_token = create_refresh_token()
        csrf_token = create_csrf_token(refresh_token, settings)
        auth_session = AuthService._build_session(
            user=user,
            refresh_token=refresh_token,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await AuthSessionRepository(db_session).add(auth_session)
        await AuthService._commit(db_session)

        logger.info("Inicio de sesión exitoso: user_id=%s", user.id)

        return AuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            csrf_token=csrf_token,
        )

    @staticmethod
    async def revoke_session_family(
        db_session: AsyncSession,
        family_id: UUID,
        reason: str,
    ) -> None:
        await AuthSessionRepository(db_session).revoke_family(
            family_id,
            reason,
            datetime.now(timezone.utc),
        )

    @staticmethod
    async def revoke_for_user(
        db_session: AsyncSession,
        user_id: UUID,
        reason: str,
    ) -> None:
        await AuthSessionRepository(db_session).revoke_for_user(
            user_id,
            reason,
            datetime.now(timezone.utc),
        )

    @staticmethod
    async def refresh(
        db_session: AsyncSession,
        refresh_token: str | None,
        csrf_token: str | None,
        settings: Settings,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthTokens:
        if not refresh_token:
            raise AppException(
                "Refresh token requerido.",
                401,
                ErrorCode.REFRESH_FAILED,
            )
        if not csrf_token or not verify_csrf_token(
            refresh_token,
            csrf_token,
            settings,
        ):
            raise AppException(
                "CSRF token inválido.",
                403,
                ErrorCode.CSRF_INVALID,
            )

        now = datetime.now(timezone.utc)
        session_repository = AuthSessionRepository(db_session)
        auth_session = await session_repository.get_by_refresh_token_hash_for_update(
            hash_refresh_token(refresh_token)
        )

        if auth_session is None:
            raise AppException(
                "Refresh token inválido.",
                401,
                ErrorCode.REFRESH_FAILED,
            )

        if auth_session.revoked_at is not None:
            if (
                auth_session.revocation_reason == "rotated"
                and auth_session.replaced_by is not None
            ):
                await AuthService.revoke_session_family(
                    db_session,
                    auth_session.family_id,
                    "reuse_detected",
                )
                await AuthService._commit(db_session)
                logger.warning(
                    "Reutilización de refresh token detectada: family_id=%s",
                    auth_session.family_id,
                )
            raise AppException(
                "Refresh token ya utilizado.",
                401,
                ErrorCode.REFRESH_FAILED,
            )

        if auth_session.expires_at <= now:
            auth_session.revoked_at = now
            auth_session.last_used_at = now
            auth_session.revocation_reason = "expired"
            auth_session.updated_at = now
            auth_session.updated_by = auth_session.user_id
            await AuthService._commit(db_session)
            raise AppException(
                "Refresh token expirado.",
                401,
                ErrorCode.REFRESH_FAILED,
            )

        user = await UsuarioRepository(db_session).get_by_id(auth_session.user_id)
        if user is None:
            await AuthService.revoke_session_family(
                db_session,
                auth_session.family_id,
                "user_unavailable",
            )
            await AuthService._commit(db_session)
            raise AppException(
                "Refresh token inválido.",
                401,
                ErrorCode.REFRESH_FAILED,
            )

        AuthService.validate_user_access(user)
        role = AuthService._get_user_role(user)
        new_refresh_token = create_refresh_token()
        new_csrf_token = create_csrf_token(new_refresh_token, settings)
        new_session = AuthService._build_session(
            user=user,
            refresh_token=new_refresh_token,
            family_id=auth_session.family_id,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await session_repository.add(new_session)

        rotated = await session_repository.rotate(
            auth_session.id,
            new_session.id,
            user.id,
            now,
        )
        if not rotated:
            await db_session.rollback()
            raise AppException(
                "Refresh token inválido o ya utilizado.",
                401,
                ErrorCode.REFRESH_FAILED,
            )

        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "role": role.value,
            },
            settings=settings,
        )
        await AuthService._commit(db_session)

        logger.info(
            "Sesión renovada: user_id=%s family_id=%s",
            user.id,
            auth_session.family_id,
        )

        return AuthTokens(
            access_token=access_token,
            refresh_token=new_refresh_token,
            csrf_token=new_csrf_token,
        )

    @staticmethod
    async def logout(
        db_session: AsyncSession,
        refresh_token: str | None,
        csrf_token: str | None,
        settings: Settings,
    ) -> None:
        if not refresh_token:
            return
        if not csrf_token or not verify_csrf_token(
            refresh_token,
            csrf_token,
            settings,
        ):
            raise AppException(
                "CSRF token inválido.",
                403,
                ErrorCode.CSRF_INVALID,
            )

        auth_session = await AuthSessionRepository(
            db_session
        ).get_by_refresh_token_hash_for_update(hash_refresh_token(refresh_token))

        if auth_session is None:
            return

        if auth_session.revoked_at is not None:
            if auth_session.revocation_reason == "rotated":
                await AuthService.revoke_session_family(
                    db_session,
                    auth_session.family_id,
                    "logout",
                )
                await AuthService._commit(db_session)
                logger.info(
                    "Familia de sesión cerrada: user_id=%s family_id=%s",
                    auth_session.user_id,
                    auth_session.family_id,
                )
            return

        await AuthService.revoke_session_family(
            db_session,
            auth_session.family_id,
            "logout",
        )
        await AuthService._commit(db_session)

        logger.info(
            "Sesión cerrada: user_id=%s family_id=%s",
            auth_session.user_id,
            auth_session.family_id,
        )
