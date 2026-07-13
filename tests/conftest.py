"""Shared fixtures for the persistence tests (S4).

Tests run against a **real Postgres** (per the sqlalchemy-2x skill — SQLite differs
on ``NUMERIC``, locking, and ``ON CONFLICT``). The connection URL comes from
``COFFER_DATABASE_URL`` (CI sets it; a local default points at ``coffer_test``).

Isolation: each test runs inside an outer transaction that is rolled back on teardown,
so repos can ``flush`` freely and no test leaks rows into the next.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from coffer.persistence.crypto import FieldCipher
from coffer.persistence.models import Base

_DEFAULT_URL = "postgresql+psycopg://coffer:coffer@localhost:5432/coffer_test"


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("COFFER_DATABASE_URL", _DEFAULT_URL)


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    # Fresh schema built straight from the ORM metadata (equivalent to the migration —
    # `alembic check` confirms no drift). Migration up/down is tested separately.
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    outer = connection.begin()
    sess = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        outer.rollback()
        connection.close()


@pytest.fixture(scope="session")
def cipher() -> FieldCipher:
    return FieldCipher(FieldCipher.generate_key())
