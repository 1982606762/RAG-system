"""Single-owner login. No registration, user table, or account selection."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_owner
from api.security import create_access_token, verify_password
from core.config import OWNER_PASSWORD_HASH

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=72)


@router.post("/login")
def login(request: LoginRequest):
    if not verify_password(request.password, OWNER_PASSWORD_HASH):
        raise HTTPException(status_code=401, detail="密码错误")
    return {"access_token": create_access_token(), "token_type": "bearer"}


@router.get("/me", dependencies=[Depends(require_owner)])
def me():
    return {"role": "owner"}
