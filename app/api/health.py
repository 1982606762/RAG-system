"""Readiness probe used by deployment and the application shell."""

import logging

import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db.connection import check_database

router = APIRouter(prefix="/api", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health():
    try:
        check_database()
    except psycopg.Error:
        # Do not return connection details or credentials to a public endpoint.
        logger.warning("PostgreSQL readiness check failed")
        return JSONResponse(status_code=503, content={"postgres": False})
    return {"postgres": True}
