"""Owner-only upload, inspection, original download and manual retry."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import FileResponse

from api.deps import require_owner
from db import documents as store
from documents.models import DocumentError
from documents.service import original_path, retry_document, upload_document

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(require_owner)])


@router.get("")
def list_documents(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    return store.list_documents(limit, offset)


@router.post("")
def upload(file: UploadFile):
    try:
        return upload_document(file)
    finally:
        file.file.close()


@router.get("/{document_id}")
def detail(document_id: UUID):
    return store.get_detail(document_id)


@router.post("/{document_id}/retry")
def retry(document_id: UUID):
    return retry_document(document_id)


@router.get("/{document_id}/original")
def original(document_id: UUID):
    with store.connect() as conn:
        document = store.get_document(conn, document_id)
    path = original_path(document_id, document["extension"])
    if not path.is_file():
        raise DocumentError("original_missing", "原始文件不存在，请检查文件存储。", 404)
    # Always download raw originals. The frontend explicitly previews supported
    # types in a blob URL; uploaded HTML/Markdown is never served as active HTML.
    return FileResponse(path, media_type="application/octet-stream", filename=document["filename"],
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
