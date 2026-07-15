"""S11 — Ringkasan (net-worth overview) read model (SPEC §3.1).

The dashboard's query-side use-case: given a household's materialized
``networth_snapshot`` series (S7) plus its accounts / members / statements /
transactions / categories, assemble the Ringkasan payload —

  * the household net-worth series (straight from the materialized snapshot);
  * the **per-member** net-worth series (NOT materialized — computed on read by the
    shared carry-forward engine ``coffer.domain.networth.compute_snapshot`` over each
    member's accounts);
  * the delta vs. the previous month (amount + pct, pct ``None`` when the prior month's
    net worth is zero — div-by-zero guard);
  * per-account latest balance + as-of date + net-worth bucket (Rincian Akun);
  * the KPI row — routine-spend estimate, savings rate, latest monthly cash flow — reusing
    the S8 read models.

Pure and repo-driven (mirrors the S8 read models / recompute): exercised here with
in-memory fakes over the domain Protocols, no Postgres.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from coffer.domain.entities import (
    Account,
    Category,
    Member,
    NetworthSnapshot,
    Statement,
    Transaction,
)
from coffer.domain.enums import AccountType, Cadence, CategoryType, UploadedVia
from coffer.domain.networth import Bucket
from coffer.domain.read_models import (
    RingkasanView,
    compute_ringkasan,
)

HOUSEHOLD = 1
TOMMY, PRISKILA = 1, 2

MAY = datetime.date(2026, 5, 31)
JUN = datetime.date(2026, 6, 30)


# ── builders ─────────────────────────────────────────────────────────────────────────
def member(id_: int, name: str) -> Member:
    return Member(id=id_, household_id=HOUSEHOLD, name=name)


def account(id_: int, member_id: int, account_type: AccountType) -> Account:
    return Account(
        id=id_,
        member_id=member_id,
        institution="bca",
        account_type=account_type,
        account_number_masked=f"****{id_:04d}",
    )


_stmt_seq = 0


def statement(account_id: int, period_end: datetime.date, closing: str | None) -> Statement:
    global _stmt_seq
    _stmt_seq += 1
    return Statement(
        id=_stmt_seq,
        account_id=account_id,
        period_start=datetime.date(period_end.year, period_end.month, 1),
        period_end=period_end,
        file_hash=f"f{_stmt_seq}",
        content_hash=f"c{_stmt_seq}",
        uploaded_via=UploadedVia.WEB,
        uploaded_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        parser_version="v1",
        is_encrypted=False,
        closing_balance=Decimal(closing) if closing is not None else None,
    )


def snapshot(
    grid: datetime.date, *, cash: str, portfolio: str, liability: str, net: str
) -> NetworthSnapshot:
    return NetworthSnapshot(
        household_id=HOUSEHOLD,
        grid_date=grid,
        cash_total=Decimal(cash),
        portfolio_total=Decimal(portfolio),
        credit_liability_total=Decimal(liability),
        net_worth=Decimal(net),
    )


_txn_seq = 0


def txn(
    date: datetime.date,
    account_id: int,
    *,
    debit: str = "0",
    credit: str = "0",
    category_id: int | None = None,
) -> Transaction:
    global _txn_seq
    _txn_seq += 1
    return Transaction(
        id=_txn_seq,
        statement_id=1,
        account_id=account_id,
        date=date,
        description="x",
        dedup_key=f"k{_txn_seq}",
        debit=Decimal(debit),
        credit=Decimal(credit),
        category_id=category_id,
    )


def category(id_: int, type_: CategoryType, cadence: Cadence = Cadence.MONTHLY) -> Category:
    return Category(
        id=id_,
        household_id=HOUSEHOLD,
        match_pattern="x",
        label=f"cat{id_}",
        type=type_,
        cadence=cadence,
    )


# ── in-memory fakes over the domain Protocols ──────────────────────────────────────────
class FakeAccountRepo:
    def __init__(self, accounts: list[Account]) -> None:
        self._accounts = accounts

    def list_by_household(self, household_id: int) -> list[Account]:
        return list(self._accounts)

    def add(self, account: Account) -> Account:
        raise NotImplementedError

    def get(self, account_id: int) -> Account | None:
        raise NotImplementedError

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        raise NotImplementedError


class FakeMemberRepo:
    def __init__(self, members: list[Member]) -> None:
        self._members = members

    def list_by_household(self, household_id: int) -> list[Member]:
        return list(self._members)

    def add(self, member: Member) -> Member:
        raise NotImplementedError

    def get(self, member_id: int) -> Member | None:
        raise NotImplementedError

    def by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        raise NotImplementedError


class FakeStatementRepo:
    def __init__(self, statements: list[Statement]) -> None:
        self._statements = statements

    def list_by_account(self, account_id: int) -> list[Statement]:
        return sorted(
            (s for s in self._statements if s.account_id == account_id),
            key=lambda s: s.period_end,
        )

    def add(self, statement: Statement) -> Statement:
        raise NotImplementedError

    def get(self, statement_id: int) -> Statement | None:
        raise NotImplementedError

    def by_file_hash(self, file_hash: str) -> Statement | None:
        raise NotImplementedError

    def by_content_hash(self, content_hash: str) -> Statement | None:
        raise NotImplementedError


class FakeTransactionRepo:
    def __init__(self, transactions: list[Transaction]) -> None:
        self._transactions = transactions

    def list_by_account(self, account_id: int) -> list[Transaction]:
        return [t for t in self._transactions if t.account_id == account_id]

    def add(self, transaction: Transaction) -> Transaction:
        raise NotImplementedError

    def get(self, transaction_id: int) -> Transaction | None:
        raise NotImplementedError

    def by_dedup_key(self, dedup_key: str) -> Transaction | None:
        raise NotImplementedError


class FakeCategoryRepo:
    def __init__(self, categories: list[Category]) -> None:
        self._categories = categories

    def list_by_household(self, household_id: int) -> list[Category]:
        return list(self._categories)

    def add(self, category: Category) -> Category:
        raise NotImplementedError

    def get(self, category_id: int) -> Category | None:
        raise NotImplementedError


class FakeSnapshotRepo:
    def __init__(self, snapshots: list[NetworthSnapshot]) -> None:
        self._snapshots = snapshots

    def list_by_household(self, household_id: int) -> list[NetworthSnapshot]:
        return sorted(self._snapshots, key=lambda s: s.grid_date)

    def upsert(self, snapshot: NetworthSnapshot) -> NetworthSnapshot:
        raise NotImplementedError

    def by_grid(self, household_id: int, grid_date: datetime.date) -> NetworthSnapshot | None:
        raise NotImplementedError


def _view(
    *,
    accounts: list[Account] | None = None,
    members: list[Member] | None = None,
    statements: list[Statement] | None = None,
    transactions: list[Transaction] | None = None,
    categories: list[Category] | None = None,
    snapshots: list[NetworthSnapshot] | None = None,
) -> RingkasanView:
    return compute_ringkasan(
        household_id=HOUSEHOLD,
        accounts=FakeAccountRepo(accounts or []),
        members=FakeMemberRepo(members or []),
        statements=FakeStatementRepo(statements or []),
        transactions=FakeTransactionRepo(transactions or []),
        categories=FakeCategoryRepo(categories or []),
        snapshots=FakeSnapshotRepo(snapshots or []),
    )


# ── household series + headline ─────────────────────────────────────────────────────
def test_household_series_maps_snapshot_rows() -> None:
    view = _view(
        snapshots=[
            snapshot(MAY, cash="140", portfolio="0", liability="20", net="120"),
            snapshot(JUN, cash="205", portfolio="0", liability="30", net="175"),
        ],
    )
    assert [p.grid_date for p in view.household_series] == [MAY, JUN]
    jun = view.household_series[-1]
    assert (jun.cash, jun.portfolio, jun.liability, jun.net_worth) == (
        Decimal("205"),
        Decimal("0"),
        Decimal("30"),
        Decimal("175"),
    )
    # Headline = the latest grid point.
    assert view.as_of == JUN
    assert view.net_worth == Decimal("175")


def test_delta_vs_previous_month() -> None:
    view = _view(
        snapshots=[
            snapshot(MAY, cash="0", portfolio="0", liability="0", net="80"),
            snapshot(JUN, cash="0", portfolio="0", liability="0", net="120"),
        ],
    )
    assert view.delta is not None
    assert view.delta.amount == Decimal("40")
    assert view.delta.pct == Decimal("0.5")  # 40 / 80


def test_delta_pct_is_none_when_prior_is_zero() -> None:
    view = _view(
        snapshots=[
            snapshot(MAY, cash="0", portfolio="0", liability="0", net="0"),
            snapshot(JUN, cash="0", portfolio="0", liability="0", net="100"),
        ],
    )
    assert view.delta is not None
    assert view.delta.amount == Decimal("100")
    assert view.delta.pct is None  # no divide-by-zero


def test_single_snapshot_has_no_delta() -> None:
    view = _view(snapshots=[snapshot(JUN, cash="0", portfolio="0", liability="0", net="100")])
    assert view.delta is None
    assert view.net_worth == Decimal("100")


# ── per-member series (on-read carry-forward) ─────────────────────────────────────────
def test_member_series_carry_forward() -> None:
    # Tommy: savings + CC (net = cash − liability); Priskila: savings only.
    accounts = [
        account(1, TOMMY, AccountType.BCA_SAVINGS),
        account(2, TOMMY, AccountType.BCA_CREDIT_CARD),
        account(3, PRISKILA, AccountType.BCA_SAVINGS),
    ]
    statements = [
        statement(1, MAY, "100"),
        statement(1, JUN, "150"),
        statement(2, MAY, "20"),
        statement(2, JUN, "30"),
        statement(3, MAY, "40"),
        statement(3, JUN, "55"),
    ]
    # Snapshot rows define the grid the member series aligns to.
    snapshots = [
        snapshot(MAY, cash="140", portfolio="0", liability="20", net="120"),
        snapshot(JUN, cash="205", portfolio="0", liability="30", net="175"),
    ]
    view = _view(
        accounts=accounts,
        members=[member(TOMMY, "Tommy"), member(PRISKILA, "Priskila")],
        statements=statements,
        snapshots=snapshots,
    )
    by_name = {m.member_name: m for m in view.member_series}
    assert set(by_name) == {"Tommy", "Priskila"}
    tommy = by_name["Tommy"]
    assert [(p.grid_date, p.net_worth) for p in tommy.points] == [
        (MAY, Decimal("80")),  # 100 − 20
        (JUN, Decimal("120")),  # 150 − 30
    ]
    priskila = by_name["Priskila"]
    assert [(p.grid_date, p.net_worth) for p in priskila.points] == [
        (MAY, Decimal("40")),
        (JUN, Decimal("55")),
    ]


# ── Rincian Akun (per-account latest balance + bucket) ─────────────────────────────────
def test_account_details_latest_balance_and_bucket() -> None:
    accounts = [
        account(1, TOMMY, AccountType.BCA_SAVINGS),
        account(2, TOMMY, AccountType.BCA_CREDIT_CARD),
        account(3, PRISKILA, AccountType.AJAIB_PORTFOLIO),
        account(4, PRISKILA, AccountType.BCA_SAVINGS),  # no statements yet
    ]
    statements = [
        statement(1, MAY, "100"),
        statement(1, JUN, "150"),  # latest wins
        statement(2, JUN, "30"),
        statement(3, MAY, "500"),
        statement(3, JUN, None),  # a None closing doesn't override the carried balance
    ]
    view = _view(accounts=accounts, statements=statements)
    by_id = {a.account_id: a for a in view.accounts}

    assert by_id[1].balance == Decimal("150")
    assert by_id[1].as_of == JUN
    assert by_id[1].bucket is Bucket.CASH

    assert by_id[2].balance == Decimal("30")
    assert by_id[2].bucket is Bucket.LIABILITY

    # Latest non-None closing carries (Jun's None is ignored).
    assert by_id[3].balance == Decimal("500")
    assert by_id[3].as_of == MAY
    assert by_id[3].bucket is Bucket.PORTFOLIO

    # No statements → absent: zero balance, no as-of, still bucketed by type.
    assert by_id[4].balance == Decimal("0")
    assert by_id[4].as_of is None
    assert by_id[4].bucket is Bucket.CASH


# ── KPI row (reuses the S8 read models) ────────────────────────────────────────────────
def test_kpis_from_spend_and_cashflow_read_models() -> None:
    cats = [category(1, CategoryType.ROUTINE), category(2, CategoryType.INCOME)]
    transactions = [
        txn(datetime.date(2026, 4, 15), 1, debit="300000", category_id=1),
        txn(datetime.date(2026, 4, 25), 1, credit="1000000", category_id=2),
        txn(datetime.date(2026, 5, 15), 1, debit="300000", category_id=1),
        txn(datetime.date(2026, 5, 25), 1, credit="1000000", category_id=2),
        txn(datetime.date(2026, 6, 15), 1, debit="300000", category_id=1),
        txn(datetime.date(2026, 6, 25), 1, credit="1000000", category_id=2),
    ]
    view = _view(
        accounts=[account(1, TOMMY, AccountType.BCA_SAVINGS)],
        transactions=transactions,
        categories=cats,
    )
    assert view.kpis.routine_spend_monthly == Decimal("300000")
    assert view.kpis.routine_annual_amortized == Decimal("0")
    assert view.kpis.savings_rate == Decimal("0.7")  # (3_000_000 − 900_000) / 3_000_000
    assert view.kpis.monthly_cash_flow == Decimal("700000")  # latest month: 1_000_000 − 300_000


def test_kpis_cold_start_when_under_three_months() -> None:
    cats = [category(1, CategoryType.ROUTINE)]
    transactions = [txn(datetime.date(2026, 6, 15), 1, debit="300000", category_id=1)]
    view = _view(
        accounts=[account(1, TOMMY, AccountType.BCA_SAVINGS)],
        transactions=transactions,
        categories=cats,
    )
    assert view.kpis.routine_spend_monthly is None  # cold start (<3 months)


# ── empty household ────────────────────────────────────────────────────────────────────
def test_empty_household() -> None:
    view = _view()
    assert view.household_series == []
    assert view.member_series == []
    assert view.accounts == []
    assert view.as_of is None
    assert view.net_worth == Decimal("0")
    assert view.delta is None
    assert view.kpis.routine_spend_monthly is None
    assert view.kpis.savings_rate is None
    assert view.kpis.monthly_cash_flow is None
