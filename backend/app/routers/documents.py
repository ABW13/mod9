"""Document upload, listing and deletion."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import rag
from ..config import settings
from ..database import get_db
from ..dependencies import get_current_user
from ..models import Document, User
from ..schemas import DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_SUFFIXES = {".txt", ".md"}


@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the caller's documents, newest first.

    The query is filtered by owner_id, so one account's documents are never
    visible to another.
    """
    return db.scalars(
        select(Document)
        .where(Document.owner_id == user.id)
        .order_by(Document.uploaded_at.desc())
    ).all()


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Accept a text file and record it against the caller.

    The file is written to the upload directory and a row is created. Chunking
    and embedding happen in a later step, so chunk_count starts at zero.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type {suffix!r}. Allowed: {sorted(ALLOWED_SUFFIXES)}",
        )

    data = file.file.read()
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.MAX_UPLOAD_BYTES} bytes",
        )

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Prefix with the owner id so two users uploading notes.txt do not collide.
    stored_name = f"{user.id}_{Path(file.filename).name}"
    (upload_dir / stored_name).write_bytes(data)

    # Uploading the same filename again replaces the earlier row rather than
    # adding a second one. Without this, re-uploading duplicates the document
    # and the next ingest indexes both copies.
    existing = db.scalar(
        select(Document).where(
            Document.owner_id == user.id, Document.filename == file.filename
        )
    )
    if existing is not None:
        rag.delete_document_chunks(user.id, existing.id)
        existing.chunk_count = 0
        db.commit()
        db.refresh(existing)
        return existing

    doc = Document(owner_id=user.id, filename=file.filename, chunk_count=0)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete one of the caller's documents.

    The lookup includes owner_id, so a request for someone else's document
    returns 404 rather than 403 -- it does not reveal that the row exists.
    """
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_id == user.id
        )
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    stored = Path(settings.UPLOAD_DIR) / f"{user.id}_{doc.filename}"
    stored.unlink(missing_ok=True)

    # Remove the vectors too, or they stay in ChromaDB and keep being
    # retrieved and counted even though the document row is gone.
    rag.delete_document_chunks(user.id, doc.id)

    db.delete(doc)
    db.commit()

@router.get("/{document_id}/chunks")
def list_chunks(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the indexed chunks for one of the caller's documents.

    The document lookup includes owner_id, so another account's document is a
    404 rather than a 403 -- it does not reveal that the row exists.
    """
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_id == user.id
        )
    )
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    collection = rag.get_collection()
    found = collection.get(
        where={"$and": [
            {"owner_id": user.id},
            {"document_id": document_id},
        ]},
        include=["metadatas", "documents"],
    )

    chunks = []
    for chunk_id, text, meta in zip(
        found.get("ids", []),
        found.get("documents", []),
        found.get("metadatas", []),
    ):
        meta = meta or {}
        chunks.append({
            "id": chunk_id,
            "chunk": meta.get("chunk", 0),
            "source": meta.get("source", doc.filename),
            "text": text,
        })

    chunks.sort(key=lambda c: c["chunk"])
    return chunks
