"""Database engine and session management."""

from contextlib import contextmanager
from typing import Iterator

from sqlmodel import SQLModel, Session, create_engine

from .config import get_settings


def _build_engine_url():
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.using_sqlite else {}
    engine = create_engine(settings.database_url, connect_args=connect_args)
    return engine


engine = _build_engine_url()


def init_db() -> None:
    """Create all database tables."""
    from . import models  # noqa: F401 - ensure models are registered

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for scripts or background tasks."""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
