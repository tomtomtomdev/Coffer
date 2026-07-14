"""S6 — categorization + learned-rule engine (SPEC §3.3).

Two responsibilities, both pure and testable without a DB:

  * ``classify`` — ingest-time categorization with the SPEC §3.3 precedence
    (parser/structural → learned_rule → regex ``category.match_pattern`` →
    uncategorized). Intra-household transfers (counterparty resolves to another
    household account) are the structural top tier.
  * learned-rule creation (``build_learned_rule``) + refinement on re-tag
    (``retag``): a recipient-acct rule is safe, an amount-only rule needs explicit
    confirmation, and re-tagging a learned-rule result *refines* (deactivates) the
    rule rather than fighting it with a duplicate override.

The classifier operates on already-fetched domain value objects (lists), so tests
inject them directly; ``categorize`` is the thin repo-driven wrapper (in-memory
fakes satisfy the Protocols — no Postgres, mirroring the dedup tests).
"""

from __future__ import annotations

import datetime
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from coffer.domain.entities import Account, Category, LearnedRule
from coffer.domain.enums import AccountType, Cadence, CategorySource, CategoryType
from coffer.ingestion.categorize import (
    INTRA_HOUSEHOLD_TRANSFER_PATTERN,
    Categorization,
    RuleKey,
    build_learned_rule,
    categorize,
    classify,
    retag,
    seed_categories,
)
from coffer.parsers.statement_types import ParsedTransaction

NOW = datetime.datetime(2026, 7, 14, 9, 0)
DAY = datetime.date(2026, 7, 3)


def _txn(
    *,
    description: str = "some spend",
    debit: str = "0",
    credit: str = "0",
    counterparty_acct: str | None = None,
    counterparty_name: str | None = None,
) -> ParsedTransaction:
    return ParsedTransaction(
        date=DAY,
        posting_date=DAY,
        description=description,
        debit=Decimal(debit),
        credit=Decimal(credit),
        counterparty_acct=counterparty_acct,
        counterparty_name=counterparty_name,
    )


def _cat(
    id_: int,
    pattern: str,
    *,
    label: str = "L",
    type_: CategoryType = CategoryType.ROUTINE,
    cadence: Cadence = Cadence.MONTHLY,
) -> Category:
    return Category(
        household_id=1,
        match_pattern=pattern,
        label=label,
        type=type_,
        cadence=cadence,
        id=id_,
    )


def _account(number: str, *, id_: int = 10, member_id: int = 2) -> Account:
    return Account(
        member_id=member_id,
        institution="bca",
        account_type=AccountType.BCA_SAVINGS,
        account_number_masked=number,
        id=id_,
    )


# transfer category the intra-household detector resolves to (seeded in production).
INTRA_CAT = _cat(
    900,
    INTRA_HOUSEHOLD_TRANSFER_PATTERN,
    label="Transfer Antar-Anggota",
    type_=CategoryType.TRANSFER,
)


# ── regex tier (category.match_pattern) ──────────────────────────────────────--
def test_regex_category_match_is_stamped_parser() -> None:
    grab = _cat(1, r"GRAB", label="Transport")
    result = classify(
        _txn(description="GRAB *TRIP 12345", debit="25000"),
        household_accounts=[],
        categories=[grab],
        active_rules=[],
    )
    assert result.category_id == 1
    assert result.source is CategorySource.PARSER
    assert not result.uncategorized


def test_regex_is_case_insensitive_and_uses_search() -> None:
    result = classify(
        _txn(description="pembelian di indomaret", debit="50000"),
        household_accounts=[],
        categories=[_cat(2, r"INDOMARET", label="Groceries")],
        active_rules=[],
    )
    assert result.category_id == 2


def test_uncategorized_when_nothing_matches() -> None:
    result = classify(
        _txn(description="HADI NUR WAHID", debit="100000"),
        household_accounts=[],
        categories=[_cat(1, r"GRAB")],
        active_rules=[],
    )
    assert result.uncategorized
    assert result.category_id is None
    assert result.source is None


def test_sentinel_pattern_is_not_used_for_regex_matching() -> None:
    # The intra-household sentinel is an identity marker, not a regex — a description
    # that literally contained it must NOT match it as a category pattern.
    result = classify(
        _txn(description=f"noise {INTRA_HOUSEHOLD_TRANSFER_PATTERN} noise", debit="1"),
        household_accounts=[],
        categories=[INTRA_CAT],
        active_rules=[],
    )
    assert result.uncategorized


def test_kartu_kredit_pl_is_transfer_via_seed() -> None:
    cats = seed_categories(household_id=1)
    # give the seed rows ids as if persisted
    cats = [Category(**{**c.__dict__, "id": i + 1}) for i, c in enumerate(cats)]
    result = classify(
        _txn(description="KARTU KREDIT/PL 4211", debit="2177067"),
        household_accounts=[],
        categories=cats,
        active_rules=[],
    )
    assert result.category_id is not None
    matched = next(c for c in cats if c.id == result.category_id)
    assert matched.type is CategoryType.TRANSFER


# ── learned-rule tier ─────────────────────────────────────────────────────────
def test_learned_rule_by_counterparty_acct_auto_classifies() -> None:
    rule = LearnedRule(
        household_id=1,
        category_id=42,
        created_at=NOW,
        match_counterparty_acct="7788990011",
        id=5,
    )
    result = classify(
        _txn(description="TRSF E-BANKING", debit="500000", counterparty_acct="7788990011"),
        household_accounts=[],
        categories=[],
        active_rules=[rule],
    )
    assert result.category_id == 42
    assert result.source is CategorySource.LEARNED_RULE
    assert result.matched_rule_id == 5


def test_learned_rule_beats_regex_category() -> None:
    rule = LearnedRule(
        household_id=1, category_id=42, created_at=NOW, match_counterparty_acct="X1", id=5
    )
    regex = _cat(1, r"TRSF", label="catch-all")
    result = classify(
        _txn(description="TRSF to X1", debit="500000", counterparty_acct="X1"),
        household_accounts=[],
        categories=[regex],
        active_rules=[rule],
    )
    assert result.source is CategorySource.LEARNED_RULE
    assert result.category_id == 42


def test_amount_only_rule_matches_within_tolerance() -> None:
    rule = LearnedRule(
        household_id=1,
        category_id=7,
        created_at=NOW,
        match_amount=Decimal("150000"),
        match_amount_tolerance=Decimal("1000"),
        id=9,
    )
    within = classify(
        _txn(description="whatever", debit="150500"),
        household_accounts=[],
        categories=[],
        active_rules=[rule],
    )
    assert within.category_id == 7
    outside = classify(
        _txn(description="whatever", debit="160000"),
        household_accounts=[],
        categories=[],
        active_rules=[rule],
    )
    assert outside.uncategorized


def test_acct_rule_beats_amount_only_rule() -> None:
    acct_rule = LearnedRule(
        household_id=1, category_id=1, created_at=NOW, match_counterparty_acct="A", id=1
    )
    amount_rule = LearnedRule(
        household_id=1, category_id=2, created_at=NOW, match_amount=Decimal("100"), id=2
    )
    result = classify(
        _txn(description="x", debit="100", counterparty_acct="A"),
        household_accounts=[],
        categories=[],
        active_rules=[amount_rule, acct_rule],  # order shouldn't matter
    )
    assert result.category_id == 1  # acct tier wins


# ── intra-household transfer (structural, top tier) ──────────────────────────--
def test_intra_household_transfer_detected() -> None:
    priskila_acct = _account("7788990011", member_id=2)
    result = classify(
        _txn(description="TRSF E-BANKING CR", credit="1000000", counterparty_acct="7788990011"),
        household_accounts=[priskila_acct],
        categories=[INTRA_CAT],
        active_rules=[],
    )
    assert result.category_id == INTRA_CAT.id
    assert result.source is CategorySource.PARSER


def test_intra_household_beats_learned_rule() -> None:
    # Even if a learned rule would match, a counterparty that resolves to a household
    # account is definitively a transfer (SPEC §3.3) and nets out.
    priskila_acct = _account("7788990011", member_id=2)
    rule = LearnedRule(
        household_id=1, category_id=42, created_at=NOW, match_counterparty_acct="7788990011", id=5
    )
    result = classify(
        _txn(description="TRSF", debit="1000000", counterparty_acct="7788990011"),
        household_accounts=[priskila_acct],
        categories=[INTRA_CAT],
        active_rules=[rule],
    )
    assert result.category_id == INTRA_CAT.id
    assert result.source is CategorySource.PARSER


def test_intra_household_missing_seed_category_raises() -> None:
    # If the counterparty resolves to a household account but the transfer category
    # was never seeded, that's a setup/programmer error — refuse to guess (mirrors
    # validate.py raising on an unknown account_type).
    priskila_acct = _account("7788990011")
    with pytest.raises(ValueError, match="intra-household"):
        classify(
            _txn(description="TRSF", debit="1", counterparty_acct="7788990011"),
            household_accounts=[priskila_acct],
            categories=[],
            active_rules=[],
        )


def test_non_member_counterparty_is_not_intra_household() -> None:
    priskila_acct = _account("7788990011")
    result = classify(
        _txn(description="TRSF HADI", debit="1", counterparty_acct="0001112223"),
        household_accounts=[priskila_acct],
        categories=[INTRA_CAT],
        active_rules=[],
    )
    assert result.uncategorized  # a stranger's acct — queue for a one-time learned tag


# ── categorize() repo wrapper (in-memory fakes satisfy the domain Protocols) ────
class _FakeAccountRepo:
    def __init__(self, accounts: list[Account]) -> None:
        self._accounts = accounts

    def list_by_household(self, household_id: int) -> list[Account]:
        return self._accounts

    # Rest of the AccountRepo Protocol — unused by categorize.
    def add(self, account: Account) -> Account:
        raise NotImplementedError

    def get(self, account_id: int) -> Account | None:
        raise NotImplementedError

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        raise NotImplementedError


class _FakeCategoryRepo:
    def __init__(self, categories: list[Category]) -> None:
        self._categories = categories

    def list_by_household(self, household_id: int) -> list[Category]:
        return self._categories

    # Rest of the CategoryRepo Protocol — unused by categorize.
    def add(self, category: Category) -> Category:
        raise NotImplementedError

    def get(self, category_id: int) -> Category | None:
        raise NotImplementedError


class _FakeLearnedRuleRepo:
    def __init__(self, rules: list[LearnedRule]) -> None:
        self._rules = rules

    def list_active_by_household(self, household_id: int) -> list[LearnedRule]:
        return [r for r in self._rules if r.active]

    # Rest of the LearnedRuleRepo Protocol — unused by categorize.
    def add(self, rule: LearnedRule) -> LearnedRule:
        raise NotImplementedError

    def get(self, rule_id: int) -> LearnedRule | None:
        raise NotImplementedError


def test_categorize_wrapper_fetches_from_repos() -> None:
    rule = LearnedRule(
        household_id=1, category_id=42, created_at=NOW, match_counterparty_acct="Z", id=5
    )
    result = categorize(
        _txn(description="x", debit="1", counterparty_acct="Z"),
        household_id=1,
        accounts=_FakeAccountRepo([]),
        categories=_FakeCategoryRepo([]),
        learned_rules=_FakeLearnedRuleRepo([rule]),
    )
    assert result.category_id == 42
    assert result.source is CategorySource.LEARNED_RULE


def test_categorize_wrapper_ignores_inactive_rules() -> None:
    rule = LearnedRule(
        household_id=1,
        category_id=42,
        created_at=NOW,
        match_counterparty_acct="Z",
        active=False,
        id=5,
    )
    result = categorize(
        _txn(description="x", debit="1", counterparty_acct="Z"),
        household_id=1,
        accounts=_FakeAccountRepo([]),
        categories=_FakeCategoryRepo([]),
        learned_rules=_FakeLearnedRuleRepo([rule]),
    )
    assert result.uncategorized


# ── learned-rule creation ─────────────────────────────────────────────────────
def test_build_rule_by_counterparty_acct_needs_no_confirmation() -> None:
    rule = build_learned_rule(
        household_id=1,
        category_id=42,
        key=RuleKey.COUNTERPARTY_ACCT,
        counterparty_acct="7788990011",
        amount=Decimal("500000"),
        now=NOW,
        created_from_transaction_id=99,
    )
    assert rule.match_counterparty_acct == "7788990011"
    assert rule.match_amount is None  # the strong key alone
    assert rule.active is True
    assert rule.created_from_transaction_id == 99
    assert rule.created_at == NOW


def test_build_rule_by_acct_requires_a_counterparty_acct() -> None:
    with pytest.raises(ValueError, match="counterparty_acct"):
        build_learned_rule(
            household_id=1,
            category_id=42,
            key=RuleKey.COUNTERPARTY_ACCT,
            counterparty_acct=None,
            amount=Decimal("1"),
            now=NOW,
        )


def test_amount_only_rule_requires_explicit_confirmation() -> None:
    # SPEC §3.3: an amount-only rule (no recipient acct) collides across unrelated
    # spend, so it must be explicitly confirmed at creation.
    with pytest.raises(ValueError, match="confirm"):
        build_learned_rule(
            household_id=1,
            category_id=42,
            key=RuleKey.AMOUNT,
            counterparty_acct=None,
            amount=Decimal("150000"),
            now=NOW,
        )


def test_amount_only_rule_built_when_confirmed() -> None:
    rule = build_learned_rule(
        household_id=1,
        category_id=42,
        key=RuleKey.AMOUNT,
        counterparty_acct=None,
        amount=Decimal("150000"),
        now=NOW,
        amount_tolerance=Decimal("500"),
        confirm_amount_only=True,
    )
    assert rule.match_counterparty_acct is None
    assert rule.match_amount == Decimal("150000")
    assert rule.match_amount_tolerance == Decimal("500")


# ── re-tag refinement (override, not fighting) ───────────────────────────────--
def test_retag_of_learned_result_deactivates_the_rule() -> None:
    prior = LearnedRule(
        household_id=1,
        category_id=42,
        created_at=NOW,
        match_counterparty_acct="Z",
        active=True,
        id=5,
    )
    result = retag(
        transaction_id=99,
        new_category_id=7,
        now=NOW,
        member_id=1,
        prior_source=CategorySource.LEARNED_RULE,
        prior_rule=prior,
    )
    assert result.override.transaction_id == 99
    assert result.override.category_id == 7
    assert result.override.member_id == 1
    assert result.deactivated_rule is not None
    assert result.deactivated_rule.id == 5
    assert result.deactivated_rule.active is False


def test_retag_of_parser_result_creates_override_only() -> None:
    result = retag(
        transaction_id=99,
        new_category_id=7,
        now=NOW,
        prior_source=CategorySource.PARSER,
    )
    assert result.override.category_id == 7
    assert result.deactivated_rule is None


def test_seed_categories_covers_transfer_and_intra_household() -> None:
    cats = seed_categories(household_id=1)
    patterns = {c.match_pattern for c in cats}
    assert INTRA_HOUSEHOLD_TRANSFER_PATTERN in patterns
    assert any(c.type is CategoryType.TRANSFER and "KARTU KREDIT" in c.match_pattern for c in cats)
    # a few of the Q4 routine seeds are present
    assert any(c.type is CategoryType.ROUTINE for c in cats)
    assert any(c.cadence is Cadence.ANNUAL for c in cats)  # STNK / insurance
    assert all(c.household_id == 1 for c in cats)


def test_categorization_is_a_frozen_value() -> None:
    c = Categorization(category_id=1, source=CategorySource.PARSER)
    with pytest.raises(FrozenInstanceError):
        c.category_id = 2  # type: ignore[misc]
