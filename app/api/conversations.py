"""Conversation history routes — create threads, list them, read messages,
and ask questions that REMEMBER the earlier turns.

Every route here requires login: a conversation belongs to exactly one user,
and we check ownership before reading or writing it.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from rag.agent import agent_answer
from db.storage import (
    create_conversation,
    list_conversations,
    get_conversation,
    update_conversation_title,
    add_message,
    get_messages,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class NewConversation(BaseModel):
    title: Optional[str] = None


class AskInConversation(BaseModel):
    question: str
    model: Optional[str] = None


@router.post("")
def create(req: NewConversation, user: dict = Depends(get_current_user)):
    """Start a new (empty) conversation owned by the current user."""
    return create_conversation(user["id"], req.title)


@router.get("")
def list_all(user: dict = Depends(get_current_user)):
    """List the current user's conversations, newest first."""
    return list_conversations(user["id"])


@router.get("/{conv_id}/messages")
def messages(conv_id: str, user: dict = Depends(get_current_user)):
    """Return every message in one conversation (after ownership check)."""
    if get_conversation(conv_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return get_messages(conv_id)


@router.post("/{conv_id}/ask")
def ask(conv_id: str, req: AskInConversation, user: dict = Depends(get_current_user)):
    """Ask a question inside a conversation, with memory of earlier turns."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    conv = get_conversation(conv_id, user["id"])
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 1. Replay prior turns so the agent has context (taken BEFORE we store
    #    the current question, so it isn't duplicated).
    history = get_messages(conv_id)
    # 2. Run the agentic RAG loop with that history. agent_answer returns
    #    {"answer": str, "files": [card, ...]}: the files are whatever
    #    vector_search hit this turn, so the UI can offer download/delete on
    #    them right inside the chat.
    result = agent_answer(
        req.question, user["id"], history=history, verbose=False,
        model=req.model or None,
    )
    answer = result["answer"]
    # 3. Persist BOTH sides of this turn (CLEAN text only — we store the answer
    #    string, NOT the file cards, which are a live UI affordance, not history).
    add_message(conv_id, "user", req.question)
    add_message(conv_id, "assistant", answer)
    # 4. The first question doubles as the thread title.
    if not conv["title"]:
        update_conversation_title(conv_id, req.question[:20])

    # usage = token/cost observability from the agent loop; forward it so the
    # UI can show "this answer cost $X". Not persisted (it's per-call, not history).
    return {
        "conversation_id": conv_id,
        "answer": answer,
        "files": result["files"],
        "usage": result.get("usage"),
    }
