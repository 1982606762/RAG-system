"""Auth primitives — password hashing (bcrypt) and JWT tokens (PyJWT).

Kept separate from the routes so the hashing/token logic is easy to read,
test, and reuse. Nothing here touches the database or FastAPI.
"""

import datetime

import bcrypt
import jwt

from core.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES


def hash_password(plain: str) -> str:
    """Turn a plaintext password into a bcrypt hash (safe to store in the DB).

    bcrypt works on bytes and only considers the first 72 bytes, which is
    plenty for normal passwords. We decode the result to str for storage.
    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Check a login attempt against the stored hash. Never decrypts —
    bcrypt re-hashes `plain` with the salt baked into `hashed` and compares.
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # bcrypt rejects inputs longer than its 72-byte limit in newer versions.
        return False


def create_access_token(user_id: str) -> str:
    """Sign a JWT that proves 'this user is logged in until exp'.

    The token is NOT encrypted — anyone can read its payload. What they can't
    do is forge one, because they don't have JWT_SECRET to sign it.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,                                   # subject: who it's for
        "iat": now,                                       # issued at
        "exp": now + datetime.timedelta(minutes=JWT_EXPIRE_MINUTES),  # expiry
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Return the user_id from a valid token.

    Raises a jwt.PyJWTError subclass if the token is expired, tampered with,
    or otherwise invalid — the caller turns that into a 401.
    """
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    return payload["sub"]
