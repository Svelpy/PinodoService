import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import Settings


password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("dummy-password")


def hash_password(password: str) -> str:
    """Genera el hash seguro de una contraseña."""
    return password_hash.hash(password)


def verify_password(plain_password: str,hashed_password: str) -> bool:
    """Verifica una contraseña contra su hash."""
    try:
        return password_hash.verify(plain_password,hashed_password)
    except UnknownHashError:
        return False


def create_access_token(
    data: dict[str, Any],
    settings: Settings,
    expires_delta: timedelta | None = None,
) -> str:
    """Crea un JWT de acceso."""
    now = datetime.now(timezone.utc)
    
    if expires_delta is not None:
        expire = now + expires_delta
    else: 
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = data.copy()
    payload.update(
        {
            "iat": now,
            "exp": expire,
            "jti": str(uuid4()),
        }
    )

    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_access_token(
    token: str,
    settings: Settings,
) -> dict[str, Any] | None:
    """Decodifica y verifica un JWT de acceso."""

    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except JWTError:
        return None


def create_refresh_token() -> str:
    """Genera un refresh token criptográficamente seguro."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """Genera el hash de un refresh token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_csrf_token(refresh_token: str,settings: Settings) -> str:
    """Genera el token CSRF asociado al refresh token."""
    return hmac.new(settings.CSRF_SECRET_KEY.encode("utf-8"),refresh_token.encode("utf-8"),hashlib.sha256).hexdigest()


def verify_csrf_token(refresh_token: str,csrf_token: str,settings: Settings) -> bool:
    """Verifica de forma segura un token CSRF."""
    expected_token = create_csrf_token(refresh_token,settings)
    return hmac.compare_digest(expected_token,csrf_token)


def create_one_time_token() -> str:
    """Genera un token de un solo uso."""
    return secrets.token_urlsafe(32)


def hash_one_time_token(token: str) -> str:
    """Genera el hash de un token de un solo uso."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()