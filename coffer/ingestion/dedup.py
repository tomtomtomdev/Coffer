"""Dedup stage — SPEC §4 "Dedup, three layers".

Runs after validation, before persist. Given the raw statement bytes, the parsed
result and a **resolved** ``account_id`` (account resolution is the orchestrator's
job — S9), it produces a routing decision:

  ``DUPLICATE_FILE``     layer 1 — SHA-256 of the raw bytes already stored: an exact
                         re-upload. Reject the whole statement outright; no rows.
  ``DUPLICATE_CONTENT``  layer 2 — the parser's content-hash fields already stored:
                         a non-byte-identical re-export of the same statement. Reject.
  ``NEW``                the statement is new; layer 3 has split its transactions into
                         the rows to persist (each carrying its ``dedup_key``) and a
                         count of rows skipped because their ``dedup_key`` was already
                         stored — overlapping statement periods dedup per row and the
                         batch is **never** failed for it (SPEC §4).

Pure and repo-driven: it depends only on the domain repo *Protocols*
(``StatementRepo`` / ``TransactionRepo``), never on persistence. The dependency
therefore points inward and the stage is trivially testable with in-memory fakes.
"""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from coffer.domain.repositories import StatementRepo, TransactionRepo
from coffer.parsers.statement_types import (
    ParsedPortfolio,
    ParsedStatement,
    ParsedTransaction,
)

# ASCII unit separator: a byte that never appears in the string fields being joined,
# so field boundaries can't be forged by a value that happens to contain the delimiter.
_SEP = "\x1f"


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(raw: bytes) -> str:
    """Dedup layer 1: SHA-256 (hex) of the raw statement bytes (SPEC §4)."""
    return hashlib.sha256(raw).hexdigest()


def content_hash(parsed: ParsedStatement | ParsedPortfolio) -> str:
    """Dedup layer 2: SHA-256 of the parser's content-hash fields.

    The fields (account number, period/as-of, balances or total market value) come
    from the parsed object's own ``content_hash_fields`` — the parser owns which
    fields identify its content — so a re-export that isn't byte-identical still
    hashes the same and is caught.
    """
    return _sha256_hex(_SEP.join(parsed.content_hash_fields()))


def transaction_dedup_key(
    account_id: int,
    date: datetime.date,
    description: str,
    debit: Decimal,
    credit: Decimal,
) -> str:
    """Dedup layer 3: SHA-256 of ``(account_id, date, description, debit, credit)`` (SPEC §4).

    Amounts use ``str(Decimal)`` — the same canonical form ``ParsedStatement.content_hash_fields``
    uses — so a row re-appearing in an overlapping-period statement (same account, same
    parser) hashes identically.
    """
    return _sha256_hex(
        _SEP.join([str(account_id), date.isoformat(), description, str(debit), str(credit)])
    )


class DedupOutcome(StrEnum):
    NEW = "new"
    DUPLICATE_FILE = "duplicate_file"  # layer 1: exact re-upload
    DUPLICATE_CONTENT = "duplicate_content"  # layer 2: non-byte-identical re-export


@dataclass(frozen=True)
class KeyedTransaction:
    """A not-yet-seen transaction paired with its computed ``dedup_key``.

    The persist stage stores ``transaction`` with ``dedup_key`` verbatim, so the key
    is computed exactly once, here, and never recomputed downstream.
    """

    transaction: ParsedTransaction
    dedup_key: str


@dataclass(frozen=True)
class DedupResult:
    """The dedup stage's decision for one parsed statement/portfolio.

    ``file_hash`` / ``content_hash`` are always returned (even on a duplicate) so the
    orchestrator can stamp the ``Statement`` it persists without recomputing them.
    """

    outcome: DedupOutcome
    file_hash: str
    content_hash: str
    new_transactions: list[KeyedTransaction] = field(default_factory=list)
    duplicate_transaction_count: int = 0

    @property
    def is_duplicate(self) -> bool:
        return self.outcome is not DedupOutcome.NEW


def dedup(
    *,
    raw_bytes: bytes,
    parsed: ParsedStatement | ParsedPortfolio,
    account_id: int,
    statements: StatementRepo,
    transactions: TransactionRepo,
) -> DedupResult:
    """Route a parsed statement through the three dedup layers (SPEC §4)."""
    fh = file_hash(raw_bytes)
    ch = content_hash(parsed)

    # Layer 1 — exact re-upload: reject the whole statement, contribute no rows.
    if statements.by_file_hash(fh) is not None:
        return DedupResult(DedupOutcome.DUPLICATE_FILE, fh, ch)

    # Layer 2 — non-byte-identical re-export of already-stored content.
    if statements.by_content_hash(ch) is not None:
        return DedupResult(DedupOutcome.DUPLICATE_CONTENT, fh, ch)

    # Layer 3 — per-row dedup for overlapping statement periods. A row whose key is
    # already stored (or already seen earlier in THIS batch — the column is unique, so
    # intra-batch duplicates would break the persist) is skipped and logged, never
    # failing the batch.
    new: list[KeyedTransaction] = []
    duplicates = 0
    seen_in_batch: set[str] = set()
    for txn in parsed.transactions:
        key = transaction_dedup_key(account_id, txn.date, txn.description, txn.debit, txn.credit)
        if key in seen_in_batch or transactions.by_dedup_key(key) is not None:
            duplicates += 1
            continue
        seen_in_batch.add(key)
        new.append(KeyedTransaction(txn, key))

    return DedupResult(
        DedupOutcome.NEW,
        fh,
        ch,
        new_transactions=new,
        duplicate_transaction_count=duplicates,
    )
