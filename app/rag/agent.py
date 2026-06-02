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
import time

import anthropic

from core.config import CLAUDE_MODEL, RELEVANCE_MAX_DISTANCE
from db.storage import (
    vector_search_scored,
    run_select_for_user,
    get_documents_meta,
)


# --- Cost estimation (observability) ---------------------------------------
# Approximate USD price per 1M tokens, per model. An agentic question may make
# several Claude calls (one per tool round), so we sum usage across the whole
# loop and turn it into a rough dollar figure the UI / traces can show.
# Prices are ballpark and easy to update; keep them in one place.
_PRICING_PER_MTOK = {
    # model substring : (input $/Mtok, output $/Mtok)
    "haiku": (1.0, 5.0),
    "sonnet": (3.0, 15.0),
    "opus": (15.0, 75.0),
}


def _price_for(model: str) -> tuple[float, float]:
    """Pick the (input, output) price by matching a known family in the name.
    Falls back to Haiku pricing for unknown models so cost is never None."""
    name = (model or "").lower()
    for key, price in _PRICING_PER_MTOK.items():
        if key in name:
            return price
    return _PRICING_PER_MTOK["haiku"]


def _estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    """Rough USD cost for a token count. Used for observability, not billing."""
    in_price, out_price = _price_for(model)
    return round(in_tokens / 1e6 * in_price + out_tokens / 1e6 * out_price, 6)


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


def _run_tool(name: str, args: dict, user_id: str, hit_scores: dict) -> str:
    """Execute a tool call (scoped to user_id) and return a string for Claude.

    hit_scores maps file_id -> best (smallest) distance seen across all
    vector_search calls this turn. We keep the distance so the caller can show
    download/delete cards ONLY for files that are actually relevant (close
    enough), and order them most-relevant-first.

    Note: we still feed Claude EVERY retrieved snippet (so its answer isn't
    starved of context); the distance gate only affects which file CARDS the UI
    shows, not what the model reads.
    """
    if name == "vector_search":
        hits = vector_search_scored(args["query"], user_id, n=args.get("n", 3))
        if not hits:
            return "（无命中）"
        for fid, _text, dist in hits:
            # Keep the closest distance if this file was hit by multiple queries.
            if fid not in hit_scores or dist < hit_scores[fid]:
                hit_scores[fid] = dist
        return "\n".join(f"- {text}" for _fid, text, _dist in hits)
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


def _relevant_files(hit_scores: dict, user_id: str) -> list[dict]:
    """Turn collected vector hits into UI file cards, keeping ONLY those within
    the relevance threshold and ordering them most-relevant (closest) first.

    This is what fixes "every chat dumps all my files": an unrelated question
    whose nearest vector is still far away yields an empty list -> no cards.
    """
    relevant = sorted(
        (fid for fid, dist in hit_scores.items() if dist <= RELEVANCE_MAX_DISTANCE),
        key=lambda fid: hit_scores[fid],
    )
    if not relevant:
        return []
    cards = get_documents_meta(relevant, user_id)
    # get_documents_meta doesn't preserve order, so re-sort by relevance.
    order = {fid: i for i, fid in enumerate(relevant)}
    cards.sort(key=lambda c: order.get(c["file_id"], 1e9))
    return cards


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
    hit_scores: dict = {}   # file_id -> best (smallest) vector distance this turn
    # Observability: sum token usage across EVERY Claude call in the loop, plus
    # how many tool rounds we ran, so callers can see cost/latency per question.
    in_tokens = 0
    out_tokens = 0
    tool_calls = 0
    # Tracing: an ordered timeline of every step (LLM call / tool call) with its
    # own duration, so the /traces page can show exactly what the agent did.
    steps: list[dict] = []
    num_turns = 0
    run_start = time.perf_counter()

    def _usage() -> dict:
        """Build the usage/cost summary returned alongside every answer."""
        return {
            "model": _model,
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "tool_calls": tool_calls,
            "cost_usd": _estimate_cost(_model, in_tokens, out_tokens),
        }

    def _trace(answer: str, status: str = "ok", error: str = None) -> dict:
        """Assemble the full trace record handed back to the caller to persist."""
        return {
            "question": question,
            "answer": answer,
            "status": status,
            "error": error,
            "num_turns": num_turns,
            "duration_ms": int((time.perf_counter() - run_start) * 1000),
            "steps": steps,
            **_usage(),   # model / input_tokens / output_tokens / tool_calls / cost_usd
        }

    for _turn in range(max_turns):
        num_turns += 1
        # --- LLM call (timed) ---
        llm_start = time.perf_counter()
        resp = client.messages.create(
            model=_model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        llm_ms = int((time.perf_counter() - llm_start) * 1000)
        # Accumulate this call's token usage (every round counts toward cost).
        in_tokens += resp.usage.input_tokens
        out_tokens += resp.usage.output_tokens
        steps.append({
            "seq": len(steps) + 1,
            "type": "llm",
            "name": f"Claude 调用 #{num_turns}",
            "duration_ms": llm_ms,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "stop_reason": resp.stop_reason,
        })

        if resp.stop_reason != "tool_use":
            answer = "".join(b.text for b in resp.content if b.type == "text")
            files = _relevant_files(hit_scores, user_id)
            return {"answer": answer, "files": files,
                    "usage": _usage(), "trace": _trace(answer)}

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                tool_calls += 1
                if verbose:
                    print(f"  [工具] {block.name}({json.dumps(block.input, ensure_ascii=False)})")
                # --- tool call (timed) ---
                tool_start = time.perf_counter()
                result = _run_tool(block.name, block.input, user_id, hit_scores)
                tool_ms = int((time.perf_counter() - tool_start) * 1000)
                steps.append({
                    "seq": len(steps) + 1,
                    "type": "tool",
                    "name": block.name,
                    "duration_ms": tool_ms,
                    # Truncate so a huge SQL dump doesn't bloat the trace row.
                    "input": json.dumps(block.input, ensure_ascii=False)[:300],
                    "output_preview": str(result)[:300],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        messages.append({"role": "user", "content": tool_results})

    files = _relevant_files(hit_scores, user_id)
    answer = "（已达到最大步数，未能得出最终答案）"
    return {
        "answer": answer,
        "files": files,
        "usage": _usage(),
        "trace": _trace(answer, status="error", error="max_turns reached"),
    }
