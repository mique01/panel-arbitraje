from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.storage.db import Base, build_session_factory, session_scope
from app.storage.repository import PersistenceService


@lru_cache(maxsize=1)
def get_runtime():
    settings = get_settings()
    session_factory, engine = build_session_factory(settings)
    Base.metadata.create_all(engine)
    repository = PersistenceService(lambda: session_scope(session_factory))
    repository.ensure_defaults()
    return {
        "settings": settings,
        "session_factory": session_factory,
        "engine": engine,
        "repository": repository,
    }
