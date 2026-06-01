"""Agentic RAG — Claude decides which tool(s) to call, and how many times.

The agent loop:
    1. Send the question + tool definitions to Claude.
    2. Claude either answers directly (no tool) or asks to call a tool.
    3. We execute the tool and feed the result back.
    4. Repeat until Claude produces a final text answer.

Tools: vector_search (ChromaDB) and sql_search (PostgreSQL). Both are scoped
to ONE user. While running we collect the file_ids that vector_search hit, so
the UI can show download/delete cards for exactly those files.
"""

import json

import anthropic

from core.config import CLAUDE_MODEL
from db.storage import (
    vector_search_with_text,
    run_select_for_user,
    get_documents_meta,
)


TABLE_SCHEMA = """表 documents 的列：
  file_id (UUID), doc_type (VARCHAR, 如 invoice/receipt/contract/manual/warranty),
  doc_date (DATE), amount (NUMERIC), currency (VARCHAR),
  vendor (VARCHAR), summary (TEXT), file_path (TEXT),
  full_analysis (JSONB，含动态 details 层，如 full_analysis->'details'->>'brand'),
  created_at (TIMESTAMP)"""

SYSTEM_PROMPT = f"""你是用户的私人文件知识库助手。用户用自然语言提问。

你有两个工具：
- vector_search：模糊语义检索，适合"记不清细节、描述性"的问题（如"我三月买的奶酪"）。
- sql_search：精确查询，适合需要完整列举、范围筛选、计数或求和的问题（如"今年所有发票""消费总额"）。
  你需要自己写一条 SELECT 语句，只能查 documents 表。

{TABLE_SCHEMA}

决策原则：
- 模糊/描述性 → vector_search
- 精确/列举/汇总 → sql_search（必要时可多次调用，比如对比去年和今年要查两次）
- 与文件无关的闲聊 → 不调用任何工具，直接回答

根据检索结果用中文回答。如果没有找到相关信息，直接说没有找到，不要编造。"""


TOOLS = [
    {
        "name": "vector_search",
        "description": "在文件知识库里做语义相似度检索，返回最相关的几条文件描述。"
                       "适合模糊、描述性、记不清确切字段的查询。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索用的自然语言查询"},
                "n": {"type": "integer", "description": "返回条数，默认3"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "sql_search",
        "description": "对 documents 表执行一条只读 SELECT 查询，用于精确筛选、"
                       "完整列举、计数或求和。只能写 SELECT。",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "一条 SELECT 语句"},
            },
            "required": ["sql"],
        },
    },
]


def _run_tool(name: str, args: dict, user_id: str, hit_ids: set) -> str:
    """Execute a tool call (scoped to user_id) and return a string for Claude.

    hit_ids accumulates file_ids that vector_search matched, so the caller can
    turn them into download/delete cards afterwards.
    """
    if name == "vector_search":
        hits = vector_search_with_text(args["query"], user_id, n=args.get("n", 3))
        if not hits:
            return "（无命中）"
        for fid, _text in hits:
            hit_ids.add(fid)
        return "\n".join(f"- {text}" for _fid, text in hits)
    if name == "sql_search":
        try:
            # CTE-scoped to this user; the model can't see other users' rows.
            rows = run_select_for_user(args["sql"], user_id)
        except Exception as e:  # noqa: BLE001
            return f"查询出错：{e}"
        if not rows:
            return "（无结果）"
        return "\n".join(str(r) for r in rows)
    return f"未知工具：{name}"


def agent_answer(
    question: str,
    user_id: str,
    history: list[dict] | None = None,
    max_turns: int = 6,
    verbose: bool = True,
    model: str = None,
) -> dict:
    """Run the agentic loop. Returns {"answer": str, "files": [card, ...]}.

    files are the documents vector_search hit this turn (metadata cards the UI
    renders with download/delete buttons).

    history: prior CLEAN turns of this conversation, as
    [{"role": "user"|"assistant", "content": str}, ...]. We replay them in
    front of the new question so Claude can resolve references like "它"/"那个".
    """
    client = anthropic.Anthropic()
    messages = [
        {"role": h["role"], "content": h["content"]} for h in (history or [])
    ]
    messages.append({"role": "user", "content": question})
    _model = model or CLAUDE_MODEL
    hit_ids: set = set()

    for _turn in range(max_turns):
        resp = client.messages.create(
            model=_model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if resp.stop_reason != "tool_use":
            answer = "".join(b.text for b in resp.content if b.type == "text")
            files = get_documents_meta(list(hit_ids), user_id)
            return {"answer": answer, "files": files}

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                if verbose:
                    print(f"  [工具] {block.name}({json.dumps(block.input, ensure_ascii=False)})")
                result = _run_tool(block.name, block.input, user_id, hit_ids)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        messages.append({"role": "user", "content": tool_results})

    files = get_documents_meta(list(hit_ids), user_id)
    return {"answer": "（已达到最大步数，未能得出最终答案）", "files": files}
