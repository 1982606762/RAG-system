"""HTTP routes — all /api/* endpoints live here, grouped on one router.

Keeping routes separate from app assembly (main.py) keeps each file focused:
main.py wires things together, routes.py defines what the endpoints do.

Files are per-user now, so every data route requires login (Depends
get_current_user) and is scoped to that user. /health and /models stay public.
"""

import os
import hmac
import uuid

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from core.config import FILES_DIR, AVAILABLE_MODELS, MAX_UPLOAD_BYTES
from rag.service import ingest_file, list_documents, delete_file, semantic_search
from rag.agent import agent_answer
from db.storage import (
    run_sql, get_collection, get_document, get_document_full,
    save_trace, list_traces, get_trace,
)
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
    """Validate and persist one supported upload under a server-chosen name."""
    temp_path = os.path.join(FILES_DIR, f".{uuid.uuid4()}.upload")
    size = 0
    header = b""
    try:
        with open(temp_path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件过大")
                if len(header) < 16:
                    header = (header + chunk)[:16]
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="文件为空")

        ext = _detect_extension(header)
        if ext is None:
            raise HTTPException(
                status_code=415,
                detail="仅支持 JPEG、PNG、GIF、WEBP 和 PDF",
            )
        saved_path = os.path.join(FILES_DIR, f"{uuid.uuid4()}{ext}")
        os.replace(temp_path, saved_path)
        return saved_path
    except Exception:
        _cleanup_file(temp_path)
        raise


def _detect_extension(header: bytes) -> str | None:
    if header.startswith(b"%PDF-"):
        return ".pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    return None


def _cleanup_file(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _validated_model(model: str | None) -> str | None:
    if model and model not in AVAILABLE_MODELS:
        raise HTTPException(status_code=422, detail="不支持的模型")
    return model or None


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
def upload(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    """SYNCHRONOUS ingest: process the file inline and return the result.

    New clients should prefer /upload_async (returns immediately, processes in
    the background via Celery).
    """
    saved_path = None
    keep_file = False
    try:
        saved_path = _save_upload(file)
        result = ingest_file(
            saved_path,
            user["id"],
            model=_validated_model(model),
        )
        keep_file = not result.get("duplicate", False)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        if not keep_file:
            _cleanup_file(saved_path)

    return result


@router.post("/upload_async")
def upload_async(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    """ASYNCHRONOUS ingest: save the file, hand it to a Celery worker, and
    return a task_id immediately. The client polls /tasks/{task_id}.
    """
    saved_path = _save_upload(file)
    task_id = f"{user['id']}:{uuid.uuid4()}"
    try:
        ingest_task.apply_async(
            args=(saved_path, user["id"], _validated_model(model)),
            task_id=task_id,
        )
    except Exception:
        _cleanup_file(saved_path)
        raise
    return {"task_id": task_id, "status": "processing"}


@router.get("/tasks/{task_id}")
def task_status(task_id: str, user: dict = Depends(get_current_user)):
    """Poll the status/result of a background ingest task."""
    owner_id, separator, _opaque_id = task_id.partition(":")
    if not separator or not hmac.compare_digest(owner_id, user["id"]):
        raise HTTPException(status_code=404, detail="任务不存在")
    res = celery_app.AsyncResult(task_id)
    if res.successful():
        return {"status": "success", "result": res.result}
    if res.failed():
        return {"status": "failed", "error": str(res.result)}
    return {"status": res.status.lower()}


@router.get("/documents")
def documents(
    limit: int = Query(100, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """List the current user's documents, newest first."""
    return list_documents(user["id"], limit=limit)


@router.post("/search")
def search(req: SearchRequest, user: dict = Depends(get_current_user)):
    """Natural-language (semantic) file search -> file cards."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="搜索词不能为空")
    if len(req.query) > 1000:
        raise HTTPException(status_code=422, detail="搜索词过长")
    return semantic_search(req.query, user["id"])


@router.get("/documents/{file_id}")
def document_detail(file_id: str, user: dict = Depends(get_current_user)):
    """Full structured data for one file (for the detail modal), incl. the
    dynamic `details` layer. 404 if not found / not owned."""
    doc = get_document_full(file_id, user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="文件不存在")
    return doc


@router.get("/documents/{file_id}/preview")
def preview(file_id: str, user: dict = Depends(get_current_user)):
    """Serve the original file INLINE (Content-Disposition: inline) so the
    browser renders it in the detail modal instead of downloading it.

    Same ownership check as download; the only difference is `inline` vs
    `attachment`, which is what tells the browser to display rather than save.
    """
    doc = get_document(file_id, user["id"])
    if not doc or not doc["file_path"] or not os.path.exists(doc["file_path"]):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(doc["file_path"], content_disposition_type="inline")


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
    try:
        deleted = delete_file(file_id, user["id"])
    except Exception as exc:
        raise HTTPException(status_code=503, detail="存储服务暂时不可用，请重试") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"deleted": True}


@router.post("/ask")
def ask(req: AskRequest, user: dict = Depends(get_current_user)):
    """Run the agentic RAG loop. Returns {"answer": ..., "files": [...], "usage": ...}."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    if len(req.question) > 4000:
        raise HTTPException(status_code=422, detail="问题过长")
    result = agent_answer(
        req.question,
        user["id"],
        verbose=False,
        model=_validated_model(req.model),
    )
    # Persist the run trace (observability). Best-effort: never let a tracing
    # failure break the answer the user is waiting for.
    trace = result.pop("trace", None)
    if trace is not None:
        try:
            save_trace(user["id"], trace)
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/traces")
def traces(
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """List the current user's recent agent runs (for the /traces page)."""
    return list_traces(user["id"], limit=limit)


@router.get("/traces/{trace_id}")
def trace_detail(trace_id: str, user: dict = Depends(get_current_user)):
    """Full trace incl. the step-by-step timeline. 404 if not found / not owned."""
    t = get_trace(trace_id, user["id"])
    if not t:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return t
