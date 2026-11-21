"""Shared fixtures.

The database and vector store are wiped before each test, so no test can
depend on what another test left behind. Paths are fixed rather than per-test
because the app builds its engine and Chroma client at import time.
"""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"
os.environ["CHROMA_PATH"] = "./data/test_chroma"
os.environ["UPLOAD_DIR"] = "./data/test_uploads"

import pytest
from app.main import app
from fastapi.testclient import TestClient

DATA = Path("./data")


def _reset() -> None:
    """Empty the tables and the vector store, leaving the files in place.

    The engine holds the path it was built with at import time, so deleting
    the database file leaves the app pointing at a file that no longer has
    tables. Dropping and recreating removes the rows without touching the
    schema's location.
    """
    from app import models  # noqa: F401  (registers the tables on Base)
    from app.database import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # Clear the collection through the client rather than deleting the
    # directory: the cached PersistentClient holds a handle on it, so removing
    # the files underneath leaves it querying a store that no longer exists.
    from app import rag

    collection = rag.get_collection()
    existing = collection.get(include=[])
    if existing.get("ids"):
        collection.delete(ids=existing["ids"])

    shutil.rmtree(DATA / "test_uploads", ignore_errors=True)
    (DATA / "test_uploads").mkdir(parents=True, exist_ok=True)


@pytest.fixture
def client():
    """A test client with an empty database and empty vector store."""
    _reset()
    # The database file was deleted a line ago, so the tables must be
    # recreated before the first request. create_all() at import time only
    # ran once, at the start of the session.
    from app.database import create_all
    create_all()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    """Register a user and return an Authorization header."""
    client.post(
        "/auth/register",
        json={"email": "test@example.com", "password": "hunter2hunter2"},
    )
    r = client.post(
        "/auth/token",
        data={"username": "test@example.com", "password": "hunter2hunter2"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

@pytest.fixture
def fake_ollama(monkeypatch):
    """Replace the call to Ollama with a stub.

    Without this the answer tests depend on a model being pulled and a GPU or
    CPU being free to generate. The stub lets the tests check what the pipeline
    actually did -- which chunks it retrieved, what confidence it assigned,
    what prompt it built -- rather than whether a model server happened to be
    reachable.
    """
    calls = []

    class FakeResponse:
        def __init__(self, text):
            self._text = text
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"response": self._text}

    def fake_post(url, json=None, timeout=None, **kwargs):
        calls.append({"url": url, "payload": json or {}})
        return FakeResponse("Stubbed answer based on the supplied context.")

    import app.rag as rag_module

    monkeypatch.setattr(rag_module.requests, "post", fake_post)
    return calls
