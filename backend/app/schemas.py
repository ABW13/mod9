"""Pydantic request and response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Registration request."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """A user as returned to a client. Never includes the hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime


class Token(BaseModel):
    """A bearer token response."""

    access_token: str
    token_type: str = "bearer"


class DocumentOut(BaseModel):
    """An uploaded document."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    chunk_count: int
    uploaded_at: datetime


class AskRequest(BaseModel):
    """A question to answer from the caller's documents."""

    question: str = Field(min_length=1, max_length=2000)


class SourceOut(BaseModel):
    """One retrieved chunk cited in an answer."""

    source: str
    chunk: int
    distance: float | None = None
    text: str


class AskResponse(BaseModel):
    """The result of a question, with its citations and confidence."""

    answer: str
    sources: list[SourceOut] = []
    confidence: str
    best_distance: float | None = None
    guardrail: str = "answered"


class QuestionOut(BaseModel):
    """A past question and its answer."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    answer: str | None = None
    confidence: str | None = None
    asked_at: datetime


class HealthOut(BaseModel):
    """Service status."""

    status: str
    ollama: str
    documents: int
    chunks: int
