"""Alembic migration test (S4 DoD: migration up AND down).

Runs the migration against a throwaway database so it never touches the repo-test
schema: ``upgrade head`` creates the full SPEC §2 schema, ``downgrade base`` removes
it (leaving only ``alembic_version``), and ``upgrade head`` again proves the cycle is
repeatable.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from coffer.persistence.crypto import FieldCipher

_MIGRATION_DB = "coffer_test_migrations"
_SPEC_TABLES = {
    "household",
    "member",
    "account",
    "institution_credential",
    "statement",
    "transaction",
    "category",
    "override",
    "learned_rule",
    "holding",
    "networth_snapshot",
}


def _public_tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
            return set(rows)
    finally:
        engine.dispose()


@pytest.fixture
def migration_url(database_url: str) -> Iterator[str]:
    base, _, _ = database_url.rpartition("/")
    admin_url = f"{base}/postgres"
    target_url = f"{base}/{_MIGRATION_DB}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_MIGRATION_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{_MIGRATION_DB}"'))
    try:
        yield target_url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{_MIGRATION_DB}" WITH (FORCE)'))
        admin.dispose()


def test_migration_up_down_up(migration_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # env.py reads both of these from the environment.
    monkeypatch.setenv("COFFER_DATABASE_URL", migration_url)
    monkeypatch.setenv("COFFER_ENCRYPTION_KEY", FieldCipher.generate_key().decode())
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    assert _SPEC_TABLES <= _public_tables(migration_url)

    command.downgrade(config, "base")
    remaining = _public_tables(migration_url)
    assert _SPEC_TABLES.isdisjoint(remaining)  # every SPEC table dropped
    assert remaining <= {"alembic_version"}

    command.upgrade(config, "head")  # repeatable
    assert _SPEC_TABLES <= _public_tables(migration_url)
