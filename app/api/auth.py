"""Authentication routes — register, login, and "who am I".

register/login both return a JWT. The frontend stores the access_token and
sends it on every later request as `Authorization: Bearer <token>`.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.security import hash_password, verify_password, create_access_token
from api.deps import get_current_user
from db.storage import create_user, get_user_by_email

# This router carries its own prefix, so main.py just include_router()s it.
router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthRequest(BaseModel):
    # Using plain str for teaching simplicity. Upgrade to pydantic EmailStr
    # (needs the email-validator package) if you want format validation.
    email: str
    password: str


def _token_response(user: dict) -> dict:
    """Shape every auth success the same way: a token + the public user info."""
    token = create_access_token(user["id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"]},
    }


@router.post("/register")
def register(req: AuthRequest):
    """Create a new account and immediately return a login token."""
    if not req.email.strip() or not req.password:
        raise HTTPException(status_code=400, detail="邮箱和密码不能为空")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if get_user_by_email(req.email):
        raise HTTPException(status_code=409, detail="该邮箱已注册")
    # Store ONLY the hash — the raw password never touches the database.
    user = create_user(req.email, hash_password(req.password))
    return _token_response(user)


@router.post("/login")
def login(req: AuthRequest):
    """Verify credentials and return a fresh login token."""
    user = get_user_by_email(req.email)
    # Same error whether the email is unknown or the password is wrong, so an
    # attacker can't probe which emails exist.
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    return _token_response(user)


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    """Return the current logged-in user. Protected: needs a valid token.

    This is the smallest possible example of a protected route — copy the
    `user: dict = Depends(get_current_user)` pattern onto any endpoint that
    should require login.
    """
    return user
