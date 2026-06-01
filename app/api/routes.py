"""HTTP routes — all /api/* endpoints live here, grouped on one router.

Keeping routes separate from app assembly (main.py) keeps each file focused:
main.py wires things together, routes.py defines what the endpoints do.

Files are per-user now, so every data route requires login (Depends
get_current_user) and is scoped to that user. /health and /models stay public.
"""

import os
import shutil
import uuid

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from core.config import FILES_DIR, AVAILABLE_MODELS
from rag.service import ingest_file, list_documents, delete_file, semantic_search
from rag.agent import agent_answer
from db.storage import run_sql, get_collection, get_document
from api.deps import get_current_user
from worker.celery_app import celery_app
from worker.tasks import ingest_task

router = APIRouter(prefix="/api")

os.makedirs(FILES_DIR, exist_ok=True)


class AskRequest(BaseModel):
    question: str
    model: Optional[str] = None


class SearchRequest(BaseModel):
    query: str


def _save_upload(file: UploadFile) -> str:
    """Persist an uploaded file to FILES_DIR under a random name; return path."""
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    saved_path = os.path.join(FILES_DIR, f"{uuid.uuid4()}{ext}")
    with open(saved_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    return saved_path


@router.get("/models")
def models():
    """Return available Claude models for the frontend model selector."""
    return AVAILABLE_MODELS


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
async def upload(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    """SYNCHRONOUS ingest: process the file inline and return the result.

    New clients should prefer /upload_async (returns immediately, processes in
    the background via Celery).
    """
    saved_path = _save_upload(file)
    try:
        result = ingest_file(saved_path, user["id"], model=model or None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "file_id": result["file_id"],
        "duplicate": result.get("duplicate", False),
        "doc": result["doc"],
        "embedding_text": result["embedding_text"],
    }


@router.post("/upload_async")
async def upload_async(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    """ASYNCHRONOUS ingest: save the file, hand it to a Celery worker, and
    return a task_id immediately. The client polls /tasks/{task_id}.
    """
    saved_path = _save_upload(file)
    task = ingest_task.delay(saved_path, user["id"], model or None)
    return {"task_id": task.id, "status": "processing"}


@router.get("/tasks/{task_id}")
def task_status(task_id: str, user: dict = Depends(get_current_user)):
    """Poll the status/result of a background ingest task."""
    res = celery_app.AsyncResult(task_id)
    if res.successful():
        return {"status": "success", "result": res.result}
    if res.failed():
        return {"status": "failed", "error": str(res.result)}
    return {"status": res.status.lower()}


@router.get("/documents")
def documents(limit: int = 100, user: dict = Depends(get_current_user)):
    """List the current user's documents, newest first."""
    return list_documents(user["id"], limit=limit)


@router.post("/search")
def search(req: SearchRequest, user: dict = Depends(get_current_user)):
    """Natural-language (semantic) file search -> file cards."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="搜索词不能为空")
    return semantic_search(req.query, user["id"])


@router.get("/documents/{file_id}/download")
def download(file_id: str, user: dict = Depends(get_current_user)):
    """Stream the original file back, only if owned by the current user."""
    doc = get_document(file_id, user["id"])
    if not doc or not doc["file_path"] or not os.path.exists(doc["file_path"]):
        raise HTTPException(status_code=404, detail="文件不存在")
    ext = os.path.splitext(doc["file_path"])[1]
    nice = doc.get("vendor") or doc.get("doc_type") or "file"
    return FileResponse(doc["file_path"], filename=f"{nice}{ext}")


@router.delete("/documents/{file_id}")
def delete_doc(file_id: str, user: dict = Depends(get_current_user)):
    """Delete a file from both stores and disk. 404 if not found / not owned."""
    if not delete_file(file_id, user["id"]):
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"deleted": True}


@router.post("/ask")
def ask(req: AskRequest, user: dict = Depends(get_current_user)):
    """Run the agentic RAG loop. Returns {"answer": ..., "files": [...]}."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    return agent_answer(req.question, user["id"], verbose=False, model=req.model or None)
