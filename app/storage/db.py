from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import Settings


Base = declarative_base()


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def build_engine(settings: Settings):
    return create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=_connect_args(settings.database_url),
    )


def build_session_factory(settings: Settings):
    engine = build_engine(settings)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True), engine


@contextmanager
def session_scope(session_factory):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
