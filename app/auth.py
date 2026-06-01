import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import RefreshToken, User


ACCESS_TOKEN_TYPE = "access"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 390000
_TOKEN_SEPARATOR = "."
_PASSWORD_SEPARATOR = "$"
_security = HTTPBearer(auto_error=False)


def _require_auth_secret(settings: Settings) -> str:
    if not settings.auth_token_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account authentication is not configured",
        )
    return settings.auth_token_secret


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign_payload(payload: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return _base64url_encode(signature)


def create_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return _PASSWORD_SEPARATOR.join(
        [
            PASSWORD_HASH_ALGORITHM,
            str(PASSWORD_HASH_ITERATIONS),
            _base64url_encode(salt),
            _base64url_encode(digest),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, encoded_salt, encoded_digest = password_hash.split(_PASSWORD_SEPARATOR, 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False

    if algorithm != PASSWORD_HASH_ALGORITHM:
        return False

    try:
        salt = _base64url_decode(encoded_salt)
        expected_digest = _base64url_decode(encoded_digest)
    except ValueError:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(digest, expected_digest)


def create_access_token(user: User, settings: Settings) -> tuple[str, int]:
    secret = _require_auth_secret(settings)
    now = int(time.time())
    expires_in = settings.access_token_expires_seconds
    payload = {
        "typ": ACCESS_TOKEN_TYPE,
        "sub": str(user.id),
        "username": user.username,
        "iat": now,
        "exp": now + expires_in,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = _base64url_encode(payload_json)
    signature = _sign_payload(encoded_payload, secret)
    return f"{encoded_payload}{_TOKEN_SEPARATOR}{signature}", expires_in


def decode_verified_access_token(token: str, settings: Settings) -> dict[str, Any]:
    secret = _require_auth_secret(settings)
    try:
        encoded_payload, signature = token.split(_TOKEN_SEPARATOR, 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        ) from exc

    expected_signature = _sign_payload(encoded_payload, secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )

    try:
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        ) from exc

    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expired bearer token",
        )

    return payload


def create_refresh_token(settings: Settings) -> tuple[str, RefreshToken]:
    token = secrets.token_urlsafe(48)
    record = RefreshToken(
        token_hash=hash_refresh_token(token),
        expires_at=datetime.utcnow() + timedelta(seconds=settings.refresh_token_expires_seconds),
    )
    return token, record


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def require_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> User:
    _require_auth_secret(settings)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_verified_access_token(credentials.credentials, settings)
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id.isdecimal():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )

    user = await session.get(User, int(user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )
    return user
