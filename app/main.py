"""FastAPI app assembly — wire the routers.

The frontend is NO LONGER served from here: nginx (the `frontend` container)
serves the built React app and reverse-proxies /api to this service. So this
process is a pure JSON API now.

Run with: uvicorn main:app --host 0.0.0.0 --port 8001
"""

from fastapi import FastAPI

from api.routes import router
from api.auth import router as auth_router
from api.conversations import router as conv_router

app = FastAPI(title="家用文件知识库")
app.include_router(router)
app.include_router(auth_router)
app.include_router(conv_router)


@app.get("/")
def root():
    """Tiny liveness probe for hitting the backend directly (bypassing nginx)."""
    return {"service": "rag-api", "status": "ok"}
