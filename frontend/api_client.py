"""Thin client for the Study Buddy API.

Every call goes through here rather than being scattered through the Streamlit
app, so the token handling and error reporting live in one place.
"""

import os
from typing import Any

import requests

API_URL = os.environ.get("API_URL", "http://localhost:8000")
TIMEOUT = 10
ASK_TIMEOUT = 180  # generation is slow on CPU, so this call needs longer


class ApiError(Exception):
    """Raised when the API returns an error, carrying its message."""


def _handle(response: requests.Response) -> Any:
    """Return parsed JSON, or raise ApiError with the server's detail."""
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise ApiError(f"{response.status_code}: {detail}")
    if response.status_code == 204:
        return None
    return response.json()


def register(email: str, password: str) -> dict:
    """Create an account."""
    r = requests.post(
        f"{API_URL}/auth/register",
        json={"email": email, "password": password},
        timeout=TIMEOUT,
    )
    return _handle(r)


def login(email: str, password: str) -> str:
    """Exchange credentials for a bearer token."""
    r = requests.post(
        f"{API_URL}/auth/token",
        data={"username": email, "password": password},
        timeout=TIMEOUT,
    )
    payload = _handle(r)
    return payload["access_token"]


def _headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def health() -> dict:
    """Service status. Needs no token."""
    return _handle(requests.get(f"{API_URL}/health", timeout=TIMEOUT))


def list_documents(token: str) -> list:
    """The signed-in user's documents."""
    return _handle(requests.get(f"{API_URL}/documents", headers=_headers(token), timeout=TIMEOUT))


def upload_document(token: str, filename: str, content: bytes) -> dict:
    """Upload one text file."""
    r = requests.post(
        f"{API_URL}/documents",
        files={"file": (filename, content, "text/plain")},
        headers=_headers(token),
        timeout=TIMEOUT,
    )
    return _handle(r)


def delete_document(token: str, document_id: int) -> None:
    """Delete one document and its chunks."""
    r = requests.delete(
        f"{API_URL}/documents/{document_id}", headers=_headers(token), timeout=TIMEOUT
    )
    _handle(r)


def ingest(token: str) -> dict:
    """Chunk and index everything the user has uploaded."""
    r = requests.post(f"{API_URL}/ingest", headers=_headers(token), timeout=120)
    return _handle(r)


def ask(token: str, question: str) -> dict:
    """Ask a question. Slow: it retrieves, then generates."""
    r = requests.post(
        f"{API_URL}/ask",
        json={"question": question},
        headers=_headers(token),
        timeout=ASK_TIMEOUT,
    )
    return _handle(r)


def history(token: str) -> list:
    """The user's past questions."""
    return _handle(requests.get(f"{API_URL}/questions", headers=_headers(token), timeout=TIMEOUT))