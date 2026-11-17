"""Local authentication setup, health checks and additive schema initialization."""

import argparse
import getpass


def main() -> int:
    parser = argparse.ArgumentParser(description="个人知识库基础工具")
    parser.add_argument("command", choices=["hash-password", "healthcheck", "init-db"])
    args = parser.parse_args()

    if args.command == "hash-password":
        from api.security import hash_password

        password = getpass.getpass("访问密码（至少 12 个字符）: ")
        if password != getpass.getpass("再次输入: "):
            parser.error("两次输入的密码不一致")
        try:
            hashed = hash_password(password)
        except ValueError as exc:
            parser.error(str(exc))
        # Single quotes preserve bcrypt's dollar signs in Docker Compose .env.
        print(f"OWNER_PASSWORD_HASH='{hashed}'")
        return 0

    if args.command == "init-db":
        from db.documents import initialize
        initialize()
        print("Document schema: ready (knowledge_base_v1)")
        return 0

    import psycopg
    from db.connection import check_database

    try:
        check_database()
    except psycopg.Error:
        print("PostgreSQL: unavailable")
        return 1
    print("PostgreSQL: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
