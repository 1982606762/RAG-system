"""CLI entrypoint — drives the full pipeline across both databases.

Commands:
    python cli.py healthcheck            # verify both DBs are reachable
    python cli.py ingest <image_path>    # process + write to both stores
    python cli.py vsearch "<question>"   # vector recall + PG enrichment
    python cli.py ask "<question>"       # simple RAG: vector retrieve + answer
    python cli.py agent "<question>"     # agentic RAG: Claude picks the tools
    python cli.py sql "<SELECT ...>"     # raw exact query on PostgreSQL
"""

import sys

from rag.answer import answer_with_rag
from rag.agent import agent_answer
from rag.service import ingest_file
from db.storage import vector_search, fetch_by_ids, run_sql, get_collection


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
    result = ingest_file(path, model=model)
    print(f"已入库 file_id={result['file_id']}")
    print(f"  {result['embedding_text']}")


def vsearch(question: str):
    file_ids = vector_search(question)
    print(f"问题：{question}")
    for r in fetch_by_ids(file_ids):
        print(f"  {r[1]} | vendor={r[2]} | {r[3]} | amount={r[4]}")


def ask(question: str):
    print(answer_with_rag(question))


def agent(question: str):
    print(agent_answer(question))


def sql(query: str):
    for row in run_sql(query):
        print(" ", row)


COMMANDS = {"healthcheck": healthcheck, "ingest": ingest, "vsearch": vsearch,
            "ask": ask, "agent": agent, "sql": sql}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
