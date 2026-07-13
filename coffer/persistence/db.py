"""Engine / session helpers.

Thin wrappers over SQLAlchemy 2.0 so callers (api, tests, alembic) construct an
engine and sessions the same way. The URL comes from ``Settings`` (env) — never
hardcoded here.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_db_engine(database_url: str) -> Engine:
    return create_engine(database_url)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
