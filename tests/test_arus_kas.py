"""S14 — Arus Kas read model (SPEC §3.5).

The Arus Kas view assembles, from the household's persisted ``Transaction`` + ``Category``
rows, everything the cash-flow screen renders: the monthly income/spend/cash-flow/
savings-rate series (grouped bars + savings line), the headline savings rate (the window
average) + the latest month's cash flow, and the latest month's income-by-category
("Sumber Pendapatan") + spend-by-type ("Belanja per Tipe") breakdown lists. Pure —
exercised here over in-memory fakes; ``compute_arus_kas`` gets one repo-driven test.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from coffer.domain.entities import Account, Category, Transaction
from coffer.domain.enums import AccountType, Cadence, CategoryType
from coffer.domain.read_models import (
    ArusKasView,
    build_arus_kas,
    compute_arus_kas,
)

HOUSEHOLD = 1


def M(year: int, month: int, day: int = 15) -> datetime.date:
    return datetime.date(year, month, day)


_seq = 0


def txn(
    date: datetime.date,
    *,
    debit: str = "0",
    credit: str = "0",
    category_id: int | None = None,
    account_id: int = 1,
    description: str = "x",
    id: int | None = None,
) -> Transaction:
    global _seq
    _seq += 1
    tid = id if id is not None else _seq
    return Transaction(
        id=tid,
        statement_id=1,
        account_id=account_id,
        date=date,
        description=description,
        dedup_key=f"k{tid}",
        debit=Decimal(debit),
        credit=Decimal(credit),
        category_id=category_id,
    )


def cat(
    id: int,
    type_: CategoryType,
    *,
    cadence: Cadence = Cadence.MONTHLY,
    label: str | None = None,
) -> Category:
    return Category(
        id=id,
        household_id=HOUSEHOLD,
        match_pattern="x",
        label=label or f"cat{id}",
        type=type_,
        cadence=cadence,
    )


def acct(id_: int, account_type: AccountType = AccountType.BCA_SAVINGS) -> Account:
    return Account(
        id=id_,
        member_id=1,
        institution="bca",
        account_type=account_type,
        account_number_masked=f"****{id_:04d}",
    )


# ── monthly series + headline ─────────────────────────────────────────────────────────
def test_build_arus_kas_series_and_headline_savings_rate() -> None:
    salary = cat(1, CategoryType.INCOME, cadence=Cadence.IRREGULAR, label="Gaji")
    groceries = cat(2, CategoryType.ROUTINE, label="Belanja Harian")
    txns = [
        txn(M(2026, 1), credit="1000000", category_id=1),
        txn(M(2026, 1), debit="600000", category_id=2),
        txn(M(2026, 2), credit="1000000", category_id=1),
        txn(M(2026, 2), debit="400000", category_id=2),
    ]
    view = build_arus_kas(txns, [salary, groceries])

    assert isinstance(view, ArusKasView)
    assert [m.month for m in view.months] == [datetime.date(2026, 1, 1), datetime.date(2026, 2, 1)]
    assert view.months[0].income == Decimal("1000000")
    assert view.months[0].spend == Decimal("600000")
    assert view.months[0].cash_flow == Decimal("400000")
    assert view.months[1].cash_flow == Decimal("600000")
    # headline = aggregate (Σincome − Σspend) / Σincome over the window.
    assert view.headline_savings_rate == Decimal("1000000") / Decimal("2000000")
    # the latest-month cash flow drives the "Arus Kas · <bulan>" card.
    assert view.latest_month == datetime.date(2026, 2, 1)
    assert view.latest_cash_flow == Decimal("600000")


# ── latest-month breakdown lists ──────────────────────────────────────────────────────
def test_latest_month_income_sources_by_category_sorted_desc() -> None:
    tommy = cat(1, CategoryType.INCOME, cadence=Cadence.IRREGULAR, label="Gaji · Tommy")
    pris = cat(2, CategoryType.INCOME, cadence=Cadence.IRREGULAR, label="Gaji · Priskila")
    groceries = cat(3, CategoryType.ROUTINE, label="Belanja Harian")
    txns = [
        # an earlier month's income must NOT appear in the latest-month breakdown.
        txn(M(2026, 5), credit="9999999", category_id=1),
        txn(M(2026, 5), debit="100000", category_id=3),
        # latest month (June): two income categories.
        txn(M(2026, 6), credit="22000000", category_id=2),
        txn(M(2026, 6), credit="38000000", category_id=1),
        txn(M(2026, 6), debit="500000", category_id=3),
    ]
    view = build_arus_kas(txns, [tommy, pris, groceries])

    assert view.latest_month == datetime.date(2026, 6, 1)
    # sorted by amount desc: Tommy 38M before Priskila 22M; the May income is excluded.
    assert [(s.label, s.amount) for s in view.income_sources] == [
        ("Gaji · Tommy", Decimal("38000000")),
        ("Gaji · Priskila", Decimal("22000000")),
    ]


def test_latest_month_spend_by_type_in_fixed_order_excludes_zero_and_transfers() -> None:
    salary = cat(1, CategoryType.INCOME, cadence=Cadence.IRREGULAR, label="Gaji")
    routine = cat(2, CategoryType.ROUTINE, label="Belanja Harian")
    one_off = cat(3, CategoryType.ONE_OFF, label="Beli Kulkas")
    transfer = cat(4, CategoryType.TRANSFER, label="Pindah Rekening")
    txns = [
        txn(M(2026, 6), credit="10000000", category_id=1),
        txn(M(2026, 6), debit="500000", category_id=2),  # routine
        txn(M(2026, 6), debit="2000000", category_id=3),  # one_off
        txn(M(2026, 6), debit="9000000", category_id=4),  # transfer → excluded
    ]
    view = build_arus_kas(txns, [salary, routine, one_off, transfer])

    # order is routine → discretionary → one_off; discretionary is absent (zero) and dropped;
    # the transfer never appears in spend.
    assert [(s.type, s.amount) for s in view.spend_by_type] == [
        (CategoryType.ROUTINE, Decimal("500000")),
        (CategoryType.ONE_OFF, Decimal("2000000")),
    ]


# ── guards + exclusions ───────────────────────────────────────────────────────────────
def test_savings_rate_none_when_income_zero() -> None:
    groceries = cat(1, CategoryType.ROUTINE, label="Belanja Harian")
    view = build_arus_kas([txn(M(2026, 6), debit="500000", category_id=1)], [groceries])
    assert view.months[0].income == Decimal("0")
    assert view.months[0].savings_rate is None
    assert view.headline_savings_rate is None
    assert view.latest_cash_flow == Decimal("-500000")


def test_transfers_and_investment_moves_excluded_from_flow() -> None:
    salary = cat(1, CategoryType.INCOME, cadence=Cadence.IRREGULAR, label="Gaji")
    transfer = cat(2, CategoryType.TRANSFER, label="Transfer")
    invest = cat(3, CategoryType.INVESTMENT_MOVE, label="Top-up Ajaib")
    txns = [
        txn(M(2026, 6), credit="5000000", category_id=1),
        txn(M(2026, 6), debit="3000000", category_id=2),  # transfer
        txn(M(2026, 6), debit="1000000", category_id=3),  # investment move
    ]
    view = build_arus_kas(txns, [salary, transfer, invest])
    assert view.months[0].income == Decimal("5000000")
    assert view.months[0].spend == Decimal("0")  # neither transfer nor invest is spend
    assert view.spend_by_type == []


def test_uncategorized_excluded_from_income_and_spend() -> None:
    salary = cat(1, CategoryType.INCOME, cadence=Cadence.IRREGULAR, label="Gaji")
    txns = [
        txn(M(2026, 6), credit="5000000", category_id=1),
        txn(M(2026, 6), debit="800000", category_id=None),  # pending a tag → not spend
        txn(M(2026, 6), credit="200000", category_id=None),  # pending a tag → not income
    ]
    view = build_arus_kas(txns, [salary])
    assert view.months[0].income == Decimal("5000000")
    assert view.months[0].spend == Decimal("0")
    assert [s.label for s in view.income_sources] == ["Gaji"]


def test_empty_household() -> None:
    view = build_arus_kas([], [])
    assert view.months == []
    assert view.headline_savings_rate is None
    assert view.latest_month is None
    assert view.latest_cash_flow is None
    assert view.income_sources == []
    assert view.spend_by_type == []


# ── repo-driven wrapper ─────────────────────────────────────────────────────────────--
class _FakeAccountRepo:
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


class _FakeTransactionRepo:
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

    def set_category(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError


class _FakeCategoryRepo:
    def __init__(self, categories: list[Category]) -> None:
        self._categories = categories

    def list_by_household(self, household_id: int) -> list[Category]:
        return list(self._categories)

    def add(self, category: Category) -> Category:
        raise NotImplementedError

    def get(self, category_id: int) -> Category | None:
        raise NotImplementedError


def test_compute_arus_kas_aggregates_across_household_accounts() -> None:
    accounts = _FakeAccountRepo([acct(1), acct(2, AccountType.BCA_CREDIT_CARD)])
    cats = _FakeCategoryRepo(
        [
            cat(1, CategoryType.INCOME, cadence=Cadence.IRREGULAR, label="Gaji"),
            cat(2, CategoryType.ROUTINE, label="Belanja Harian"),
        ]
    )
    txns = _FakeTransactionRepo(
        [
            txn(M(2026, 6), credit="10000000", category_id=1, account_id=1),  # bank income
            txn(M(2026, 6), debit="600000", category_id=2, account_id=1),  # bank spend
            txn(M(2026, 6), debit="1500000", category_id=2, account_id=2),  # card spend
        ]
    )
    view = compute_arus_kas(
        household_id=HOUSEHOLD, accounts=accounts, transactions=txns, categories=cats
    )
    assert isinstance(view, ArusKasView)
    # spend aggregates both the bank debit and the card charge.
    assert view.months[-1].spend == Decimal("2100000")
    assert view.months[-1].income == Decimal("10000000")
    assert view.latest_cash_flow == Decimal("7900000")
