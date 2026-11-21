"""Local authentication setup, health checks and additive schema initialization."""

import argparse
import getpass
from uuid import UUID


def main() -> int:
    parser = argparse.ArgumentParser(description="个人知识库基础工具")
    parser.add_argument("command", choices=["hash-password", "healthcheck", "init-db", "embed-documents", "check-embeddings", "mcp-token"])
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--document-id", type=UUID)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    if args.command == "mcp-token":
        from core.config import validate_config
        from api.security import create_mcp_token
        validate_config()
        try:
            print(create_mcp_token(args.days))
        except ValueError as exc:
            parser.error(str(exc))
        return 0

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

    if args.command in ('embed-documents', 'check-embeddings'):
        from documents.models import DocumentError
        try:
            if args.command == 'check-embeddings':
                import time
                from embeddings.provider import VertexEmbedder, active_profile
                profile = active_profile()
                if profile is None:
                    raise DocumentError('embedding_not_configured', '请配置 VERTEX_EMBEDDING_PROJECT。')
                with VertexEmbedder(profile, time.monotonic() + 30) as provider:
                    vector, tokens = provider.embed('Document embedding availability check.')
                print(f'Vertex embedding: OK ({len(vector)} dimensions, {tokens} tokens)')
                return 0
            if not 1 <= args.limit <= 10000:
                parser.error('--limit must be between 1 and 10000')
            from embeddings.service import backfill
            results = backfill(args.limit, args.document_id)
            for doc in results:
                state = doc['embedding']
                print(f"{doc['id']}: {state['status']} {state['completed_chunks']}/{state['total_chunks']} chunks, {state['vector_count']} vectors")
            return int(any(doc['embedding']['status'] != 'ready' for doc in results))
        except DocumentError as exc:
            print(f'{exc.code}: {exc}')
            return 1

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
