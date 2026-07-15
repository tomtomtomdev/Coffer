"""Runtime re-tagging use-case — the Tag/Ubah action behind the Belanja review queue
(SPEC §3.3 "runtime tagging + auto-generalization").

A repo-driven orchestration over the S6 pure functions (``retag`` / ``build_learned_rule``
/ ``match_learned_rule``), mirroring the ``pipeline`` / ``telegram`` use-case shape:
it reads and writes only through the domain repo Protocols, so it is testable with
in-memory fakes and the dependency points inward (ingestion → domain).

A manual tag always wins (SPEC §3.3): it records an ``Override`` (the audit trail) and
stamps the transaction ``manual`` with the edit audit. If the transaction had been
auto-classified by a learned rule, that rule is **deactivated** rather than repeatedly
overridden ("refinement over fighting"). Optionally the new tag is generalized into a
learned rule (recipient-acct key is safe; an amount-only rule needs explicit confirmation).

Re-tagging changes spend/flow figures (computed on read, §3.3/§3.5) but never net worth
(balance-based), so no snapshot recompute is triggered.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from coffer.domain.enums import CategorySource
from coffer.domain.repositories import (
    AccountRepo,
    CategoryRepo,
    LearnedRuleRepo,
    MemberRepo,
    OverrideRepo,
    TransactionRepo,
)
from coffer.ingestion.categorize import (
    RuleKey,
    build_learned_rule,
    match_learned_rule,
    retag,
)


class TransactionNotFoundError(Exception):
    """No transaction with the given id (→ HTTP 404 at the edge)."""


class CategoryNotFoundError(Exception):
    """No such category in this household (→ HTTP 404 at the edge)."""


@dataclass(frozen=True)
class RecategorizeResult:
    """The effect of a Tag/Ubah action: the transaction's new category, and the ids of any
    rule deactivated (refinement) or created (generalization)."""

    transaction_id: int
    category_id: int
    deactivated_rule_id: int | None
    created_rule_id: int | None


def recategorize_transaction(
    *,
    transaction_id: int,
    new_category_id: int,
    member_id: int | None = None,
    generalize: RuleKey | None = None,
    confirm_amount_only: bool = False,
    amount_tolerance: Decimal | None = None,
    now: datetime.datetime,
    transactions: TransactionRepo,
    accounts: AccountRepo,
    members: MemberRepo,
    categories: CategoryRepo,
    overrides: OverrideRepo,
    learned_rules: LearnedRuleRepo,
) -> RecategorizeResult:
    """Apply a manual re-tag to one transaction (SPEC §3.3)."""
    txn = transactions.get(transaction_id)
    if txn is None or txn.id is None:
        raise TransactionNotFoundError(f"transaction {transaction_id} not found")

    household_id = _resolve_household(txn.account_id, accounts, members)

    category = categories.get(new_category_id)
    if category is None or category.household_id != household_id:
        raise CategoryNotFoundError(
            f"category {new_category_id} not found in household {household_id}"
        )

    amount = txn.debit if txn.debit != 0 else txn.credit

    # If a learned rule assigned the current category, find it so retag can deactivate it.
    prior_rule = None
    if txn.category_source is CategorySource.LEARNED_RULE:
        prior_rule = match_learned_rule(
            counterparty_acct=txn.counterparty_acct,
            amount=amount,
            active_rules=learned_rules.list_active_by_household(household_id),
        )

    outcome = retag(
        transaction_id=txn.id,
        new_category_id=new_category_id,
        now=now,
        member_id=member_id,
        prior_source=txn.category_source,
        prior_rule=prior_rule,
    )

    overrides.add(outcome.override)
    transactions.set_category(
        txn.id,
        category_id=new_category_id,
        source=CategorySource.MANUAL,
        edited_by=member_id,
        edited_at=now,
    )

    deactivated_rule_id: int | None = None
    if outcome.deactivated_rule is not None and outcome.deactivated_rule.id is not None:
        deactivated_rule_id = outcome.deactivated_rule.id
        learned_rules.set_active(deactivated_rule_id, active=False)

    created_rule_id: int | None = None
    if generalize is not None:
        rule = build_learned_rule(
            household_id=household_id,
            category_id=new_category_id,
            key=generalize,
            counterparty_acct=txn.counterparty_acct,
            amount=amount,
            now=now,
            created_from_transaction_id=txn.id,
            amount_tolerance=amount_tolerance,
            confirm_amount_only=confirm_amount_only,
        )
        created_rule_id = learned_rules.add(rule).id

    return RecategorizeResult(
        transaction_id=txn.id,
        category_id=new_category_id,
        deactivated_rule_id=deactivated_rule_id,
        created_rule_id=created_rule_id,
    )


def _resolve_household(account_id: int, accounts: AccountRepo, members: MemberRepo) -> int:
    """A transaction's household via account → member (needed for rule scope + category
    validation). A persisted transaction always resolves; a dangling link is a data
    integrity error, not user input."""
    account = accounts.get(account_id)
    if account is None:
        raise ValueError(f"transaction references unknown account {account_id}")
    member = members.get(account.member_id)
    if member is None:
        raise ValueError(f"account {account_id} references unknown member {account.member_id}")
    return member.household_id
