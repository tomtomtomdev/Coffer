"""S13 — the Tag/Ubah write path (SPEC §3.3 runtime tagging).

``recategorize_transaction`` is the repo-driven use-case behind the dashboard's Tag/Ubah
action. It applies a manual tag (records an ``Override`` + stamps the transaction
``manual``), and — reusing the S6 pure functions — deactivates a learned rule that had
mis-fired ("refinement over fighting") and optionally generalizes the new tag into a
learned rule. Pure over in-memory fakes; no Postgres.
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from decimal import Decimal

import pytest

from coffer.domain.entities import Account, Category, LearnedRule, Member, Override, Transaction
from coffer.domain.enums import AccountType, CategorySource, CategoryType
from coffer.ingestion.categorize import RuleKey
from coffer.ingestion.recategorize import (
    CategoryNotFoundError,
    RecategorizeResult,
    TransactionNotFoundError,
    recategorize_transaction,
)

NOW = datetime.datetime(2026, 7, 15, 9, 0, tzinfo=datetime.UTC)
HOUSEHOLD = 1


def _txn(**kw: object) -> Transaction:
    base: dict[str, object] = dict(
        id=100,
        statement_id=1,
        account_id=10,
        date=datetime.date(2026, 6, 1),
        description="TOKO XYZ",
        dedup_key="k100",
        debit=Decimal("250000"),
        credit=Decimal("0"),
    )
    base.update(kw)
    return Transaction(**base)  # type: ignore[arg-type]


# ── in-memory fakes ────────────────────────────────────────────────────────────────--
class _Txns:
    def __init__(self, txn: Transaction | None) -> None:
        self._txn = txn
        self.set_calls: list[dict[str, object]] = []

    def get(self, transaction_id: int) -> Transaction | None:
        return self._txn if self._txn and self._txn.id == transaction_id else None

    def set_category(
        self,
        transaction_id: int,
        *,
        category_id: int,
        source: CategorySource,
        edited_by: int | None,
        edited_at: datetime.datetime,
    ) -> None:
        self.set_calls.append(
            {
                "transaction_id": transaction_id,
                "category_id": category_id,
                "source": source,
                "edited_by": edited_by,
                "edited_at": edited_at,
            }
        )

    def add(self, transaction: Transaction) -> Transaction:
        raise NotImplementedError

    def by_dedup_key(self, dedup_key: str) -> Transaction | None:
        raise NotImplementedError

    def list_by_account(self, account_id: int) -> list[Transaction]:
        raise NotImplementedError


class _Accounts:
    def get(self, account_id: int) -> Account | None:
        return Account(
            id=account_id,
            member_id=5,
            institution="bca",
            account_type=AccountType.BCA_SAVINGS,
            account_number_masked="****0010",
        )

    def add(self, account: Account) -> Account:
        raise NotImplementedError

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        raise NotImplementedError

    def list_by_household(self, household_id: int) -> list[Account]:
        raise NotImplementedError


class _Members:
    def get(self, member_id: int) -> Member | None:
        return Member(id=member_id, household_id=HOUSEHOLD, name="Tommy")

    def add(self, member: Member) -> Member:
        raise NotImplementedError

    def by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        raise NotImplementedError

    def list_by_household(self, household_id: int) -> list[Member]:
        raise NotImplementedError


class _Categories:
    def __init__(self, cats: list[Category]) -> None:
        self._cats = {c.id: c for c in cats if c.id is not None}

    def get(self, category_id: int) -> Category | None:
        return self._cats.get(category_id)

    def add(self, category: Category) -> Category:
        raise NotImplementedError

    def list_by_household(self, household_id: int) -> list[Category]:
        return list(self._cats.values())


class _Overrides:
    def __init__(self) -> None:
        self.added: list[Override] = []

    def add(self, override: Override) -> Override:
        stored = replace(override, id=len(self.added) + 1)
        self.added.append(stored)
        return stored

    def list_by_transaction(self, transaction_id: int) -> list[Override]:
        raise NotImplementedError


class _Rules:
    def __init__(self, rules: list[LearnedRule]) -> None:
        self._rules = {r.id: r for r in rules if r.id is not None}
        self.deactivated: list[int] = []
        self.added: list[LearnedRule] = []
        self._next = max(self._rules, default=0) + 100

    def list_active_by_household(self, household_id: int) -> list[LearnedRule]:
        return [r for r in self._rules.values() if r.household_id == household_id and r.active]

    def set_active(self, rule_id: int, *, active: bool) -> None:
        self.deactivated.append(rule_id)
        self._rules[rule_id] = replace(self._rules[rule_id], active=active)

    def add(self, rule: LearnedRule) -> LearnedRule:
        rid = self._next
        self._next += 1
        stored = replace(rule, id=rid)
        self._rules[rid] = stored
        self.added.append(stored)
        return stored

    def get(self, rule_id: int) -> LearnedRule | None:
        return self._rules.get(rule_id)

    def bump_hit_count(self, rule_id: int, *, by: int = 1) -> None:
        raise NotImplementedError


def _cat(id_: int, type_: CategoryType = CategoryType.ROUTINE) -> Category:
    return Category(id=id_, household_id=HOUSEHOLD, match_pattern="x", label=f"c{id_}", type=type_)


def _run(
    txns: _Txns,
    rules: _Rules,
    cats: _Categories,
    overrides: _Overrides,
    **kw: object,
) -> RecategorizeResult:
    return recategorize_transaction(
        now=NOW,
        transactions=txns,
        accounts=_Accounts(),
        members=_Members(),
        categories=cats,
        overrides=overrides,
        learned_rules=rules,
        **kw,  # type: ignore[arg-type]
    )


# ── tests ─────────────────────────────────────────────────────────────────────────---
def test_tagging_an_uncategorized_txn_records_override_and_sets_manual() -> None:
    txns = _Txns(_txn(category_id=None, category_source=None))
    overrides = _Overrides()
    rules = _Rules([])
    result = _run(
        txns,
        rules,
        _Categories([_cat(7)]),
        overrides,
        transaction_id=100,
        new_category_id=7,
        member_id=5,
    )
    assert result == RecategorizeResult(
        transaction_id=100, category_id=7, deactivated_rule_id=None, created_rule_id=None
    )
    assert len(overrides.added) == 1
    assert overrides.added[0].category_id == 7
    assert overrides.added[0].member_id == 5
    assert txns.set_calls == [
        {
            "transaction_id": 100,
            "category_id": 7,
            "source": CategorySource.MANUAL,
            "edited_by": 5,
            "edited_at": NOW,
        }
    ]
    assert rules.deactivated == []
    assert rules.added == []


def test_retagging_a_learned_rule_result_deactivates_that_rule() -> None:
    # A txn was auto-classified by a learned rule keyed on its counterparty acct; the user
    # re-tags it → that rule is deactivated (refinement over fighting, SPEC §3.3).
    rule = LearnedRule(
        id=3,
        household_id=HOUSEHOLD,
        category_id=7,
        created_at=NOW,
        match_counterparty_acct="9988",
    )
    txns = _Txns(
        _txn(category_id=7, category_source=CategorySource.LEARNED_RULE, counterparty_acct="9988")
    )
    rules = _Rules([rule])
    result = _run(
        txns,
        rules,
        _Categories([_cat(7), _cat(9)]),
        _Overrides(),
        transaction_id=100,
        new_category_id=9,
    )
    assert result.deactivated_rule_id == 3
    assert rules.deactivated == [3]
    deactivated = rules.get(3)
    assert deactivated is not None and deactivated.active is False


def test_generalize_on_counterparty_acct_creates_a_learned_rule() -> None:
    txns = _Txns(_txn(category_id=None, counterparty_acct="123456"))
    rules = _Rules([])
    result = _run(
        txns,
        rules,
        _Categories([_cat(7)]),
        _Overrides(),
        transaction_id=100,
        new_category_id=7,
        generalize=RuleKey.COUNTERPARTY_ACCT,
    )
    assert result.created_rule_id is not None
    assert len(rules.added) == 1
    created = rules.added[0]
    assert created.match_counterparty_acct == "123456"
    assert created.category_id == 7
    assert created.created_from_transaction_id == 100


def test_amount_only_generalize_requires_confirmation() -> None:
    txns = _Txns(_txn(category_id=None, counterparty_acct=None))
    with pytest.raises(ValueError, match="confirm"):
        _run(
            txns,
            _Rules([]),
            _Categories([_cat(7)]),
            _Overrides(),
            transaction_id=100,
            new_category_id=7,
            generalize=RuleKey.AMOUNT,
        )


def test_amount_only_generalize_with_confirmation_creates_rule() -> None:
    txns = _Txns(_txn(category_id=None, counterparty_acct=None, debit=Decimal("50000")))
    rules = _Rules([])
    result = _run(
        txns,
        rules,
        _Categories([_cat(7)]),
        _Overrides(),
        transaction_id=100,
        new_category_id=7,
        generalize=RuleKey.AMOUNT,
        confirm_amount_only=True,
        amount_tolerance=Decimal("1000"),
    )
    assert result.created_rule_id is not None
    created = rules.added[0]
    assert created.match_amount == Decimal("50000")
    assert created.match_amount_tolerance == Decimal("1000")
    assert created.match_counterparty_acct is None


def test_unknown_transaction_raises() -> None:
    with pytest.raises(TransactionNotFoundError):
        _run(
            _Txns(None),
            _Rules([]),
            _Categories([_cat(7)]),
            _Overrides(),
            transaction_id=100,
            new_category_id=7,
        )


def test_unknown_or_foreign_category_raises() -> None:
    txns = _Txns(_txn(category_id=None))
    with pytest.raises(CategoryNotFoundError):
        _run(
            txns,
            _Rules([]),
            _Categories([]),
            _Overrides(),
            transaction_id=100,
            new_category_id=999,
        )
