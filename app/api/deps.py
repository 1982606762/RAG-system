"""Authentication boundary shared by all future private routes."""

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.security import verify_access_token

_bearer = HTTPBearer(auto_error=False)


def require_owner(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    error = HTTPException(
        status_code=401,
        detail="请登录后访问",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise error
    try:
        verify_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise error from exc
