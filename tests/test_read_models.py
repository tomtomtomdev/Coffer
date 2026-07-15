"""S8 — spend + cash-flow read models (SPEC §3.3, §3.5).

Pure query-side use-cases: given the household's persisted ``Transaction`` rows and
its ``Category`` set, derive the routine-spend estimate and the income/cash-flow /
savings-rate series. No Postgres — the repo-driven wrappers are exercised with
in-memory fakes over the domain Protocols (mirrors the dedup/recompute tests).

Pins the four PLAN.md cases plus the guards:
  * median-of-monthly-totals ≠ sum-of-per-category-medians (both correct, §3.3 step 3);
  * an ``annual``-cadence item is amortized on top of the median (§3.3 step 4);
  * a sparse category never divides by zero and is not anomaly-flagged (§3.3 step 5);
  * < 3 months of routine data → no estimate (cold start, §3.3 step 6);
  * income / cash flow / savings rate with the div-by-zero guard (§3.5);
  * transfers / investment_moves / income / uncategorized are excluded from spend.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from coffer.domain.entities import Account, Category, Transaction
from coffer.domain.enums import AccountType, Cadence, CategorySource, CategoryType
from coffer.domain.read_models import (
    ANOMALY_MEDIAN_FLOOR,
    CashFlowSummary,
    RoutineSpendEstimate,
    cash_flow_summary,
    compute_cash_flow,
    compute_routine_spend,
    routine_spend_estimate,
)

HOUSEHOLD = 1


def M(year: int, month: int, day: int = 15) -> datetime.date:
    return datetime.date(year, month, day)


# ── builders ─────────────────────────────────────────────────────────────────────
_txn_seq = 0


def txn(
    date: datetime.date,
    *,
    debit: str = "0",
    credit: str = "0",
    category_id: int | None = None,
    account_id: int = 1,
    id: int | None = None,
) -> Transaction:
    global _txn_seq
    _txn_seq += 1
    tid = id if id is not None else _txn_seq
    return Transaction(
        id=tid,
        statement_id=1,
        account_id=account_id,
        date=date,
        description="x",
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


# ── in-memory fakes over the domain Protocols ──────────────────────────────────────
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


class FakeCategoryRepo:
    def __init__(self, categories: list[Category]) -> None:
        self._categories = categories

    def list_by_household(self, household_id: int) -> list[Category]:
        return list(self._categories)

    def add(self, category: Category) -> Category:
        raise NotImplementedError

    def get(self, category_id: int) -> Category | None:
        raise NotImplementedError


def _acct(id_: int, account_type: AccountType = AccountType.BCA_SAVINGS) -> Account:
    return Account(
        id=id_,
        member_id=1,
        institution="bca",
        account_type=account_type,
        account_number_masked=f"acct{id_}",
    )


# ── §3.3 routine estimate ───────────────────────────────────────────────────────────
def test_median_of_totals_differs_from_sum_of_category_medians() -> None:
    # Two monthly routine categories that rarely peak in the same month (SPEC §3.3
    # step 3 note): the median of monthly *totals* is NOT the sum of per-category
    # medians, and both figures are individually correct.
    cats = [cat(1, CategoryType.ROUTINE), cat(2, CategoryType.ROUTINE)]
    txns = [
        txn(M(2026, 1), debit="300000", category_id=1),  # M1: A only
        txn(M(2026, 2), debit="300000", category_id=2),  # M2: B only
        txn(M(2026, 3), debit="300000", category_id=1),  # M3: A + B
        txn(M(2026, 3), debit="300000", category_id=2),
    ]
    est = routine_spend_estimate(txns, cats)
    # monthly totals: Jan 300k, Feb 300k, Mar 600k → median 300k.
    assert est.base_median_monthly == Decimal("300000")
    # per-category medians: A=300k, B=300k → sum 600k ≠ headline.
    by_cat = {cm.category_id: cm for cm in est.category_breakdown}
    assert by_cat[1].median_monthly == Decimal("300000")
    assert by_cat[2].median_monthly == Decimal("300000")
    assert sum((cm.median_monthly for cm in est.category_breakdown), Decimal("0")) == Decimal(
        "600000"
    )
    assert est.estimate == Decimal("300000")  # no annual add-on here
    assert not est.insufficient_data


def test_base_median_even_month_count_averages_two_middle_totals() -> None:
    cats = [cat(1, CategoryType.ROUTINE)]
    txns = [
        txn(M(2026, 1), debit="100000", category_id=1),
        txn(M(2026, 2), debit="200000", category_id=1),
        txn(M(2026, 3), debit="300000", category_id=1),
        txn(M(2026, 4), debit="400000", category_id=1),
    ]
    est = routine_spend_estimate(txns, cats)
    assert est.base_median_monthly == Decimal("250000")  # (200k + 300k) / 2


def test_annual_item_is_amortized_on_top_of_the_median() -> None:
    # STNK (annual) has a monthly median of zero and would drop out of the
    # median-of-monthly-totals; instead it is annualized and amortized (SPEC §3.3 step 4).
    cats = [
        cat(1, CategoryType.ROUTINE, label="Belanja Harian"),
        cat(2, CategoryType.ROUTINE, cadence=Cadence.ANNUAL, label="STNK"),
    ]
    txns = [txn(M(2026, m), debit="500000", category_id=1) for m in range(1, 7)]
    txns.append(txn(M(2026, 3), debit="1200000", category_id=2))  # one annual payment
    est = routine_spend_estimate(txns, cats)
    assert est.base_median_monthly == Decimal("500000")  # STNK excluded from the median
    assert est.annual_amortized_monthly == Decimal("100000")  # 1,200,000 / 12
    assert est.estimate == Decimal("600000")
    # the annual category still shows in the breakdown, at its monthly-equivalent.
    stnk = next(cm for cm in est.category_breakdown if cm.category_id == 2)
    assert stnk.cadence is Cadence.ANNUAL
    assert stnk.median_monthly == Decimal("100000")


def test_cold_start_under_three_months_gives_no_estimate() -> None:
    cats = [cat(1, CategoryType.ROUTINE)]
    txns = [
        txn(M(2026, 1), debit="500000", category_id=1),
        txn(M(2026, 2), debit="500000", category_id=1),
    ]
    est = routine_spend_estimate(txns, cats)
    assert est.estimate is None
    assert est.insufficient_data
    assert est.months_observed == 2
    assert est.category_breakdown == []
    assert est.anomalies == []


def test_uncategorized_and_non_routine_debits_are_excluded_from_the_estimate() -> None:
    cats = [
        cat(1, CategoryType.ROUTINE),
        cat(2, CategoryType.TRANSFER, cadence=Cadence.IRREGULAR),
        cat(3, CategoryType.DISCRETIONARY),
    ]
    txns = [
        txn(M(2026, 1), debit="500000", category_id=1),
        txn(M(2026, 2), debit="500000", category_id=1),
        txn(M(2026, 3), debit="500000", category_id=1),
        txn(M(2026, 3), debit="9000000", category_id=2),  # transfer — not routine
        txn(M(2026, 3), debit="7000000", category_id=3),  # discretionary — not routine
        txn(M(2026, 3), debit="8000000", category_id=None),  # uncategorized — not routine
    ]
    est = routine_spend_estimate(txns, cats)
    assert est.base_median_monthly == Decimal("500000")
    assert est.estimate == Decimal("500000")


# ── §3.3 step 5 anomaly flag + guards ───────────────────────────────────────────────
def test_anomaly_flags_transaction_over_twice_the_category_median() -> None:
    cats = [cat(1, CategoryType.ROUTINE)]
    txns = [txn(M(2026, m), debit="100000", category_id=1, id=m) for m in range(1, 5)]
    spike = txn(M(2026, 5), debit="300000", category_id=1, id=99)  # > 2 × 100k median
    txns.append(spike)
    est = routine_spend_estimate(txns, cats)
    assert len(est.anomalies) == 1
    flag = est.anomalies[0]
    assert flag.transaction_id == 99
    assert flag.category_id == 1
    assert flag.amount == Decimal("300000")
    assert flag.category_median == Decimal("100000")


def test_anomaly_guarded_by_minimum_median_floor() -> None:
    # Median below the floor → the multiplier test never fires (guards tiny medians).
    assert ANOMALY_MEDIAN_FLOOR == Decimal("50000")
    cats = [cat(1, CategoryType.ROUTINE)]
    txns = [txn(M(2026, m), debit="10000", category_id=1) for m in range(1, 4)]
    txns.append(txn(M(2026, 4), debit="100000", category_id=1))  # 10× median but median < floor
    est = routine_spend_estimate(txns, cats)
    assert est.anomalies == []


def test_anomaly_guarded_by_minimum_observations() -> None:
    # A category with < 3 monthly observations is not flagged even with a huge spike.
    cats = [cat(1, CategoryType.ROUTINE), cat(2, CategoryType.ROUTINE)]
    txns = [
        txn(M(2026, 1), debit="100000", category_id=1),  # cat1: only 2 months
        txn(M(2026, 2), debit="5000000", category_id=1),  # huge, but 2 obs → no flag
        txn(M(2026, 1), debit="100000", category_id=2),  # cat2 fills 3 routine months
        txn(M(2026, 2), debit="100000", category_id=2),
        txn(M(2026, 3), debit="100000", category_id=2),
    ]
    est = routine_spend_estimate(txns, cats)
    assert est.anomalies == []


def test_sparse_category_does_not_divide_by_zero() -> None:
    # A category seen once, in an otherwise 3-month dataset. No ZeroDivisionError, and
    # its single observation still yields a (non-anomalous) median.
    cats = [cat(1, CategoryType.ROUTINE), cat(2, CategoryType.ROUTINE)]
    txns = [
        txn(M(2026, 1), debit="500000", category_id=1),
        txn(M(2026, 2), debit="500000", category_id=1),
        txn(M(2026, 3), debit="500000", category_id=1),
        txn(M(2026, 3), debit="250000", category_id=2),  # sparse: one observation
    ]
    est = routine_spend_estimate(txns, cats)
    sparse = next(cm for cm in est.category_breakdown if cm.category_id == 2)
    assert sparse.observation_count == 1
    assert sparse.median_monthly == Decimal("250000")
    assert est.anomalies == []  # 1 obs < 3 → not eligible


# ── §3.5 income / cash flow / savings rate ──────────────────────────────────────────
def test_cash_flow_income_minus_spend_and_savings_rate() -> None:
    cats = [
        cat(1, CategoryType.INCOME),
        cat(2, CategoryType.ROUTINE),
        cat(3, CategoryType.DISCRETIONARY),
        cat(4, CategoryType.ONE_OFF),
        cat(5, CategoryType.TRANSFER, cadence=Cadence.IRREGULAR),
        cat(6, CategoryType.INVESTMENT_MOVE, cadence=Cadence.IRREGULAR),
    ]
    txns = [
        txn(M(2026, 3), credit="10000000", category_id=1),  # income
        txn(M(2026, 3), debit="3000000", category_id=2),  # routine spend
        txn(M(2026, 3), debit="1000000", category_id=3),  # discretionary spend
        txn(M(2026, 3), debit="500000", category_id=4),  # one_off spend
        txn(M(2026, 3), debit="2000000", category_id=5),  # transfer — excluded
        txn(M(2026, 3), debit="4000000", category_id=6),  # investment_move — excluded
        txn(M(2026, 3), debit="8000000", category_id=None),  # uncategorized — excluded
    ]
    summary = cash_flow_summary(txns, cats)
    assert len(summary.months) == 1
    mo = summary.months[0]
    assert mo.month == datetime.date(2026, 3, 1)
    assert mo.income == Decimal("10000000")
    assert mo.spend == Decimal("4500000")  # 3M + 1M + 0.5M only
    assert mo.cash_flow == Decimal("5500000")
    assert mo.savings_rate == Decimal("0.55")
    assert summary.headline_savings_rate == Decimal("0.55")


def test_savings_rate_guards_divide_by_zero_when_no_income() -> None:
    cats = [cat(1, CategoryType.ROUTINE)]
    txns = [txn(M(2026, 3), debit="2000000", category_id=1)]
    summary = cash_flow_summary(txns, cats)
    mo = summary.months[0]
    assert mo.income == Decimal("0")
    assert mo.spend == Decimal("2000000")
    assert mo.cash_flow == Decimal("-2000000")
    assert mo.savings_rate is None  # no divide-by-zero
    assert summary.headline_savings_rate is None


def test_cash_flow_attributes_by_transaction_date_and_sorts_months() -> None:
    cats = [cat(1, CategoryType.INCOME), cat(2, CategoryType.ROUTINE)]
    txns = [
        txn(M(2026, 2), credit="5000000", category_id=1),
        txn(M(2026, 1), debit="1000000", category_id=2),
        txn(M(2026, 2), debit="2000000", category_id=2),
    ]
    summary = cash_flow_summary(txns, cats)
    assert [mo.month for mo in summary.months] == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 2, 1),
    ]
    assert summary.months[0].income == Decimal("0")
    assert summary.months[0].spend == Decimal("1000000")
    assert summary.months[1].income == Decimal("5000000")
    assert summary.months[1].spend == Decimal("2000000")


# ── repo-driven wrappers ─────────────────────────────────────────────────────────────
def test_compute_routine_spend_aggregates_across_household_accounts() -> None:
    accounts = FakeAccountRepo([_acct(1), _acct(2, AccountType.BCA_CREDIT_CARD)])
    cats = FakeCategoryRepo([cat(1, CategoryType.ROUTINE)])
    txns = FakeTransactionRepo(
        [
            txn(M(2026, 1), debit="300000", category_id=1, account_id=1),
            txn(M(2026, 2), debit="300000", category_id=1, account_id=1),
            txn(M(2026, 3), debit="200000", category_id=1, account_id=2),  # card spend
        ]
    )
    est = compute_routine_spend(
        household_id=HOUSEHOLD, accounts=accounts, transactions=txns, categories=cats
    )
    assert isinstance(est, RoutineSpendEstimate)
    assert est.months_observed == 3
    assert est.base_median_monthly == Decimal("300000")


def test_compute_cash_flow_aggregates_across_household_accounts() -> None:
    accounts = FakeAccountRepo([_acct(1), _acct(2, AccountType.BCA_CREDIT_CARD)])
    cats = FakeCategoryRepo([cat(1, CategoryType.INCOME), cat(2, CategoryType.ROUTINE)])
    txns = FakeTransactionRepo(
        [
            txn(M(2026, 3), credit="10000000", category_id=1, account_id=1),
            txn(M(2026, 3), debit="2000000", category_id=2, account_id=2),
        ]
    )
    summary = compute_cash_flow(
        household_id=HOUSEHOLD, accounts=accounts, transactions=txns, categories=cats
    )
    assert isinstance(summary, CashFlowSummary)
    assert summary.months[0].income == Decimal("10000000")
    assert summary.months[0].spend == Decimal("2000000")


def test_empty_household_is_cold_start_and_flat_cash_flow() -> None:
    accounts = FakeAccountRepo([])
    cats = FakeCategoryRepo([])
    txns = FakeTransactionRepo([])
    est = compute_routine_spend(
        household_id=HOUSEHOLD, accounts=accounts, transactions=txns, categories=cats
    )
    summary = compute_cash_flow(
        household_id=HOUSEHOLD, accounts=accounts, transactions=txns, categories=cats
    )
    assert est.estimate is None
    assert est.insufficient_data
    assert summary.months == []
    assert summary.headline_savings_rate is None
