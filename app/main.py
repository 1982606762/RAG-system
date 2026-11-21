"""FastAPI application for the single-owner document MVP."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.routing import Route
import psycopg

from api.auth import router as auth_router
from api.health import router as health_router
from api.documents import router as documents_router
from api.search import router as search_router
from api.mcp import mcp_lifespan, mcp_app
from core.config import validate_config
from documents.models import DocumentError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_config()
    async with mcp_lifespan():
        yield


app = FastAPI(title="个人知识库", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(search_router)


@app.exception_handler(DocumentError)
async def document_error_handler(request, exc):
    if exc.status >= 500:
        logger.warning("Request failed: route=%s status=%s code=%s",
                       getattr(request.scope.get("route"), "path", "unknown"), exc.status, exc.code)
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": exc.code})


@app.exception_handler(psycopg.Error)
async def database_error_handler(request, exc):
    logger.error("Database request failed: route=%s error_type=%s",
                 getattr(request.scope.get("route"), "path", "unknown"), type(exc).__name__)
    missing_schema = isinstance(exc, (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName))
    return JSONResponse(status_code=503, content={
        "detail": "请先运行 python cli.py init-db 初始化文档数据库。" if missing_schema else "数据库暂时不可用，请稍后重试。",
        "code": "schema_missing" if missing_schema else "database_unavailable",
    })


@app.get("/")
def root():
    return {"service": "rag-api", "status": "ok"}


# An exact ASGI route avoids a catch-all mount shadowing REST's 404/405 handling.
app.router.routes.append(Route('/api/mcp', endpoint=mcp_app, methods=['GET', 'POST', 'DELETE']))
