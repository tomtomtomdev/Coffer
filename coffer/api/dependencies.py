"""FastAPI dependency wiring — construct the ingestion use-case from env config.

This is the composition root: it reads ``Settings`` from the environment (never
hardcoded — SPEC §6), builds the concrete SQL repos + infra adapters, and hands the
router a ready ``IngestStatement``. A single ``InProcessRecomputeLock`` is shared across
requests so recompute stays serialized per household (SPEC §3.1) within this process.

Everything env-dependent is behind ``functools.lru_cache`` so importing this module (or
the app) touches no environment; tests override ``get_ingest_use_case`` and never hit
the env / DB at all.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from coffer.api.adapters import FilesystemStatementArchive, PdfPlumberReader
from coffer.api.parsing import PARSERS
from coffer.ingestion.pipeline import IngestStatement
from coffer.ingestion.recompute import InProcessRecomputeLock
from coffer.persistence.config import Settings
from coffer.persistence.crypto import FieldCipher
from coffer.persistence.db import create_db_engine, create_session_factory
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlCategoryRepo,
    SqlHoldingRepo,
    SqlLearnedRuleRepo,
    SqlMemberRepo,
    SqlNetworthSnapshotRepo,
    SqlStatementRepo,
    SqlTransactionRepo,
)

STATEMENT_ARCHIVE_DIR_ENV = "COFFER_STATEMENT_ARCHIVE_DIR"


@lru_cache
def _settings() -> Settings:
    return Settings.from_env()


@lru_cache
def _engine() -> Engine:
    return create_db_engine(_settings().database_url)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return create_session_factory(_engine())


@lru_cache
def _cipher() -> FieldCipher:
    return FieldCipher(_settings().encryption_key)


@lru_cache
def _recompute_lock() -> InProcessRecomputeLock:
    return InProcessRecomputeLock()


@lru_cache
def _archive() -> FilesystemStatementArchive:
    base = Path(os.environ.get(STATEMENT_ARCHIVE_DIR_ENV, "statement_archive"))
    return FilesystemStatementArchive(base, _cipher())


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def build_ingest_use_case(session: Session) -> IngestStatement:
    """Wire concrete SQL repos + infra adapters into the orchestrator for one session."""
    return IngestStatement(
        accounts=SqlAccountRepo(session),
        members=SqlMemberRepo(session),
        statements=SqlStatementRepo(session),
        transactions=SqlTransactionRepo(session),
        categories=SqlCategoryRepo(session),
        learned_rules=SqlLearnedRuleRepo(session),
        holdings=SqlHoldingRepo(session),
        snapshots=SqlNetworthSnapshotRepo(session),
        reader=PdfPlumberReader(),
        parsers=PARSERS,
        archive=_archive(),
        lock=_recompute_lock(),
        clock=_now,
    )


def get_ingest_use_case() -> Iterator[IngestStatement]:
    """Per-request use-case bound to one unit-of-work: commit on success, roll back on
    error (the ``Session`` context manager rolls back if ``commit`` isn't reached)."""
    with _session_factory()() as session:
        yield build_ingest_use_case(session)
        session.commit()
