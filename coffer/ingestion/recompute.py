"""Net-worth snapshot recompute — SPEC §3.1.

The last pipeline stage (``… → Dedup → DB → Recompute snapshot (serialized)``).
Net worth is recomputed **on ingest** (not on read) so the dashboard loads fast,
onto a fixed **month-end grid** rather than each account's ragged ``period_end``.

The pure carry-forward engine (the month-end grid, per-account carry-forward, the
``account_type`` → bucket classification, and ``compute_snapshot``) lives in
``coffer.domain.networth`` so this ingest-time stage and the dashboard read model share
one implementation. This module owns the parts that are *specific to ingest*:

  **Event-driven window.** Ingesting a statement for account ``A`` with
  ``period_end = D`` only changes grid points from ``grid(D)`` up to (but not including)
  ``A``'s *next* statement's grid — because carry-forward propagates the new balance
  forward only until the next known statement. So a backfilled Feb (after Mar already
  exists) updates only Feb; a lone statement carries forward to the household's data
  horizon. See ``affected_grids``.

  **Serialization.** Recompute is serialized per household via an injected
  ``HouseholdRecomputeLock`` so a web upload and a Telegram ingest can't race the
  snapshot (SPEC §3.1). Because each grid point is recomputed from the full statement
  history, recompute is idempotent — re-running it converges to the same snapshot.

``month_end`` / ``iter_month_ends`` / ``compute_snapshot`` are re-exported from this
module for the recompute call-sites and their existing tests.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from coffer.domain.entities import Account, NetworthSnapshot, Statement
from coffer.domain.networth import compute_snapshot, iter_month_ends, month_end
from coffer.domain.repositories import AccountRepo, NetworthSnapshotRepo, StatementRepo

__all__ = [
    "HouseholdRecomputeLock",
    "InProcessRecomputeLock",
    "affected_grids",
    "compute_snapshot",
    "iter_month_ends",
    "month_end",
    "recompute_all",
    "recompute_for_statement",
]


def affected_grids(
    *, period_end: date, account_period_ends: Sequence[date], horizon: date
) -> list[date]:
    """Grid points a newly-ingested statement changes (SPEC §3.1 recompute semantics).

    ``account_period_ends`` are all of the ingested account's statement ``period_end``
    dates (including the new one); ``horizon`` is the latest ``period_end`` across the
    whole household (how far carry-forward can reach). Returns ``grid(period_end)`` up
    to — but not including — the grid of the account's next statement; or through the
    horizon if there is none. Empty when a later same-month statement already owns the
    only grid point in range.
    """
    start = month_end(period_end)
    later = [pe for pe in account_period_ends if pe > period_end]
    if later:
        next_grid = month_end(min(later))
        return [g for g in iter_month_ends(start, next_grid) if g < next_grid]
    return list(iter_month_ends(start, horizon))


# ── serialization: one writer per household (SPEC §3.1) ──────────────────────────────
class HouseholdRecomputeLock(Protocol):
    """A mutual-exclusion scope keyed by household, so concurrent ingests (web +
    Telegram) can't interleave a recompute for the same household."""

    def for_household(self, household_id: int) -> AbstractContextManager[None]: ...


class InProcessRecomputeLock:
    """Thread-level lock per household for a single-process deployment.

    A multi-process deployment (separate webhook + web workers) must instead use a
    cross-process lock — a Postgres advisory lock (``pg_advisory_xact_lock`` on the
    household id) is the natural fit and shares the recompute transaction's lifetime.
    """

    def __init__(self) -> None:
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    def for_household(self, household_id: int) -> AbstractContextManager[None]:
        with self._guard:
            lock = self._locks.setdefault(household_id, threading.Lock())
        return self._hold(lock)

    @contextmanager
    def _hold(self, lock: threading.Lock) -> Iterator[None]:
        with lock:
            yield


# ── repo-driven recompute ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _HouseholdData:
    accounts: list[Account]
    statements_by_account: dict[int, list[Statement]]
    horizon: date | None  # latest period_end across the household; None if no statements


def _load(household_id: int, accounts: AccountRepo, statements: StatementRepo) -> _HouseholdData:
    accts = accounts.list_by_household(household_id)
    by_account: dict[int, list[Statement]] = {}
    horizon: date | None = None
    for account in accts:
        if account.id is None:
            continue
        stmts = statements.list_by_account(account.id)
        by_account[account.id] = stmts
        for stmt in stmts:
            if horizon is None or stmt.period_end > horizon:
                horizon = stmt.period_end
    return _HouseholdData(accts, by_account, horizon)


def _write(
    *,
    household_id: int,
    grids: Sequence[date],
    data: _HouseholdData,
    snapshots: NetworthSnapshotRepo,
) -> list[NetworthSnapshot]:
    written: list[NetworthSnapshot] = []
    for grid in grids:
        snapshot = compute_snapshot(
            household_id=household_id,
            grid_date=grid,
            accounts=data.accounts,
            statements_by_account=data.statements_by_account,
        )
        written.append(snapshots.upsert(snapshot))
    return written


def recompute_for_statement(
    *,
    household_id: int,
    account_id: int,
    period_end: date,
    accounts: AccountRepo,
    statements: StatementRepo,
    snapshots: NetworthSnapshotRepo,
    lock: HouseholdRecomputeLock,
) -> list[NetworthSnapshot]:
    """Recompute only the grid points a just-ingested statement changes (SPEC §3.1).

    Serialized per household. Idempotent: the affected grids are recomputed from the
    full statement history, so re-running with the same data upserts the same values.
    """
    with lock.for_household(household_id):
        data = _load(household_id, accounts, statements)
        account_period_ends = [s.period_end for s in data.statements_by_account.get(account_id, [])]
        if not account_period_ends or data.horizon is None:
            return []
        grids = affected_grids(
            period_end=period_end,
            account_period_ends=account_period_ends,
            horizon=data.horizon,
        )
        return _write(household_id=household_id, grids=grids, data=data, snapshots=snapshots)


def recompute_all(
    *,
    household_id: int,
    accounts: AccountRepo,
    statements: StatementRepo,
    snapshots: NetworthSnapshotRepo,
    lock: HouseholdRecomputeLock,
) -> list[NetworthSnapshot]:
    """Rebuild every grid point from the earliest statement to the horizon.

    A full rebuild for onboarding / after a reparse; serialized per household. The
    event-driven ``recompute_for_statement`` is the hot path on ingest.
    """
    with lock.for_household(household_id):
        data = _load(household_id, accounts, statements)
        if data.horizon is None:
            return []
        earliest = min(s.period_end for stmts in data.statements_by_account.values() for s in stmts)
        grids = list(iter_month_ends(earliest, data.horizon))
        return _write(household_id=household_id, grids=grids, data=data, snapshots=snapshots)
