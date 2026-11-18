"""SQLAlchemy engine, session factory and declarative base."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Declarative base for every model."""


def _url() -> str:
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        path = Path(url.replace("sqlite:///", "", 1))
        path.parent.mkdir(parents=True, exist_ok=True)
    return url


engine = create_engine(
    _url(),
    connect_args={"check_same_thread": False} if _url().startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI dependency yielding a session, closed when the request ends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """Create any missing tables. Called at startup."""
    from . import models  # noqa: F401  (registers the models on Base)

    Base.metadata.create_all(bind=engine)
