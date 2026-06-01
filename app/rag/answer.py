"""Simple RAG answer — fixed flow: retrieve top-n chunks, then Claude answers.

This is the non-agentic baseline (the "ask" flow). For autonomous tool
selection see agent.py.
"""

import anthropic

from core.config import CLAUDE_MODEL
from db.storage import vector_search_with_text


SYSTEM_PROMPT = """你是用户的私人文件助手。
根据提供的文件内容回答问题。
如果文件中没有相关信息，直接说"我在您的文件中没有找到相关记录"。
不要编造任何信息。"""


def answer_with_rag(question: str, user_id: str, n: int = 3) -> str:
    hits = vector_search_with_text(question, user_id, n=n)
    if not hits:
        return "我在您的文件中没有找到相关记录。"

    context = "\n\n".join(
        f"文件{i + 1}：\n{text}" for i, (_fid, text) in enumerate(hits)
    )
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"我的文件内容：\n{context}\n\n我的问题：{question}",
        }],
    )
    return message.content[0].text
