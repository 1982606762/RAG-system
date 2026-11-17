"""Password verification and tokens for the one configured owner."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from core.config import (
    JWT_ALGORITHM, JWT_AUDIENCE, JWT_EXPIRE_MINUTES, JWT_ISSUER, JWT_SECRET,
)


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise ValueError("密码至少 12 个字符，且不能超过 72 个 UTF-8 字节")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    # Enforce the byte limit explicitly, including with older bcrypt versions.
    if not password or len(password.encode("utf-8")) > 72:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "owner",
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def verify_access_token(token: str) -> None:
    # A valid signature alone must not grant old multi-user tokens owner access.
    payload = jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        options={"require": ["sub", "iss", "aud", "iat", "exp"]},
    )
    if payload["sub"] != "owner":
        raise jwt.InvalidTokenError("Invalid owner")
