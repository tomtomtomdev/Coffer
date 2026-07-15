"""Spend + cash-flow read models — SPEC §3.3, §3.5.

These are **query-side use-cases**, not ingest pipeline stages: they derive the
dashboard's spend/flow figures from the persisted ``transaction`` + ``category``
rows on read (there is no materialized spend snapshot in §2, unlike
``networth_snapshot`` which recompute writes on ingest). They therefore live in the
domain layer as use-case logic — reading only domain entities through the domain
repository Protocols, so the dependency points inward (CLAUDE.md).

Two features:

**§3.3 Routine monthly-spend estimate.** The estimand is deliberately split (SPEC §3.3):
  * headline = **median of monthly *totals*** of routine spend over the last 3–6
    months — NOT the sum of per-category medians (categories rarely peak the same
    month, so summing per-category medians understates a typical total month);
  * ``annual``-cadence items have a monthly median of ~zero and would drop out, so
    they are annualized and amortized to a monthly-equivalent, added on top;
  * per-category medians drive the breakdown bars (they are *not* expected to sum to
    the headline);
  * an anomaly flag marks any transaction ``> 2 ×`` its category's trailing median —
    guarded by ``≥ 3`` monthly observations and a minimum-median floor so a sparse or
    tiny category can't make everything look anomalous or divide by zero;
  * ``< 3`` months of routine data → no estimate (cold start) rather than a
    misleading number.

**§3.5 Income / cash flow / savings rate.** Per calendar month (attributed by the
transaction ``date``, never the upload date): ``income`` = credits typed ``income``;
``spend`` = debits typed ``routine|discretionary|one_off``; ``cash_flow`` =
income − spend; ``savings_rate`` = (income − spend) / income (``None`` when income is
zero — the div-by-zero guard). ``transfer`` and ``investment_move`` are excluded from
both (intra-household transfers already net out via their ``transfer`` type, §3.3).

**What is *not* counted as spend.** Only the three spend types above. Uncategorized
debits (``category_id is None``) are pending a one-time review tag (§3.3) and are
therefore excluded rather than guessed into a number — as the review queue is worked
the figures firm up. This matches "always visible, always correctable".

Definitions (documented so the numbers are auditable):
  * A transaction's **month** is ``date(year, month, 1)``.
  * "Months of routine data" (cold-start basis + the median window) = the distinct
    months containing ``≥ 1`` routine transaction. A month with routine activity but
    no *non-annual* routine spend still counts as a ``0`` in the median list.
  * The routine window is the most recent ``≤ window_months`` (default 6) of those.
  * An ``annual`` item's amortized monthly-equivalent = the sum of that category's
    debits in the **latest month it appears**, divided by 12 (models one payment per
    year; a stale payment is still the best available estimate).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from coffer.domain.entities import Account, Category, Statement, Transaction
from coffer.domain.enums import AccountType, Cadence, CategorySource, CategoryType
from coffer.domain.networth import Bucket, bucket_of, compute_snapshot
from coffer.domain.repositories import (
    AccountRepo,
    CategoryRepo,
    HoldingRepo,
    MemberRepo,
    NetworthSnapshotRepo,
    StatementRepo,
    TransactionRepo,
)

# Portfolio account types (SPEC §3.2 — Ajaib + Stockbit merged by ticker).
_PORTFOLIO_TYPES = frozenset({AccountType.AJAIB_PORTFOLIO, AccountType.STOCKBIT_PORTFOLIO})

# ── tunables (documented constants, not magic numbers) ──────────────────────────────
WINDOW_MONTHS_DEFAULT = 6  # median-of-monthly-totals over the last 3–6 months (§3.3 step 3)
MIN_MONTHS_FOR_ESTIMATE = 3  # cold start below this (§3.3 step 6)
_MONTHS_PER_YEAR = Decimal("12")  # annual amortization divisor (§3.3 step 4)
ANOMALY_MULTIPLIER = Decimal("2")  # flag a txn above this × the category median (§3.3 step 5)
ANOMALY_MEDIAN_FLOOR = Decimal("50000")  # min median (IDR) before the multiplier test fires
ANOMALY_MIN_OBSERVATIONS = 3  # min monthly observations before the multiplier test fires

# Spend, for the cash-flow view (§3.5): real outflow, excluding transfers / funding.
_SPEND_TYPES = frozenset({CategoryType.ROUTINE, CategoryType.DISCRETIONARY, CategoryType.ONE_OFF})


# ── value objects ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CategoryMedian:
    """One category's row in the routine-spend breakdown (SPEC §3.3).

    For a monthly/irregular category ``median_monthly`` is the median of its monthly
    totals over its observation months; for an ``annual`` category it is the amortized
    monthly-equivalent. ``observation_count`` is the number of distinct months the
    category appears (drives the anomaly ``≥ 3`` guard).
    """

    category_id: int
    label: str
    median_monthly: Decimal
    observation_count: int
    cadence: Cadence


@dataclass(frozen=True)
class AnomalyFlag:
    """A transaction whose amount exceeds ``ANOMALY_MULTIPLIER`` × its category's
    trailing median — surfaced for review as "possibly non-routine" (SPEC §3.3 step 5)."""

    transaction_id: int
    category_id: int
    amount: Decimal
    category_median: Decimal
    reason: str = "possibly non-routine"


@dataclass(frozen=True)
class MonthlyRoutinePoint:
    """One bar of the routine-spend sparkline (SPEC §3.3 display): a window month and its
    total non-annual routine debits — the same per-month totals the headline median is
    taken over (annual items are amortized separately, not shown as a monthly bar)."""

    month: date
    total: Decimal


@dataclass(frozen=True)
class RoutineSpendEstimate:
    """The §3.3 routine-spend read model.

    ``estimate is None`` (with ``insufficient_data``) on cold start. Otherwise
    ``estimate == base_median_monthly + annual_amortized_monthly``. The breakdown is
    NOT expected to sum to the headline (see module docstring). ``monthly_series`` is the
    sparkline data — the window months' non-annual routine totals, in month order.
    """

    estimate: Decimal | None
    insufficient_data: bool
    months_observed: int
    window_months: int
    base_median_monthly: Decimal
    annual_amortized_monthly: Decimal
    category_breakdown: list[CategoryMedian]
    anomalies: list[AnomalyFlag]
    monthly_series: list[MonthlyRoutinePoint]


@dataclass(frozen=True)
class MonthlyCashFlow:
    """One month of the §3.5 cash-flow series. ``savings_rate is None`` when income is zero."""

    month: date
    income: Decimal
    spend: Decimal
    cash_flow: Decimal
    savings_rate: Decimal | None


@dataclass(frozen=True)
class CashFlowSummary:
    """The §3.5 income / cash-flow / savings-rate read model.

    ``headline_savings_rate`` is the aggregate ``(Σincome − Σspend) / Σincome`` over the
    trailing ``window_months`` months (``None`` when that window's income is zero).
    """

    months: list[MonthlyCashFlow]
    headline_savings_rate: Decimal | None
    window_months: int


# ── small pure helpers ───────────────────────────────────────────────────────────────
def _month_key(day: date) -> date:
    """The first of ``day``'s month — the canonical month bucket."""
    return date(day.year, day.month, 1)


def _median(values: Sequence[Decimal]) -> Decimal:
    """Exact ``Decimal`` median (average of the two middle values for an even count).

    Returns ``0`` for an empty sequence; callers only pass non-empty windows.
    """
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _pair_with_category(
    transactions: Sequence[Transaction], categories: Sequence[Category]
) -> list[tuple[Transaction, Category]]:
    """Resolve each transaction to its category, dropping uncategorized rows.

    Uncategorized transactions (``category_id is None``) and any dangling id are left
    out — they are not counted as spend/routine/income (see module docstring).
    """
    by_id: dict[int, Category] = {}
    for cat in categories:
        if cat.id is not None:
            by_id[cat.id] = cat
    paired: list[tuple[Transaction, Category]] = []
    for txn in transactions:
        if txn.category_id is None:
            continue
        resolved = by_id.get(txn.category_id)
        if resolved is not None:
            paired.append((txn, resolved))
    return paired


# ── §3.3 routine estimate (pure) ─────────────────────────────────────────────────────
def routine_spend_estimate(
    transactions: Sequence[Transaction],
    categories: Sequence[Category],
    *,
    window_months: int = WINDOW_MONTHS_DEFAULT,
) -> RoutineSpendEstimate:
    """Compute the SPEC §3.3 routine-spend estimate from already-fetched domain rows."""
    routine = [
        (t, c)
        for t, c in _pair_with_category(transactions, categories)
        if c.type is CategoryType.ROUTINE
    ]

    routine_months = sorted({_month_key(t.date) for t, _ in routine})
    months_observed = len(routine_months)
    if months_observed < MIN_MONTHS_FOR_ESTIMATE:
        return RoutineSpendEstimate(
            estimate=None,
            insufficient_data=True,
            months_observed=months_observed,
            window_months=window_months,
            base_median_monthly=Decimal("0"),
            annual_amortized_monthly=Decimal("0"),
            category_breakdown=[],
            anomalies=[],
            monthly_series=[],
        )

    window = routine_months[-window_months:]
    window_set = set(window)

    # Headline base: median over window months of Σ non-annual routine debits.
    non_annual_month_total: dict[date, Decimal] = {m: Decimal("0") for m in window}
    for txn, cat in routine:
        if cat.cadence is Cadence.ANNUAL:
            continue
        month = _month_key(txn.date)
        if month in window_set:
            non_annual_month_total[month] += txn.debit
    base_median = _median([non_annual_month_total[m] for m in window])

    breakdown: list[CategoryMedian] = []
    anomalies: list[AnomalyFlag] = []

    # Annual items: amortize the latest year's payment to a monthly-equivalent.
    annual_amortized = Decimal("0")
    annual_by_cat: dict[int, list[Transaction]] = defaultdict(list)
    for txn, cat in routine:
        if cat.cadence is Cadence.ANNUAL and cat.id is not None:
            annual_by_cat[cat.id].append(txn)
    label_of = {c.id: c.label for _, c in routine if c.id is not None}
    for cat_id, items in annual_by_cat.items():
        latest_month = max(_month_key(t.date) for t in items)
        annual_amount = sum(
            (t.debit for t in items if _month_key(t.date) == latest_month), Decimal("0")
        )
        monthly_equiv = annual_amount / _MONTHS_PER_YEAR
        annual_amortized += monthly_equiv
        observations = len({_month_key(t.date) for t in items})
        breakdown.append(
            CategoryMedian(cat_id, label_of[cat_id], monthly_equiv, observations, Cadence.ANNUAL)
        )

    # Non-annual per-category medians (breakdown) + anomaly flags, over the window.
    non_annual_by_cat: dict[int, list[Transaction]] = defaultdict(list)
    cadence_of: dict[int, Cadence] = {}
    for txn, cat in routine:
        if cat.cadence is Cadence.ANNUAL or cat.id is None:
            continue
        if _month_key(txn.date) in window_set:
            non_annual_by_cat[cat.id].append(txn)
            cadence_of[cat.id] = cat.cadence
    for cat_id, items in non_annual_by_cat.items():
        per_month: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
        for txn in items:
            per_month[_month_key(txn.date)] += txn.debit
        totals = list(per_month.values())
        observations = len(totals)
        median = _median(totals)
        breakdown.append(
            CategoryMedian(cat_id, label_of[cat_id], median, observations, cadence_of[cat_id])
        )
        if observations >= ANOMALY_MIN_OBSERVATIONS and median >= ANOMALY_MEDIAN_FLOOR:
            threshold = ANOMALY_MULTIPLIER * median
            for txn in items:
                if txn.debit > threshold and txn.id is not None:
                    anomalies.append(AnomalyFlag(txn.id, cat_id, txn.debit, median))

    breakdown.sort(key=lambda cm: (-cm.median_monthly, cm.category_id))
    anomalies.sort(key=lambda a: (-a.amount, a.transaction_id))

    return RoutineSpendEstimate(
        estimate=base_median + annual_amortized,
        insufficient_data=False,
        months_observed=months_observed,
        window_months=window_months,
        base_median_monthly=base_median,
        annual_amortized_monthly=annual_amortized,
        category_breakdown=breakdown,
        anomalies=anomalies,
        monthly_series=[MonthlyRoutinePoint(m, non_annual_month_total[m]) for m in window],
    )


# ── §3.3 Belanja (spend screen) assembled read model ─────────────────────────────────
REVIEW_LIMIT_DEFAULT = 40  # queue page size; all uncategorized are always kept (see below)


@dataclass(frozen=True)
class SpendAnomaly:
    """An anomaly row for the Belanja screen — an ``AnomalyFlag`` enriched with the
    transaction's description and its category label (so the UI needn't re-join)."""

    transaction_id: int
    category_id: int
    category_label: str
    description: str
    amount: Decimal
    category_median: Decimal
    reason: str


@dataclass(frozen=True)
class ReviewItem:
    """One row of the categorization review queue (SPEC §3.3 "always visible, always
    correctable"). ``category_source is None`` ⇒ uncategorized (needs a first tag);
    otherwise the source drives the badge and the row offers a re-tag. ``debit``/``credit``
    are both carried (money as Decimal); the UI shows the non-zero side."""

    transaction_id: int
    date: date
    description: str
    debit: Decimal
    credit: Decimal
    counterparty_name: str | None
    counterparty_acct: str | None
    account_id: int
    institution: str
    account_number_masked: str
    category_id: int | None
    category_label: str | None
    category_source: CategorySource | None
    is_anomaly: bool


@dataclass(frozen=True)
class CategoryOption:
    """A household category offered in the Tag/Ubah picker."""

    id: int
    label: str
    type: CategoryType
    cadence: Cadence


@dataclass(frozen=True)
class BelanjaView:
    """The assembled §3.3 spend screen: the routine-spend estimate (headline + base
    median + amortized annual + sparkline + per-category breakdown), enriched anomalies,
    the review queue, and the full category list for the re-tag picker."""

    estimate: Decimal | None
    insufficient_data: bool
    months_observed: int
    window_months: int
    base_median_monthly: Decimal
    annual_amortized_monthly: Decimal
    monthly_series: list[MonthlyRoutinePoint]
    category_breakdown: list[CategoryMedian]
    anomalies: list[SpendAnomaly]
    review_queue: list[ReviewItem]
    categories: list[CategoryOption]


def build_belanja(
    transactions: Sequence[Transaction],
    categories: Sequence[Category],
    accounts: Sequence[Account],
    *,
    window_months: int = WINDOW_MONTHS_DEFAULT,
    review_limit: int = REVIEW_LIMIT_DEFAULT,
) -> BelanjaView:
    """Assemble the SPEC §3.3 Belanja view from already-fetched domain rows (pure).

    The review queue floats **all** uncategorized rows to the top (they need a tag),
    then fills the remaining ``review_limit`` slots with the most-recent categorized rows
    (most recent first) so a wrong auto-assignment stays visible and correctable.
    """
    est = routine_spend_estimate(transactions, categories, window_months=window_months)
    label_of = {c.id: c.label for c in categories if c.id is not None}
    desc_of = {t.id: t.description for t in transactions if t.id is not None}
    anomaly_ids = {a.transaction_id for a in est.anomalies}

    anomalies = [
        SpendAnomaly(
            transaction_id=a.transaction_id,
            category_id=a.category_id,
            category_label=label_of.get(a.category_id, ""),
            description=desc_of.get(a.transaction_id, ""),
            amount=a.amount,
            category_median=a.category_median,
            reason=a.reason,
        )
        for a in est.anomalies
    ]

    acct_of = {a.id: a for a in accounts if a.id is not None}
    items = [
        ReviewItem(
            transaction_id=t.id,
            date=t.date,
            description=t.description,
            debit=t.debit,
            credit=t.credit,
            counterparty_name=t.counterparty_name,
            counterparty_acct=t.counterparty_acct,
            account_id=t.account_id,
            institution=(a.institution if a else ""),
            account_number_masked=(a.account_number_masked if a else ""),
            category_id=t.category_id,
            category_label=(label_of.get(t.category_id) if t.category_id is not None else None),
            category_source=t.category_source,
            is_anomaly=t.id in anomaly_ids,
        )
        for t in transactions
        if t.id is not None
        for a in [acct_of.get(t.account_id)]
    ]
    uncategorized = sorted(
        (i for i in items if i.category_id is None),
        key=lambda i: (i.date, i.transaction_id),
        reverse=True,
    )
    categorized = sorted(
        (i for i in items if i.category_id is not None),
        key=lambda i: (i.date, i.transaction_id),
        reverse=True,
    )
    remaining = max(0, review_limit - len(uncategorized))
    review_queue = uncategorized + categorized[:remaining]

    options = [
        CategoryOption(id=c.id, label=c.label, type=c.type, cadence=c.cadence)
        for c in categories
        if c.id is not None
    ]

    return BelanjaView(
        estimate=est.estimate,
        insufficient_data=est.insufficient_data,
        months_observed=est.months_observed,
        window_months=est.window_months,
        base_median_monthly=est.base_median_monthly,
        annual_amortized_monthly=est.annual_amortized_monthly,
        monthly_series=est.monthly_series,
        category_breakdown=est.category_breakdown,
        anomalies=anomalies,
        review_queue=review_queue,
        categories=options,
    )


def compute_belanja(
    *,
    household_id: int,
    accounts: AccountRepo,
    transactions: TransactionRepo,
    categories: CategoryRepo,
    window_months: int = WINDOW_MONTHS_DEFAULT,
    review_limit: int = REVIEW_LIMIT_DEFAULT,
) -> BelanjaView:
    """Repo-driven §3.3 Belanja view — fetches the household's accounts, transactions and
    categories once (mirrors ``compute_ringkasan``'s load)."""
    accts = accounts.list_by_household(household_id)
    txns: list[Transaction] = []
    for a in accts:
        if a.id is not None:
            txns.extend(transactions.list_by_account(a.id))
    return build_belanja(
        txns,
        categories.list_by_household(household_id),
        accts,
        window_months=window_months,
        review_limit=review_limit,
    )


# ── §3.5 income / cash flow / savings rate (pure) ────────────────────────────────────
def _savings_rate(income: Decimal, spend: Decimal) -> Decimal | None:
    """(income − spend) / income, or ``None`` when income is zero (div-by-zero guard)."""
    if income <= 0:
        return None
    return (income - spend) / income


def cash_flow_summary(
    transactions: Sequence[Transaction],
    categories: Sequence[Category],
    *,
    window_months: int = WINDOW_MONTHS_DEFAULT,
) -> CashFlowSummary:
    """Compute the SPEC §3.5 income / cash-flow / savings-rate series from domain rows."""
    income_by: defaultdict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    spend_by: defaultdict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    for txn, cat in _pair_with_category(transactions, categories):
        month = _month_key(txn.date)
        if cat.type is CategoryType.INCOME:
            income_by[month] += txn.credit
        elif cat.type in _SPEND_TYPES:
            spend_by[month] += txn.debit

    months = sorted(set(income_by) | set(spend_by))
    series = [
        MonthlyCashFlow(
            month=month,
            income=income_by[month],
            spend=spend_by[month],
            cash_flow=income_by[month] - spend_by[month],
            savings_rate=_savings_rate(income_by[month], spend_by[month]),
        )
        for month in months
    ]

    window = months[-window_months:]
    total_income = sum((income_by[m] for m in window), Decimal("0"))
    total_spend = sum((spend_by[m] for m in window), Decimal("0"))
    headline = _savings_rate(total_income, total_spend)

    return CashFlowSummary(
        months=series, headline_savings_rate=headline, window_months=window_months
    )


# ── repo-driven wrappers ─────────────────────────────────────────────────────────────
def _household_transactions(
    household_id: int, accounts: AccountRepo, transactions: TransactionRepo
) -> list[Transaction]:
    """All of a household's transactions, gathered per account (mirrors recompute's
    load: ``TransactionRepo`` exposes ``list_by_account``, not a household query)."""
    gathered: list[Transaction] = []
    for account in accounts.list_by_household(household_id):
        if account.id is None:
            continue
        gathered.extend(transactions.list_by_account(account.id))
    return gathered


def compute_routine_spend(
    *,
    household_id: int,
    accounts: AccountRepo,
    transactions: TransactionRepo,
    categories: CategoryRepo,
    window_months: int = WINDOW_MONTHS_DEFAULT,
) -> RoutineSpendEstimate:
    """Repo-driven §3.3 estimate — fetches the household's transactions + categories once."""
    return routine_spend_estimate(
        _household_transactions(household_id, accounts, transactions),
        categories.list_by_household(household_id),
        window_months=window_months,
    )


def compute_cash_flow(
    *,
    household_id: int,
    accounts: AccountRepo,
    transactions: TransactionRepo,
    categories: CategoryRepo,
    window_months: int = WINDOW_MONTHS_DEFAULT,
) -> CashFlowSummary:
    """Repo-driven §3.5 cash-flow summary — fetches the household's rows once."""
    return cash_flow_summary(
        _household_transactions(household_id, accounts, transactions),
        categories.list_by_household(household_id),
        window_months=window_months,
    )


# ── §3.1 Ringkasan (net-worth overview) read model ────────────────────────────────────
@dataclass(frozen=True)
class NetworthGridPoint:
    """One month-end grid point of the household net-worth series (SPEC §3.1)."""

    grid_date: date
    cash: Decimal
    portfolio: Decimal
    liability: Decimal
    net_worth: Decimal


@dataclass(frozen=True)
class MemberSeriesPoint:
    grid_date: date
    net_worth: Decimal


@dataclass(frozen=True)
class MemberNetworth:
    """A member's net-worth line for the "Per Anggota" toggle (computed on read)."""

    member_id: int
    member_name: str
    points: list[MemberSeriesPoint]


@dataclass(frozen=True)
class AccountBalance:
    """One Rincian Akun row: an account's latest reported balance + as-of date.

    ``balance`` is the account's own most recent non-null ``closing_balance`` (its raw
    magnitude — a credit card's is the positive Tagihan Baru); ``bucket`` tells the UI
    edge how to render it (a ``LIABILITY`` shows negative / rose). ``as_of`` is that
    statement's ``period_end`` — kept per-account so the mixed-as-of-date reality is
    honest (§3.1) rather than pretending one household date.
    """

    account_id: int
    member_id: int
    institution: str
    account_type: AccountType
    account_number_masked: str
    bucket: Bucket
    balance: Decimal
    as_of: date | None


@dataclass(frozen=True)
class NetworthDelta:
    """Change in household net worth vs. the previous grid point (the hero delta pill).

    ``pct`` is ``amount / |prior net worth|``; ``None`` when the prior month's net worth
    was zero (div-by-zero guard — cf. the savings-rate guard in §3.5).
    """

    amount: Decimal
    pct: Decimal | None


@dataclass(frozen=True)
class RingkasanKpis:
    """The overview KPI row (SPEC §3.1), lifted from the S8 read models.

    ``routine_spend_monthly`` / ``savings_rate`` / ``monthly_cash_flow`` are ``None`` when
    there is not enough data (cold start / zero income / no months) rather than a
    misleading zero.
    """

    routine_spend_monthly: Decimal | None
    routine_annual_amortized: Decimal
    savings_rate: Decimal | None
    monthly_cash_flow: Decimal | None


@dataclass(frozen=True)
class RingkasanView:
    """The assembled §3.1 Ringkasan payload for the dashboard's overview screen."""

    as_of: date | None
    net_worth: Decimal
    delta: NetworthDelta | None
    household_series: list[NetworthGridPoint]
    member_series: list[MemberNetworth]
    accounts: list[AccountBalance]
    kpis: RingkasanKpis


def _latest_balance(statements: Sequence[Statement]) -> tuple[Decimal, date | None]:
    """An account's most recent reported balance + that statement's ``period_end``.

    ``statements`` is ``period_end``-ascending; the latest statement carrying a non-null
    ``closing_balance`` wins (a ``None`` closing — e.g. an empty portfolio snapshot — is
    not a balance data point). No such statement → ``(0, None)`` (account absent).
    """
    balance = Decimal("0")
    as_of: date | None = None
    for stmt in statements:
        if stmt.closing_balance is not None:
            balance = stmt.closing_balance
            as_of = stmt.period_end
    return balance, as_of


def compute_ringkasan(
    *,
    household_id: int,
    accounts: AccountRepo,
    members: MemberRepo,
    statements: StatementRepo,
    transactions: TransactionRepo,
    categories: CategoryRepo,
    snapshots: NetworthSnapshotRepo,
    window_months: int = WINDOW_MONTHS_DEFAULT,
) -> RingkasanView:
    """Assemble the SPEC §3.1 Ringkasan overview from the persisted read side.

    The household series is read straight from the materialized ``networth_snapshot``
    (S7 — the dashboard loads fast); the per-member series is computed **on read** (it is
    not materialized) via the shared carry-forward engine over each member's accounts.
    Everything else (delta, Rincian Akun, KPI row) is derived from the same fetched rows.
    """
    snapshot_rows = snapshots.list_by_household(household_id)
    household_series = [
        NetworthGridPoint(
            grid_date=s.grid_date,
            cash=s.cash_total,
            portfolio=s.portfolio_total,
            liability=s.credit_liability_total,
            net_worth=s.net_worth,
        )
        for s in snapshot_rows
    ]
    as_of = household_series[-1].grid_date if household_series else None
    net_worth = household_series[-1].net_worth if household_series else Decimal("0")

    delta: NetworthDelta | None = None
    if len(household_series) >= 2:
        prior = household_series[-2].net_worth
        amount = household_series[-1].net_worth - prior
        delta = NetworthDelta(amount=amount, pct=(amount / abs(prior) if prior != 0 else None))

    accts = accounts.list_by_household(household_id)
    statements_by_account: dict[int, list[Statement]] = {
        a.id: statements.list_by_account(a.id) for a in accts if a.id is not None
    }

    # Per-member series, aligned to the household grid, via on-read carry-forward.
    grid_dates = [s.grid_date for s in snapshot_rows]
    member_series: list[MemberNetworth] = []
    for m in members.list_by_household(household_id):
        if m.id is None:
            continue
        member_accounts = [a for a in accts if a.member_id == m.id]
        points = [
            MemberSeriesPoint(
                grid_date=g,
                net_worth=compute_snapshot(
                    household_id=household_id,
                    grid_date=g,
                    accounts=member_accounts,
                    statements_by_account=statements_by_account,
                ).net_worth,
            )
            for g in grid_dates
        ]
        member_series.append(MemberNetworth(member_id=m.id, member_name=m.name, points=points))

    # Rincian Akun: each account's own latest reported balance + as-of + net-worth bucket.
    account_rows = [
        AccountBalance(
            account_id=a.id,
            member_id=a.member_id,
            institution=a.institution,
            account_type=a.account_type,
            account_number_masked=a.account_number_masked,
            bucket=bucket_of(a.account_type),
            balance=balance,
            as_of=acct_as_of,
        )
        for a in accts
        if a.id is not None
        for balance, acct_as_of in [_latest_balance(statements_by_account[a.id])]
    ]

    # KPI row — reuse the S8 read models over the household's rows, fetched once.
    household_txns: list[Transaction] = []
    for a in accts:
        if a.id is not None:
            household_txns.extend(transactions.list_by_account(a.id))
    cats = categories.list_by_household(household_id)
    routine = routine_spend_estimate(household_txns, cats, window_months=window_months)
    flow = cash_flow_summary(household_txns, cats, window_months=window_months)
    kpis = RingkasanKpis(
        routine_spend_monthly=routine.estimate,
        routine_annual_amortized=routine.annual_amortized_monthly,
        savings_rate=flow.headline_savings_rate,
        monthly_cash_flow=(flow.months[-1].cash_flow if flow.months else None),
    )

    return RingkasanView(
        as_of=as_of,
        net_worth=net_worth,
        delta=delta,
        household_series=household_series,
        member_series=member_series,
        accounts=account_rows,
        kpis=kpis,
    )


# ── §3.2 Portofolio consolidation read model ──────────────────────────────────────────
@dataclass(frozen=True)
class BrokerHolding:
    """One broker's line for a ticker — the per-broker breakdown (SPEC §3.2)."""

    institution: str
    account_id: int
    lots: Decimal
    avg_price: Decimal
    market_price: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    as_of: date


@dataclass(frozen=True)
class ConsolidatedHolding:
    """A ticker merged across brokers: combined lots, lots-weighted avg, MV, P/L."""

    ticker: str
    name: str
    lots: Decimal
    avg_price: Decimal  # lots-weighted across brokers
    market_value: Decimal
    unrealized_pl: Decimal
    cost_basis: Decimal  # market_value − unrealized_pl
    brokers: list[BrokerHolding]


@dataclass(frozen=True)
class PortfolioView:
    """The §3.2 consolidated-holdings payload.

    ``mixed_as_of`` is True when the brokers price as-of different dates — the combined
    P/L is then only loosely comparable (SPEC §3.2), so the UI shows the caveat banner and
    the per-broker figures rather than presenting a single false number.
    """

    total_market_value: Decimal
    total_unrealized_pl: Decimal
    total_cost_basis: Decimal
    holdings: list[ConsolidatedHolding]
    as_of_dates: list[date]
    mixed_as_of: bool


def portfolio_consolidation(
    *,
    household_id: int,
    accounts: AccountRepo,
    statements: StatementRepo,
    holdings: HoldingRepo,
) -> PortfolioView:
    """Merge the latest broker holdings by ticker into the §3.2 consolidated view.

    Each broker account contributes its **latest** statement's holdings (carry-forward);
    holdings are grouped by ticker with a lots-weighted average cost. Broker cash is not
    a holding, so it never appears here (it is net worth's concern, §3.1).
    """
    by_ticker: dict[str, list[BrokerHolding]] = defaultdict(list)
    name_of: dict[str, str] = {}
    as_of_set: set[date] = set()

    for account in accounts.list_by_household(household_id):
        if account.account_type not in _PORTFOLIO_TYPES or account.id is None:
            continue
        stmts = statements.list_by_account(account.id)  # period_end-ascending
        if not stmts:
            continue
        latest = stmts[-1]
        if latest.id is None:
            continue
        for h in holdings.list_by_statement(latest.id):
            by_ticker[h.ticker].append(
                BrokerHolding(
                    institution=account.institution,
                    account_id=account.id,
                    lots=h.lot_balance,
                    avg_price=h.avg_price,
                    market_price=h.market_price,
                    market_value=h.market_value,
                    unrealized_pl=h.unrealized_pl,
                    as_of=h.as_of_date,
                )
            )
            if h.name and h.ticker not in name_of:
                name_of[h.ticker] = h.name
            as_of_set.add(h.as_of_date)

    consolidated: list[ConsolidatedHolding] = []
    for ticker, brokers in by_ticker.items():
        lots = sum((b.lots for b in brokers), Decimal("0"))
        market_value = sum((b.market_value for b in brokers), Decimal("0"))
        unrealized_pl = sum((b.unrealized_pl for b in brokers), Decimal("0"))
        weighted = sum((b.avg_price * b.lots for b in brokers), Decimal("0"))
        avg_price = weighted / lots if lots != 0 else Decimal("0")
        consolidated.append(
            ConsolidatedHolding(
                ticker=ticker,
                name=name_of.get(ticker, ticker),
                lots=lots,
                avg_price=avg_price,
                market_value=market_value,
                unrealized_pl=unrealized_pl,
                cost_basis=market_value - unrealized_pl,
                brokers=sorted(brokers, key=lambda b: b.institution),
            )
        )
    consolidated.sort(key=lambda c: (-c.market_value, c.ticker))

    total_market_value = sum((c.market_value for c in consolidated), Decimal("0"))
    total_unrealized_pl = sum((c.unrealized_pl for c in consolidated), Decimal("0"))
    return PortfolioView(
        total_market_value=total_market_value,
        total_unrealized_pl=total_unrealized_pl,
        total_cost_basis=total_market_value - total_unrealized_pl,
        holdings=consolidated,
        as_of_dates=sorted(as_of_set),
        mixed_as_of=len(as_of_set) > 1,
    )
