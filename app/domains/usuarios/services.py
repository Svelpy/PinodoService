import asyncio
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_model import utc_now
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.domains.auth.services import AuthService
from app.domains.usuarios.models import Usuario
from app.domains.usuarios.repositories import UsuarioRepository
from app.domains.usuarios.schemas import (
    UsuarioChangePassword,
    UsuarioCreate,
    UsuarioResetPassword,
    UsuarioResponse,
    UsuarioUpdate,
    UsuarioUpdateMe,
)
from app.shared.enums import Role
from app.shared.errors.codes import ErrorCode
from app.shared.errors.exceptions import AppException
from app.shared.schemas.pagination import PaginatedResponse
from app.shared.services.permissions import can_manage_role


logger = get_logger(__name__)


class UsuarioService:
    """Reglas de negocio del dominio de usuarios."""

    @staticmethod
    def _validate_can_manage_role(actor_role: Role, target_role: Role) -> None:
        if not can_manage_role(actor_role, target_role):
            raise AppException(
                "No tienes permisos para administrar usuarios con ese rol.",
                403,
                ErrorCode.PERMISSION_DENIED,
                {"rol": "Solo puedes administrar usuarios con un rol inferior."},
            )

    @staticmethod
    def _email_conflict() -> AppException:
        return AppException(
            "El email ya está registrado.",
            409,
            ErrorCode.CONFLICT,
            {"email": "El email ya está registrado."},
        )

    @classmethod
    def _integrity_exception(cls, error: IntegrityError) -> AppException:
        original_error = error.orig
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "__cause__", None),
                "constraint_name",
                None,
            )

        if constraint_name == "uq_usuarios_email":
            return cls._email_conflict()

        return AppException(
            "Los datos del usuario entran en conflicto con un registro existente.",
            409,
            ErrorCode.CONFLICT,
        )

    @classmethod
    async def _commit(
        cls,
        db_session: AsyncSession,
        usuario: Usuario | None = None,
    ) -> None:
        try:
            await db_session.commit()
        except IntegrityError as error:
            await db_session.rollback()
            raise cls._integrity_exception(error) from error
        except Exception:
            await db_session.rollback()
            raise
        if usuario is not None:
            await db_session.refresh(usuario)

    @classmethod
    async def _validate_unique_email(
        cls,
        repository: UsuarioRepository,
        email: str,
        exclude_id: UUID | None = None,
    ) -> None:
        if await repository.get_active_by_email(email, exclude_id=exclude_id) is not None:
            raise cls._email_conflict()

    @staticmethod
    async def get(
        db_session: AsyncSession,
        usuario_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Usuario:
        usuario = await UsuarioRepository(db_session).get_by_id(
            usuario_id,
            include_deleted=include_deleted,
            for_update=for_update,
        )
        if usuario is None:
            raise AppException(
                "Usuario no encontrado.",
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        return usuario

    @staticmethod
    async def list(
        db_session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        rol: Role | None = None,
        include_deleted: bool = False,
    ) -> PaginatedResponse[UsuarioResponse]:
        if page < 1:
            raise AppException(
                "La página debe ser mayor o igual a 1.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )
        if per_page < 1 or per_page > 100:
            raise AppException(
                "La cantidad por página debe estar entre 1 y 100.",
                422,
                ErrorCode.VALIDATION_ERROR,
            )

        usuarios, total = await UsuarioRepository(db_session).list(
            offset=(page - 1) * per_page,
            limit=per_page,
            rol=rol,
            include_deleted=include_deleted,
        )
        return PaginatedResponse[UsuarioResponse](
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            data=usuarios,
        )

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        data: UsuarioCreate,
        actor_id: UUID,
        actor_role: Role,
    ) -> Usuario:
        cls._validate_can_manage_role(actor_role, data.rol)
        repository = UsuarioRepository(db_session)
        await cls._validate_unique_email(repository, str(data.email))

        password_hash = await asyncio.to_thread(hash_password, data.password)
        usuario = Usuario(
            **data.model_dump(exclude={"password"}),
            password_hash=password_hash,
            created_by=actor_id,
            updated_by=actor_id,
        )
        repository.add(usuario)
        await cls._commit(db_session, usuario)

        logger.info("Usuario creado: usuario_id=%s actor_id=%s", usuario.id, actor_id)
        return usuario

    @classmethod
    async def update(
        cls,
        db_session: AsyncSession,
        usuario_id: UUID,
        data: UsuarioUpdate | UsuarioUpdateMe,
        actor_id: UUID,
        actor_role: Role | None = None,
    ) -> Usuario:
        """
        Actualiza un usuario.

        Con UsuarioUpdate (panel administrativo) se exige actor_role y se valida
        la jerarquía sobre el rol actual y el resultante. Con UsuarioUpdateMe el
        usuario edita sus propios datos y el schema no admite cambiar el rol.
        """
        is_admin_update = isinstance(data, UsuarioUpdate)
        if is_admin_update and actor_role is None:
            raise RuntimeError("El rol del actor es obligatorio.")

        changes = data.model_dump(exclude_unset=True)
        usuario = await cls.get(db_session, usuario_id, for_update=bool(changes))

        if is_admin_update:
            cls._validate_can_manage_role(actor_role, usuario.rol)
            cls._validate_can_manage_role(actor_role, changes.get("rol", usuario.rol))

        if not changes:
            return usuario

        if "email" in changes:
            await cls._validate_unique_email(
                UsuarioRepository(db_session),
                str(changes["email"]),
                exclude_id=usuario.id,
            )

        for field_name, value in changes.items():
            setattr(usuario, field_name, value)
        usuario.updated_at = utc_now()
        usuario.updated_by = actor_id
        await cls._commit(db_session, usuario)

        logger.info("Usuario actualizado: usuario_id=%s actor_id=%s", usuario.id, actor_id)
        return usuario

    @classmethod
    async def delete(
        cls,
        db_session: AsyncSession,
        usuario_id: UUID,
        actor_id: UUID,
        actor_role: Role,
    ) -> Usuario:
        usuario = await cls.get(db_session, usuario_id, for_update=True)
        cls._validate_can_manage_role(actor_role, usuario.rol)

        now = utc_now()
        usuario.is_deleted = True
        usuario.deleted_at = now
        usuario.deleted_by = actor_id
        usuario.updated_at = now
        usuario.updated_by = actor_id

        await AuthService.revoke_for_user(db_session, usuario.id, "user_deleted")
        await cls._commit(db_session, usuario)

        logger.info("Usuario eliminado: usuario_id=%s actor_id=%s", usuario.id, actor_id)
        return usuario

    @classmethod
    async def change_password(
        cls,
        db_session: AsyncSession,
        usuario_id: UUID,
        data: UsuarioChangePassword,
        actor_id: UUID,
    ) -> Usuario:
        usuario = await cls.get(db_session, usuario_id, for_update=True)
        current_password_is_valid = await asyncio.to_thread(
            verify_password,
            data.current_password,
            usuario.password_hash,
        )
        if not current_password_is_valid:
            raise AppException(
                "La contraseña actual no es correcta.",
                400,
                ErrorCode.AUTHENTICATION_FAILED,
                {"current_password": "La contraseña actual no es correcta."},
            )

        if data.new_password == data.current_password:
            raise AppException(
                "La nueva contraseña debe ser diferente de la actual.",
                422,
                ErrorCode.VALIDATION_ERROR,
                {"new_password": "Debe ser diferente de la contraseña actual."},
            )

        usuario.password_hash = await asyncio.to_thread(hash_password, data.new_password)
        usuario.updated_at = utc_now()
        usuario.updated_by = actor_id

        await AuthService.revoke_for_user(db_session, usuario.id, "password_changed")
        await cls._commit(db_session, usuario)

        logger.info("Contraseña cambiada: usuario_id=%s actor_id=%s", usuario.id, actor_id)
        return usuario

    @classmethod
    async def reset_password(
        cls,
        db_session: AsyncSession,
        usuario_id: UUID,
        data: UsuarioResetPassword,
        actor_id: UUID,
        actor_role: Role,
    ) -> Usuario:
        usuario = await cls.get(db_session, usuario_id, for_update=True)
        cls._validate_can_manage_role(actor_role, usuario.rol)

        password_is_unchanged = await asyncio.to_thread(
            verify_password,
            data.new_password,
            usuario.password_hash,
        )
        if password_is_unchanged:
            raise AppException(
                "La nueva contraseña debe ser diferente de la actual.",
                422,
                ErrorCode.VALIDATION_ERROR,
                {"new_password": "Debe ser diferente de la contraseña actual."},
            )

        usuario.password_hash = await asyncio.to_thread(hash_password, data.new_password)
        usuario.updated_at = utc_now()
        usuario.updated_by = actor_id

        await AuthService.revoke_for_user(db_session, usuario.id, "admin_password_reset")
        await cls._commit(db_session, usuario)

        logger.info("Contraseña restablecida: usuario_id=%s actor_id=%s", usuario.id, actor_id)
        return usuario
