"""Net-worth snapshot recompute — SPEC §3.1.

The last pipeline stage (``… → Dedup → DB → Recompute snapshot (serialized)``).
Net worth is recomputed **on ingest** (not on read) so the dashboard loads fast,
onto a fixed **month-end grid** rather than each account's ragged ``period_end``.

Two ideas do all the work:

  **Carry-forward.** For an account and a grid date ``G``, the account's value is the
  ``closing_balance`` of its most recent statement with ``period_end <= G`` (SPEC §3.1
  step 2). If no statement exists at/before ``G`` the account contributes nothing.
  ``net_worth(G) = cash + portfolio − liability`` over all accounts, carried forward.

  **Event-driven window.** Ingesting a statement for account ``A`` with
  ``period_end = D`` only changes grid points from ``grid(D)`` up to (but not
  including) ``A``'s *next* statement's grid — because carry-forward propagates the
  new balance forward only until the next known statement. So a backfilled Feb (after
  Mar already exists) updates only Feb; a lone statement carries forward to the
  household's data horizon. See ``affected_grids``.

**RDN ↔ broker-cash (the flagged double-count).** ``portfolio_total`` is holdings
**market value only** — SPEC §3.1 says net worth stacks "portfolio market value",
not broker cash. The broker's cash (Ajaib "Saldo RDN" / Stockbit "Cash Investor") is
the *same rupiah* as a BCA Tapres/RDN savings balance, so it is counted **once**, on
the bank side, via that savings account's ``closing_balance``. The persist stage must
therefore store a portfolio statement's ``closing_balance`` as Σ holdings market value
(excluding cash). No account-number matching is needed here — the identity is resolved
by definition, not by resolving masked account numbers (that stays an S9 concern).

Pure and repo-driven, mirroring the dedup/categorize stages: the engine reads through
the domain repo Protocols only (``AccountRepo`` / ``StatementRepo`` /
``NetworthSnapshotRepo``), so the dependency points inward and it is testable with
in-memory fakes. Recompute is **serialized per household** via an injected
``HouseholdRecomputeLock`` so a web upload and a Telegram ingest can't race the
snapshot (SPEC §3.1). Because each grid point is recomputed from scratch, recompute is
idempotent — re-running it converges to the same snapshot.
"""

from __future__ import annotations

import calendar
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum, auto
from typing import Protocol

from coffer.domain.entities import Account, NetworthSnapshot, Statement
from coffer.domain.enums import AccountType
from coffer.domain.repositories import AccountRepo, NetworthSnapshotRepo, StatementRepo


class _Bucket(StrEnum):
    """Which line of ``networth_snapshot`` an account's value feeds."""

    CASH = auto()
    LIABILITY = auto()
    PORTFOLIO = auto()


# account_type → net-worth bucket. Every AccountType must appear here; an unknown
# type raises (refuse to silently drop an account from net worth — cf. validate.py).
_BUCKETS: dict[AccountType, _Bucket] = {
    AccountType.BCA_SAVINGS: _Bucket.CASH,
    AccountType.BCA_CREDIT_CARD: _Bucket.LIABILITY,
    AccountType.CIMB_CREDIT_CARD: _Bucket.LIABILITY,
    AccountType.AJAIB_PORTFOLIO: _Bucket.PORTFOLIO,
    AccountType.STOCKBIT_PORTFOLIO: _Bucket.PORTFOLIO,
}


def _bucket_of(account_type: AccountType) -> _Bucket:
    try:
        return _BUCKETS[account_type]
    except KeyError:  # a new AccountType shipped without a net-worth rule — programmer error
        raise ValueError(f"no net-worth bucket for account_type {account_type!r}") from None


# ── month-end grid helpers ──────────────────────────────────────────────────────────
def month_end(day: date) -> date:
    """The calendar month-end of ``day``'s month — the §3.1 grid granularity."""
    last = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, last)


def _next_month_end(grid: date) -> date:
    """The month-end after ``grid`` (which is assumed to be a month-end)."""
    year, month = (grid.year + 1, 1) if grid.month == 12 else (grid.year, grid.month + 1)
    return month_end(date(year, month, 1))


def iter_month_ends(start: date, end: date) -> Iterator[date]:
    """Month-end grid points from ``start``'s month through ``end``'s month, inclusive."""
    grid = month_end(start)
    stop = month_end(end)
    while grid <= stop:
        yield grid
        grid = _next_month_end(grid)


# ── carry-forward + aggregation (pure) ──────────────────────────────────────────────
def _carried_value(statements: Sequence[Statement], grid: date) -> Decimal | None:
    """The ``closing_balance`` of the most recent statement with ``period_end <= grid``.

    ``statements`` is ordered by ``period_end`` ascending (the repo guarantees it).
    A statement whose ``closing_balance`` is ``None`` is not a net-worth data point,
    so the prior balance keeps carrying. ``None`` here means "account absent at grid".
    """
    value: Decimal | None = None
    for stmt in statements:
        if stmt.period_end > grid:
            break
        if stmt.closing_balance is not None:
            value = stmt.closing_balance
    return value


def compute_snapshot(
    *,
    household_id: int,
    grid_date: date,
    accounts: Sequence[Account],
    statements_by_account: Mapping[int, Sequence[Statement]],
) -> NetworthSnapshot:
    """The household's carried-forward net worth at one grid point (SPEC §3.1 step 3)."""
    totals: dict[_Bucket, Decimal] = {b: Decimal("0") for b in _Bucket}
    for account in accounts:
        if account.id is None:
            continue
        value = _carried_value(statements_by_account.get(account.id, ()), grid_date)
        if value is None:
            continue
        totals[_bucket_of(account.account_type)] += value

    cash = totals[_Bucket.CASH]
    liability = totals[_Bucket.LIABILITY]
    portfolio = totals[_Bucket.PORTFOLIO]
    return NetworthSnapshot(
        household_id=household_id,
        grid_date=grid_date,
        cash_total=cash,
        credit_liability_total=liability,
        portfolio_total=portfolio,
        net_worth=cash + portfolio - liability,
    )


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
