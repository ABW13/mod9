"""SQLAlchemy models: users, documents and questions."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """A registered account. Owns documents and questions."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Document(Base):
    """An uploaded file. Holds the filename and chunk count, not the text.

    The text itself lives in ChromaDB as chunks, so it is stored once rather
    than twice. The owner id is written into each chunk's metadata at ingest
    time, which is what lets retrieval be filtered per user.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="documents")


class Question(Base):
    """A question asked and the answer returned.

    `answer` and `confidence` are nullable: when the guardrail refuses, there is
    no answer, but the question is still recorded so history is complete.
    """

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer = mapped_column(Text, nullable=True)
    confidence = mapped_column(String(16), nullable=True)
    best_distance = mapped_column(Float, nullable=True)
    asked_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="questions")
