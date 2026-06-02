"""CLI entrypoint — drives the full pipeline across both databases.

Commands:
    python cli.py healthcheck            # verify both DBs are reachable
    python cli.py ingest <image_path>    # process + write to both stores
    python cli.py vsearch "<question>"   # vector recall + PG enrichment
    python cli.py ask "<question>"       # simple RAG: vector retrieve + answer
    python cli.py agent "<question>"     # agentic RAG: Claude picks the tools
    python cli.py sql "<SELECT ...>"     # raw exact query on PostgreSQL
    python cli.py create-user <email> [password]   # create an account (admin path)

Files are per-user now, so the data commands need a user. For convenience the
CLI just uses the FIRST registered user — create one via create-user first.
"""

import secrets
import sys

from rag.answer import answer_with_rag
from rag.agent import agent_answer
from rag.service import ingest_file
from db.storage import (
    vector_search, fetch_by_ids, run_sql, get_collection,
    create_user, get_user_by_email,
)
from api.security import hash_password


def _debug_user_id() -> str:
    """First registered user's id — a convenience for CLI debugging only."""
    rows = run_sql("SELECT id FROM users ORDER BY created_at LIMIT 1")
    if not rows:
        print("还没有用户，请先在网页端注册一个账号。")
        sys.exit(1)
    return str(rows[0][0])


def healthcheck():
    ok = True
    try:
        get_collection()
        print("ChromaDB    : OK")
    except Exception as e:  # noqa: BLE001
        ok = False
        print("ChromaDB    : FAILED ->", e)
    try:
        run_sql("SELECT 1")
        print("PostgreSQL  : OK")
    except Exception as e:  # noqa: BLE001
        ok = False
        print("PostgreSQL  : FAILED ->", e)
    print("Overall     :", "ALL GOOD" if ok else "PROBLEMS")
    return ok


def ingest(path: str, model: str = None):
    result = ingest_file(path, _debug_user_id(), model=model)
    print(f"已入库 file_id={result['file_id']}")
    print(f"  {result['embedding_text']}")


def vsearch(question: str):
    file_ids = vector_search(question, _debug_user_id())
    print(f"问题：{question}")
    for r in fetch_by_ids(file_ids):
        print(f"  {r[1]} | vendor={r[2]} | {r[3]} | amount={r[4]}")


def ask(question: str):
    print(answer_with_rag(question, _debug_user_id()))


def agent(question: str):
    result = agent_answer(question, _debug_user_id())
    print(result["answer"])


def sql(query: str):
    for row in run_sql(query):
        print(" ", row)


def create_user_cmd(email: str, password: str = None):
    """Create an account from the command line (the admin path now that public
    self-registration is off). If no password is given, a strong random one is
    generated and printed once.
    """
    if get_user_by_email(email):
        print(f"用户已存在：{email}")
        sys.exit(1)
    # No password supplied -> generate a URL-safe random one and show it ONCE.
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(12)
    user = create_user(email, hash_password(password))
    print(f"已创建用户：{user['email']}  (id={user['id']})")
    if generated:
        print(f"  随机密码（请妥善保存，仅显示这一次）：{password}")


COMMANDS = {"healthcheck": healthcheck, "ingest": ingest, "vsearch": vsearch,
            "ask": ask, "agent": agent, "sql": sql,
            "create-user": create_user_cmd}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
