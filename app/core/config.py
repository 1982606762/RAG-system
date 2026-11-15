"""Configuration for the single-owner application shell."""

import os
from pathlib import Path

import bcrypt

# Empty DSN lets libpq use PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD.
PG_DSN = os.getenv("PG_DSN", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
JWT_ISSUER = "rag-api"
JWT_AUDIENCE = "personal-knowledge-base"
OWNER_PASSWORD_HASH = os.getenv("OWNER_PASSWORD_HASH", "")
DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", str(Path(__file__).resolve().parents[2] / "files" / "mvp")))
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 50
PROCESSING_TIMEOUT_SECONDS = 120
OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "eng+dan+chi_sim")


def validate_config() -> None:
    """Fail closed at API startup; the password CLI can run before setup."""
    if len(JWT_SECRET.encode("utf-8")) < 32 or JWT_SECRET.startswith("change-me"):
        raise RuntimeError("JWT_SECRET 必须是至少 32 字节的随机密钥")
    if JWT_EXPIRE_MINUTES <= 0:
        raise RuntimeError("JWT_EXPIRE_MINUTES 必须大于 0")
    try:
        bcrypt.checkpw(b"configuration-check", OWNER_PASSWORD_HASH.encode("utf-8"))
    except ValueError as exc:
        raise RuntimeError("请使用 python cli.py hash-password 配置 OWNER_PASSWORD_HASH") from exc
