"""Ingestion and question answering."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import rag
from ..config import settings
from ..database import get_db
from ..dependencies import get_current_user
from ..models import Document, Question, User
from ..schemas import AskRequest, AskResponse, QuestionOut

router = APIRouter(tags=["rag"])


@router.post("/ingest")
def ingest(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Chunk and index every document the caller has uploaded.

    Idempotent: re-running replaces a document's chunks rather than duplicating
    them. Each document's chunk_count is updated from what was actually stored.
    """
    docs = db.scalars(
        select(Document).where(Document.owner_id == user.id)
    ).all()

    if not docs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No documents uploaded yet",
        )

    upload_dir = Path(settings.UPLOAD_DIR)
    indexed = []
    missing = []
    for doc in docs:
        stored = upload_dir / f"{user.id}_{doc.filename}"
        if not stored.exists():
            missing.append(doc.filename)
            continue
        # Replace rather than append, so re-ingesting does not duplicate.
        rag.delete_document_chunks(user.id, doc.id)
        count = rag.ingest_file(stored, user.id, doc.id, doc.filename)
        doc.chunk_count = count
        indexed.append({"document": doc.filename, "chunks": count})

    db.commit()

    response = {
        "documents": len(indexed),
        "chunks": sum(i["chunks"] for i in indexed),
        "files": indexed,
        "stored": rag.count_chunks(owner_id=user.id),
    }
    # Rows whose file is gone are reported rather than skipped silently.
    if missing:
        response["missing"] = missing
    return response


@router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Answer a question from the caller's documents and record it.

    The question is written to the database whether or not the guardrail
    refuses, so the caller's history is complete.
    """
    result = rag.answer_question(payload.question, user.id)

    record = Question(
        owner_id=user.id,
        question=payload.question,
        answer=None if result["guardrail"] != "answered" else result["answer"],
        confidence=result["confidence"],
        best_distance=result["best_distance"],
    )
    db.add(record)
    db.commit()

    return result


@router.get("/questions", response_model=list[QuestionOut])
def history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The caller's question history, newest first."""
    return db.scalars(
        select(Question)
        .where(Question.owner_id == user.id)
        .order_by(Question.asked_at.desc())
    ).all()
