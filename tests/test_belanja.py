"""S13 — Belanja read model (SPEC §3.3).

The Belanja view assembles, from the household's persisted ``Transaction`` + ``Category``
rows, everything the spend screen renders: the routine-spend estimate (headline + base
median + amortized annual), the monthly sparkline series, the per-category median
breakdown, the enriched anomaly rows, the review queue (uncategorized first, then recent
categorized, with a source badge per row) and the full category list for the Tag/Ubah
picker. Pure — exercised here over in-memory fakes; ``compute_belanja`` gets one
repo-driven test.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from coffer.domain.entities import Account, Category, Transaction
from coffer.domain.enums import AccountType, Cadence, CategorySource, CategoryType
from coffer.domain.read_models import (
    BelanjaView,
    build_belanja,
    compute_belanja,
    routine_spend_estimate,
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
    category_source: CategorySource | None = None,
    account_id: int = 1,
    description: str = "x",
    counterparty_acct: str | None = None,
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
        category_source=category_source,
        counterparty_acct=counterparty_acct,
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


# ── monthly sparkline series on the estimate ──────────────────────────────────────────
def test_routine_estimate_exposes_monthly_series_behind_the_headline() -> None:
    cats = [cat(1, CategoryType.ROUTINE)]
    txns = [
        txn(M(2026, 1), debit="100000", category_id=1),
        txn(M(2026, 2), debit="200000", category_id=1),
        txn(M(2026, 3), debit="300000", category_id=1),
    ]
    est = routine_spend_estimate(txns, cats)
    assert [p.month for p in est.monthly_series] == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 2, 1),
        datetime.date(2026, 3, 1),
    ]
    assert [p.total for p in est.monthly_series] == [
        Decimal("100000"),
        Decimal("200000"),
        Decimal("300000"),
    ]
    # the headline base median is the median of exactly these bars.
    assert est.base_median_monthly == Decimal("200000")


def test_cold_start_monthly_series_is_empty() -> None:
    cats = [cat(1, CategoryType.ROUTINE)]
    est = routine_spend_estimate([txn(M(2026, 1), debit="1", category_id=1)], cats)
    assert est.insufficient_data
    assert est.monthly_series == []


# ── the assembled Belanja view ────────────────────────────────────────────────────────
def test_build_belanja_assembles_estimate_breakdown_and_categories() -> None:
    cats = [
        cat(1, CategoryType.ROUTINE, label="Belanja Harian"),
        cat(2, CategoryType.ROUTINE, cadence=Cadence.ANNUAL, label="STNK"),
        cat(3, CategoryType.INCOME, cadence=Cadence.IRREGULAR, label="Gaji"),
    ]
    txns = [txn(M(2026, m), debit="500000", category_id=1) for m in range(1, 7)]
    txns.append(txn(M(2026, 3), debit="1200000", category_id=2))  # annual
    view = build_belanja(txns, cats, [acct(1)])

    assert isinstance(view, BelanjaView)
    assert view.base_median_monthly == Decimal("500000")
    assert view.annual_amortized_monthly == Decimal("100000")  # 1.2M / 12
    assert view.estimate == Decimal("600000")
    assert not view.insufficient_data
    assert len(view.monthly_series) == 6
    # every household category is offered to the picker (not just routine ones).
    assert {c.id for c in view.categories} == {1, 2, 3}
    labels = {c.id: c.label for c in view.categories}
    assert labels[3] == "Gaji"


def test_review_queue_floats_uncategorized_first_then_recent_categorized() -> None:
    cats = [cat(1, CategoryType.ROUTINE, label="Belanja Harian")]
    txns = [
        txn(M(2026, 1, 5), debit="100000", category_id=1, category_source=CategorySource.PARSER),
        txn(M(2026, 3, 9), debit="250000", category_id=None, description="TOKO XYZ", id=77),
        txn(M(2026, 2, 2), debit="90000", category_id=1, category_source=CategorySource.MANUAL),
    ]
    view = build_belanja(txns, cats, [acct(1)])
    q = view.review_queue
    # the uncategorized row is first regardless of its date being between the others.
    assert q[0].transaction_id == 77
    assert q[0].category_id is None
    assert q[0].category_source is None
    assert q[0].description == "TOKO XYZ"
    assert q[0].debit == Decimal("250000")
    assert q[0].institution == "bca"
    assert q[0].account_number_masked == "****0001"
    # then the categorized rows, most-recent first (Feb before Jan).
    assert [i.transaction_id for i in q[1:]] == [txns[2].id, txns[0].id]
    assert q[1].category_source is CategorySource.MANUAL
    assert q[1].category_label == "Belanja Harian"


def test_review_queue_limit_keeps_all_uncategorized_and_caps_categorized() -> None:
    cats = [cat(1, CategoryType.ROUTINE)]
    uncategorized = [txn(M(2026, 1, d), debit="10000", category_id=None) for d in range(1, 6)]
    categorized = [
        txn(M(2026, 2, d), debit="10000", category_id=1, category_source=CategorySource.PARSER)
        for d in range(1, 11)
    ]
    view = build_belanja(uncategorized + categorized, cats, [acct(1)], review_limit=8)
    # all 5 uncategorized are kept (they need action); categorized fills the remaining 3 slots.
    uncats = [i for i in view.review_queue if i.category_id is None]
    catd = [i for i in view.review_queue if i.category_id is not None]
    assert len(uncats) == 5
    assert len(catd) == 3
    assert len(view.review_queue) == 8


def test_belanja_anomalies_are_enriched_with_description_and_label() -> None:
    cats = [cat(1, CategoryType.ROUTINE, label="Transportasi")]
    txns = [txn(M(2026, m), debit="100000", category_id=1) for m in range(1, 5)]
    spike = txn(M(2026, 5), debit="500000", category_id=1, description="GRAB SURGE", id=99)
    txns.append(spike)
    view = build_belanja(txns, cats, [acct(1)])
    assert len(view.anomalies) == 1
    a = view.anomalies[0]
    assert a.transaction_id == 99
    assert a.description == "GRAB SURGE"
    assert a.category_label == "Transportasi"
    assert a.amount == Decimal("500000")
    assert a.reason  # non-empty human reason
    # the review row for the spike is flagged.
    spike_row = next(i for i in view.review_queue if i.transaction_id == 99)
    assert spike_row.is_anomaly


def test_build_belanja_cold_start_still_offers_categories_and_queue() -> None:
    cats = [cat(1, CategoryType.ROUTINE)]
    txns = [txn(M(2026, 1), debit="500000", category_id=None, description="a")]
    view = build_belanja(txns, cats, [acct(1)])
    assert view.estimate is None
    assert view.insufficient_data
    assert view.category_breakdown == []
    # you can still tag during cold start — the queue + picker are populated.
    assert len(view.review_queue) == 1
    assert {c.id for c in view.categories} == {1}


def test_build_belanja_empty_household() -> None:
    view = build_belanja([], [], [])
    assert view.estimate is None
    assert view.insufficient_data
    assert view.monthly_series == []
    assert view.review_queue == []
    assert view.categories == []
    assert view.anomalies == []


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

    def set_category(
        self,
        transaction_id: int,
        *,
        category_id: int,
        source: CategorySource,
        edited_by: int | None,
        edited_at: datetime.datetime,
    ) -> None:
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


def test_compute_belanja_aggregates_across_household_accounts() -> None:
    accounts = _FakeAccountRepo([acct(1), acct(2, AccountType.BCA_CREDIT_CARD)])
    cats = _FakeCategoryRepo([cat(1, CategoryType.ROUTINE)])
    txns = _FakeTransactionRepo(
        [
            txn(M(2026, 1), debit="300000", category_id=1, account_id=1),
            txn(M(2026, 2), debit="300000", category_id=1, account_id=1),
            txn(M(2026, 3), debit="200000", category_id=1, account_id=2),  # card spend
            txn(M(2026, 3), debit="70000", category_id=None, account_id=2),  # to review
        ]
    )
    view = compute_belanja(
        household_id=HOUSEHOLD, accounts=accounts, transactions=txns, categories=cats
    )
    assert isinstance(view, BelanjaView)
    assert view.months_observed == 3
    # the uncategorized card row surfaces in the queue with its account context.
    pending = [i for i in view.review_queue if i.category_id is None]
    assert len(pending) == 1
    assert pending[0].account_id == 2
