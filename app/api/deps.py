"""Reusable FastAPI dependencies.

A "dependency" is a function FastAPI runs BEFORE your route. Declare
`user: dict = Depends(get_current_user)` on any route and FastAPI will:
  1. read the Authorization header,
  2. validate the JWT,
  3. load the user from the DB,
  4. either hand your route the user dict, or reject with 401 first.

So protecting a route is one line, and the logic lives here in one place.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api.security import decode_access_token
from db.storage import get_user_by_id

# Parses the "Authorization: Bearer <token>" header for us.
_bearer = HTTPBearer()


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Resolve the logged-in user from the bearer token, or raise 401."""
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已失效或无效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise cred_exc
    user = get_user_by_id(user_id)
    if user is None:          # token valid but user deleted since
        raise cred_exc
    return user
