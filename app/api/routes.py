"""HTTP routes — all /api/* endpoints live here, grouped on one router.

Keeping routes separate from app assembly (main.py) keeps each file focused:
main.py wires things together, routes.py defines what the endpoints do.
"""

import os
import shutil
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from core.config import FILES_DIR
from rag.service import ingest_file, list_documents
from rag.agent import agent_answer
from db.storage import run_sql, get_collection

router = APIRouter(prefix="/api")

os.makedirs(FILES_DIR, exist_ok=True)


class AskRequest(BaseModel):
    question: str


@router.get("/health")
def health():
    """Report reachability of both stores (used by the UI banner)."""
    status = {"chroma": False, "postgres": False}
    try:
        get_collection()
        status["chroma"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        run_sql("SELECT 1")
        status["postgres"] = True
    except Exception:  # noqa: BLE001
        pass
    return status


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Save the uploaded file, then run the ingest pipeline on it."""
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    saved_path = os.path.join(FILES_DIR, f"{uuid.uuid4()}{ext}")
    with open(saved_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        result = ingest_file(saved_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "file_id": result["file_id"],
        "doc": result["doc"],
        "embedding_text": result["embedding_text"],
    }


@router.get("/documents")
def documents(limit: int = 100):
    """List ingested documents, newest first."""
    return list_documents(limit=limit)


@router.post("/ask")
def ask(req: AskRequest):
    """Run the agentic RAG loop and return the final answer."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    return {"answer": agent_answer(req.question, verbose=False)}
