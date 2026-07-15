"""Net-worth carry-forward primitives — SPEC §3.1 (pure domain logic).

The month-end grid, per-account carry-forward, the ``account_type`` → net-worth bucket
classification, and the single-grid-point net-worth computation live here as pure domain
use-case logic. Two call-sites build on them:

  * ``coffer.ingestion.recompute`` — the ingest-time stage that **materializes**
    ``networth_snapshot`` on write (the household series the dashboard loads fast);
  * ``coffer.domain.read_models`` — the dashboard read model, which needs the per-member
    series that is *not* materialized and so computes it on read.

Keeping the engine in the innermost layer means there is **one** carry-forward
implementation, not two that can drift.

Ideas (SPEC §3.1):
  * **Carry-forward** — for an account and a grid date ``G``, the account's value is the
    ``closing_balance`` of its most recent statement with ``period_end <= G``. No statement
    at/before ``G`` → the account contributes nothing to that grid point.
  * **Buckets** — ``net_worth(G) = cash + portfolio − liability`` over all accounts.

Depends on nothing but the domain entities/enums (Clean Architecture, CLAUDE.md).
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from decimal import Decimal
from enum import StrEnum, auto

from coffer.domain.entities import Account, NetworthSnapshot, Statement
from coffer.domain.enums import AccountType


class Bucket(StrEnum):
    """Which line of ``networth_snapshot`` an account's value feeds (SPEC §3.1)."""

    CASH = auto()
    LIABILITY = auto()
    PORTFOLIO = auto()


# account_type → net-worth bucket. Every AccountType must appear here; an unknown
# type raises (refuse to silently drop an account from net worth — cf. validate.py).
BUCKETS: dict[AccountType, Bucket] = {
    AccountType.BCA_SAVINGS: Bucket.CASH,
    AccountType.BCA_CREDIT_CARD: Bucket.LIABILITY,
    AccountType.CIMB_CREDIT_CARD: Bucket.LIABILITY,
    AccountType.AJAIB_PORTFOLIO: Bucket.PORTFOLIO,
    AccountType.STOCKBIT_PORTFOLIO: Bucket.PORTFOLIO,
}


def bucket_of(account_type: AccountType) -> Bucket:
    try:
        return BUCKETS[account_type]
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
def carried_value(statements: Sequence[Statement], grid: date) -> Decimal | None:
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
    """The carried-forward net worth of ``accounts`` at one grid point (SPEC §3.1 step 3).

    Passing the whole household's accounts yields the household snapshot (recompute's
    materialized write); passing one member's accounts yields that member's net worth
    (the dashboard's on-read "Per Anggota" series). The bucketing/carry-forward is
    identical, so both paths share this one function.
    """
    totals: dict[Bucket, Decimal] = {b: Decimal("0") for b in Bucket}
    for account in accounts:
        if account.id is None:
            continue
        value = carried_value(statements_by_account.get(account.id, ()), grid_date)
        if value is None:
            continue
        totals[bucket_of(account.account_type)] += value

    cash = totals[Bucket.CASH]
    liability = totals[Bucket.LIABILITY]
    portfolio = totals[Bucket.PORTFOLIO]
    return NetworthSnapshot(
        household_id=household_id,
        grid_date=grid_date,
        cash_total=cash,
        credit_liability_total=liability,
        portfolio_total=portfolio,
        net_worth=cash + portfolio - liability,
    )
