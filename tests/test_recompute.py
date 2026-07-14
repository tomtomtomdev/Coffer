"""S7 — net-worth snapshot recompute (SPEC §3.1).

Exercises the pure recompute engine with in-memory fakes over the domain repo
Protocols (mirrors the dedup/categorize tests — no Postgres; the repo round-trips
are S4's job). Four things under test:

  * **month-end grid + carry-forward** — async ``period_end`` dates all resolve to
    the same month-end grid point; an account's value carries forward from its most
    recent statement ``<=`` the grid date.
  * **bucketing + RDN no-double-count** — cash / liability / portfolio split by
    ``account_type``; ``portfolio_total`` is holdings market value ONLY (broker cash
    is counted once via the mirroring BCA RDN savings account — SPEC §3.1).
  * **affected-grids window** — a backfilled statement updates only the grid points
    it actually changes (Feb-after-Mar touches only Feb), carrying forward across a
    gap up to the next statement / the horizon.
  * **serialization** — recompute runs under a per-household lock; the in-process
    lock serializes same-household work and lets different households proceed.
"""

from __future__ import annotations

import datetime
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal

from coffer.domain.entities import Account, NetworthSnapshot, Statement
from coffer.domain.enums import AccountType, UploadedVia
from coffer.ingestion.recompute import (
    HouseholdRecomputeLock,
    InProcessRecomputeLock,
    affected_grids,
    compute_snapshot,
    iter_month_ends,
    month_end,
    recompute_all,
    recompute_for_statement,
)

HOUSEHOLD = 1

# Month-end grid points used across the tests.
JAN = datetime.date(2026, 1, 31)
FEB = datetime.date(2026, 2, 28)
MAR = datetime.date(2026, 3, 31)
APR = datetime.date(2026, 4, 30)
MAY = datetime.date(2026, 5, 31)
JUN = datetime.date(2026, 6, 30)


# ── builders ─────────────────────────────────────────────────────────────────────
def acct(id_: int, account_type: AccountType, *, number: str | None = None) -> Account:
    return Account(
        id=id_,
        member_id=1,
        institution="x",
        account_type=account_type,
        account_number_masked=number or f"acct{id_}",
    )


def stmt(account_id: int, period_end: datetime.date, closing: Decimal | None) -> Statement:
    return Statement(
        account_id=account_id,
        period_start=period_end.replace(day=1),
        period_end=period_end,
        file_hash=f"f-{account_id}-{period_end.isoformat()}",
        content_hash=f"c-{account_id}-{period_end.isoformat()}",
        uploaded_via=UploadedVia.WEB,
        uploaded_at=datetime.datetime(2026, 7, 1, 12, 0),
        parser_version="test",
        is_encrypted=True,
        closing_balance=closing,
    )


# ── in-memory fakes over the domain Protocols ──────────────────────────────────────
class FakeAccountRepo:
    def __init__(self, accounts: list[Account]) -> None:
        self._accounts = accounts

    def list_by_household(self, household_id: int) -> list[Account]:
        return list(self._accounts)

    # Rest of AccountRepo — unused by recompute.
    def add(self, account: Account) -> Account:
        raise NotImplementedError

    def get(self, account_id: int) -> Account | None:
        raise NotImplementedError

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        raise NotImplementedError


class FakeStatementRepo:
    def __init__(self, statements: list[Statement]) -> None:
        self._statements = statements

    def add(self, statement: Statement) -> Statement:
        self._statements.append(statement)
        return statement

    def list_by_account(self, account_id: int) -> list[Statement]:
        # SqlStatementRepo orders by period_end; the engine relies on that.
        return sorted(
            (s for s in self._statements if s.account_id == account_id),
            key=lambda s: s.period_end,
        )

    # Rest of StatementRepo — unused by recompute.
    def get(self, statement_id: int) -> Statement | None:
        raise NotImplementedError

    def by_file_hash(self, file_hash: str) -> Statement | None:
        raise NotImplementedError

    def by_content_hash(self, content_hash: str) -> Statement | None:
        raise NotImplementedError


class FakeSnapshotRepo:
    def __init__(self, events: list[str] | None = None) -> None:
        self._by_grid: dict[datetime.date, NetworthSnapshot] = {}
        self._events = events
        self._next_id = 1

    def upsert(self, snapshot: NetworthSnapshot) -> NetworthSnapshot:
        if self._events is not None:
            self._events.append(f"upsert:{snapshot.grid_date.isoformat()}")
        existing = self._by_grid.get(snapshot.grid_date)
        stored = NetworthSnapshot(
            household_id=snapshot.household_id,
            grid_date=snapshot.grid_date,
            cash_total=snapshot.cash_total,
            credit_liability_total=snapshot.credit_liability_total,
            portfolio_total=snapshot.portfolio_total,
            net_worth=snapshot.net_worth,
            id=existing.id if existing else self._next_id,
        )
        if existing is None:
            self._next_id += 1
        self._by_grid[snapshot.grid_date] = stored
        return stored

    def by_grid(self, household_id: int, grid_date: datetime.date) -> NetworthSnapshot | None:
        return self._by_grid.get(grid_date)

    def list_by_household(self, household_id: int) -> list[NetworthSnapshot]:
        return [self._by_grid[g] for g in sorted(self._by_grid)]


class FakeSnapshotRepoWithEvents:
    """Decorates a ``FakeSnapshotRepo`` to record upserts into a shared event list
    while delegating storage — lets a test assert exactly which grids were touched."""

    def __init__(self, inner: FakeSnapshotRepo, events: list[str]) -> None:
        self._inner = inner
        self._events = events

    def upsert(self, snapshot: NetworthSnapshot) -> NetworthSnapshot:
        self._events.append(f"upsert:{snapshot.grid_date.isoformat()}")
        return self._inner.upsert(snapshot)

    def by_grid(self, household_id: int, grid_date: datetime.date) -> NetworthSnapshot | None:
        return self._inner.by_grid(household_id, grid_date)

    def list_by_household(self, household_id: int) -> list[NetworthSnapshot]:
        return self._inner.list_by_household(household_id)


class SpyLock:
    """Records enter/exit around the recompute body so a test can assert the work
    happened inside the per-household critical section."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def for_household(self, household_id: int) -> AbstractContextManager[None]:
        return self._span(household_id)

    @contextmanager
    def _span(self, household_id: int) -> Iterator[None]:
        self._events.append(f"enter:{household_id}")
        try:
            yield
        finally:
            self._events.append(f"exit:{household_id}")


def _lock() -> HouseholdRecomputeLock:
    return InProcessRecomputeLock()


# ── grid helpers ───────────────────────────────────────────────────────────────────
def test_month_end_handles_month_lengths_and_leap_february() -> None:
    assert month_end(datetime.date(2026, 2, 10)) == FEB  # 2026 not a leap year
    assert month_end(datetime.date(2024, 2, 10)) == datetime.date(2024, 2, 29)  # leap
    assert month_end(datetime.date(2026, 6, 30)) == JUN
    assert month_end(datetime.date(2026, 12, 1)) == datetime.date(2026, 12, 31)


def test_iter_month_ends_is_inclusive_and_crosses_year_boundary() -> None:
    assert list(iter_month_ends(FEB, APR)) == [FEB, MAR, APR]
    assert list(iter_month_ends(JUN, JUN)) == [JUN]
    assert list(iter_month_ends(datetime.date(2025, 12, 31), FEB)) == [
        datetime.date(2025, 12, 31),
        JAN,
        FEB,
    ]


# ── carry-forward + async period-end alignment ─────────────────────────────────────
def test_async_period_ends_align_to_one_grid_point() -> None:
    # A savings statement closes at month-end, a card at a mid-cycle day, a broker at
    # month-end — all three resolve to the same Jun grid point (SPEC §3.1).
    accounts = [
        acct(1, AccountType.BCA_SAVINGS),
        acct(2, AccountType.BCA_CREDIT_CARD),
        acct(3, AccountType.AJAIB_PORTFOLIO),
    ]
    statements = {
        1: [stmt(1, JUN, Decimal("10000000.00"))],
        2: [stmt(2, datetime.date(2026, 6, 18), Decimal("2000000.00"))],
        3: [stmt(3, JUN, Decimal("8000000.00"))],
    }
    snap = compute_snapshot(
        household_id=HOUSEHOLD,
        grid_date=JUN,
        accounts=accounts,
        statements_by_account=statements,
    )
    assert snap.cash_total == Decimal("10000000.00")
    assert snap.credit_liability_total == Decimal("2000000.00")  # Jun-18 card carried to Jun-end
    assert snap.portfolio_total == Decimal("8000000.00")
    assert snap.net_worth == Decimal("16000000.00")  # cash + portfolio − liability


def test_value_carries_forward_when_no_statement_at_grid() -> None:
    accounts = [acct(1, AccountType.BCA_SAVINGS)]
    statements = {1: [stmt(1, MAY, Decimal("10000000.00"))]}
    # No June statement — May's balance carries forward to the June grid point.
    jun = compute_snapshot(
        household_id=HOUSEHOLD, grid_date=JUN, accounts=accounts, statements_by_account=statements
    )
    assert jun.cash_total == Decimal("10000000.00")
    # Before the first statement the account contributes nothing.
    apr = compute_snapshot(
        household_id=HOUSEHOLD, grid_date=APR, accounts=accounts, statements_by_account=statements
    )
    assert apr.cash_total == Decimal("0")
    assert apr.net_worth == Decimal("0")


def test_most_recent_statement_wins_at_grid() -> None:
    accounts = [acct(1, AccountType.BCA_SAVINGS)]
    statements = {1: [stmt(1, APR, Decimal("5000000.00")), stmt(1, MAY, Decimal("7500000.00"))]}
    snap = compute_snapshot(
        household_id=HOUSEHOLD, grid_date=MAY, accounts=accounts, statements_by_account=statements
    )
    assert snap.cash_total == Decimal("7500000.00")


# ── RDN ↔ broker-cash: counted once (SPEC §3.1) ────────────────────────────────────
def test_rdn_broker_cash_not_double_counted() -> None:
    # The BCA Tapres/RDN savings balance and the broker's reported cash are the SAME
    # rupiah. portfolio_total is holdings market value ONLY (§3.1 "portfolio market
    # value"); the cash is counted once via the RDN savings account. No double count.
    rdn_savings = acct(1, AccountType.BCA_SAVINGS, number="4958xxxx")  # Ajaib RDN
    ajaib = acct(2, AccountType.AJAIB_PORTFOLIO)
    statements = {
        1: [stmt(1, JUN, Decimal("5000000.00"))],  # the RDN cash
        2: [stmt(2, JUN, Decimal("20000000.00"))],  # holdings market value only
    }
    snap = compute_snapshot(
        household_id=HOUSEHOLD,
        grid_date=JUN,
        accounts=[rdn_savings, ajaib],
        statements_by_account=statements,
    )
    assert snap.cash_total == Decimal("5000000.00")  # RDN cash, once
    assert snap.portfolio_total == Decimal("20000000.00")  # market value, no cash added
    assert snap.net_worth == Decimal("25000000.00")


def test_every_account_type_maps_to_a_networth_bucket() -> None:
    # A completeness guard: if a new AccountType ships, it must be bucketed (else it
    # would be silently dropped from net worth). Each type contributes to exactly one.
    for account_type in AccountType:
        accounts = [acct(1, account_type)]
        statements = {1: [stmt(1, JUN, Decimal("1000000.00"))]}
        snap = compute_snapshot(
            household_id=HOUSEHOLD,
            grid_date=JUN,
            accounts=accounts,
            statements_by_account=statements,
        )
        contributions = [snap.cash_total, snap.credit_liability_total, snap.portfolio_total]
        assert sum(c != 0 for c in contributions) == 1


def test_none_closing_balance_contributes_nothing() -> None:
    accounts = [acct(1, AccountType.BCA_SAVINGS)]
    statements = {1: [stmt(1, JUN, None)]}
    snap = compute_snapshot(
        household_id=HOUSEHOLD, grid_date=JUN, accounts=accounts, statements_by_account=statements
    )
    assert snap.cash_total == Decimal("0")


# ── affected-grids window (event-driven recompute) ──────────────────────────────────
def test_backfill_updates_only_the_backfilled_grid() -> None:
    # Feb arrives after Mar already exists for the same account → only Feb recomputes
    # (Mar's value is still carried by the Mar statement). SPEC §3.1 backfill semantics.
    grids = affected_grids(period_end=FEB, account_period_ends=[FEB, MAR], horizon=MAR)
    assert grids == [FEB]


def test_carry_forward_spans_gap_up_to_next_statement() -> None:
    # Feb statement, next same-account statement is Apr → Feb carries through March.
    grids = affected_grids(
        period_end=FEB, account_period_ends=[FEB, datetime.date(2026, 4, 15)], horizon=APR
    )
    assert grids == [FEB, MAR]


def test_no_next_statement_recomputes_to_horizon() -> None:
    # No later statement for this account, but another account extends the household
    # horizon to April → this account's value carries forward to the horizon.
    grids = affected_grids(period_end=JAN, account_period_ends=[JAN], horizon=APR)
    assert grids == [JAN, FEB, MAR, APR]


def test_first_statement_recomputes_only_its_own_grid() -> None:
    grids = affected_grids(period_end=MAR, account_period_ends=[MAR], horizon=MAR)
    assert grids == [MAR]


def test_mid_month_statement_superseded_same_month_recomputes_nothing() -> None:
    # A Jun-18 statement followed by a Jun-30 one for the same account: the only grid
    # point (Jun-end) is owned by Jun-30, so Jun-18 changes no grid point.
    grids = affected_grids(
        period_end=datetime.date(2026, 6, 18),
        account_period_ends=[
            datetime.date(2026, 6, 18),
            JUN,
        ],
        horizon=JUN,
    )
    assert grids == []


# ── repo-driven recompute ───────────────────────────────────────────────────────────
def test_recompute_all_writes_one_snapshot_per_grid() -> None:
    accounts = FakeAccountRepo(
        [acct(1, AccountType.BCA_SAVINGS), acct(2, AccountType.BCA_CREDIT_CARD)]
    )
    statements = FakeStatementRepo(
        [
            stmt(1, MAY, Decimal("10000000.00")),
            stmt(1, JUN, Decimal("11000000.00")),
            stmt(2, JUN, Decimal("2000000.00")),
        ]
    )
    snapshots = FakeSnapshotRepo()
    recompute_all(
        household_id=HOUSEHOLD,
        accounts=accounts,
        statements=statements,
        snapshots=snapshots,
        lock=_lock(),
    )
    stored = snapshots.list_by_household(HOUSEHOLD)
    assert [s.grid_date for s in stored] == [MAY, JUN]
    # May: only savings has a statement (10M cash, no liability yet).
    assert stored[0].cash_total == Decimal("10000000.00")
    assert stored[0].credit_liability_total == Decimal("0")
    assert stored[0].net_worth == Decimal("10000000.00")
    # June: savings 11M − card 2M.
    assert stored[1].cash_total == Decimal("11000000.00")
    assert stored[1].credit_liability_total == Decimal("2000000.00")
    assert stored[1].net_worth == Decimal("9000000.00")


def test_recompute_for_statement_backfill_touches_only_the_backfilled_grid() -> None:
    accounts = FakeAccountRepo([acct(1, AccountType.BCA_SAVINGS)])
    statements = FakeStatementRepo([stmt(1, MAR, Decimal("9000000.00"))])
    snapshots = FakeSnapshotRepo()
    recompute_for_statement(
        household_id=HOUSEHOLD,
        account_id=1,
        period_end=MAR,
        accounts=accounts,
        statements=statements,
        snapshots=snapshots,
        lock=_lock(),
    )
    assert [s.grid_date for s in snapshots.list_by_household(HOUSEHOLD)] == [MAR]

    # A February statement is backfilled after March exists.
    statements.add(stmt(1, FEB, Decimal("4000000.00")))
    events: list[str] = []
    recompute_for_statement(
        household_id=HOUSEHOLD,
        account_id=1,
        period_end=FEB,
        accounts=accounts,
        statements=statements,
        snapshots=FakeSnapshotRepoWithEvents(snapshots, events),
        lock=_lock(),
    )
    # Only the Feb grid was upserted; March is untouched.
    assert events == ["upsert:2026-02-28"]
    stored = {s.grid_date: s for s in snapshots.list_by_household(HOUSEHOLD)}
    assert stored[FEB].cash_total == Decimal("4000000.00")
    assert stored[MAR].cash_total == Decimal("9000000.00")


def test_recompute_is_idempotent() -> None:
    accounts = FakeAccountRepo([acct(1, AccountType.BCA_SAVINGS)])
    statements = FakeStatementRepo([stmt(1, JUN, Decimal("10000000.00"))])
    snapshots = FakeSnapshotRepo()
    for _ in range(2):
        recompute_all(
            household_id=HOUSEHOLD,
            accounts=accounts,
            statements=statements,
            snapshots=snapshots,
            lock=_lock(),
        )
    stored = snapshots.list_by_household(HOUSEHOLD)
    assert len(stored) == 1  # one row per grid, not duplicated
    assert stored[0].id == 1  # upsert updated in place, no new id churn
    assert stored[0].net_worth == Decimal("10000000.00")


def test_recompute_empty_household_writes_nothing() -> None:
    snapshots = FakeSnapshotRepo()
    result = recompute_all(
        household_id=HOUSEHOLD,
        accounts=FakeAccountRepo([]),
        statements=FakeStatementRepo([]),
        snapshots=snapshots,
        lock=_lock(),
    )
    assert result == []
    assert snapshots.list_by_household(HOUSEHOLD) == []


# ── serialization (SPEC §3.1: serialized per household) ─────────────────────────────
def test_recompute_runs_inside_the_household_lock() -> None:
    events: list[str] = []
    accounts = FakeAccountRepo([acct(1, AccountType.BCA_SAVINGS)])
    statements = FakeStatementRepo([stmt(1, JUN, Decimal("10000000.00"))])
    recompute_all(
        household_id=HOUSEHOLD,
        accounts=accounts,
        statements=statements,
        snapshots=FakeSnapshotRepo(events),
        lock=SpyLock(events),
    )
    assert events[0] == "enter:1"
    assert events[-1] == "exit:1"
    assert any(e.startswith("upsert:") for e in events[1:-1])  # work inside the lock


def test_inprocess_lock_serializes_same_household() -> None:
    lock = InProcessRecomputeLock()
    active = 0
    max_active = 0
    guard = threading.Lock()

    def worker() -> None:
        nonlocal active, max_active
        with lock.for_household(HOUSEHOLD):
            with guard:
                active += 1
                max_active = max(max_active, active)
            # hold the lock briefly so overlap would be observable if it weren't serialized
            for _ in range(10000):
                pass
            with guard:
                active -= 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert max_active == 1


def test_inprocess_lock_lets_distinct_households_proceed() -> None:
    lock = InProcessRecomputeLock()
    barrier = threading.Barrier(2, timeout=5)
    reached = []

    def worker(household_id: int) -> None:
        with lock.for_household(household_id):
            # Both threads must be inside their (different) locks at once to pass the
            # barrier — a global lock would deadlock and time out.
            barrier.wait()
            reached.append(household_id)

    t1 = threading.Thread(target=worker, args=(1,))
    t2 = threading.Thread(target=worker, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert sorted(reached) == [1, 2]
