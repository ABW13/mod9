"""Study Buddy API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import rag
from .config import settings
from .database import create_all
from .routers import ask, auth, documents

app = FastAPI(
    title="Study Buddy API",
    description="Ask questions of your own study documents, with citations.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(ask.router)


# Tables are created at import rather than in a startup hook, so they exist
# however the app is run -- uvicorn, TestClient, or a script.
create_all()


@app.get("/health", tags=["system"])
def health():
    """Report service status."""
    import requests as _rq
    try:
        ok = _rq.get(f"{settings.OLLAMA_URL}/api/tags", timeout=3).status_code == 200
    except Exception:
        ok = False
    return {
        "status": "healthy",
        "ollama": "connected" if ok else "unavailable",
        "documents": rag.count_chunks(),
        "chunks": rag.count_chunks(),
    }


@app.get("/", tags=["system"])
def root():
    """Service name and configured model."""
    return {"service": "study-buddy", "model": settings.MODEL_NAME}
