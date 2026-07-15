"""S13 — Belanja read path + Tag/Ubah write path wired through the real SQL repos (Postgres).

Proves ``DashboardReader.belanja`` reads accounts / transactions / categories through the
actual ``coffer.persistence`` repos, and that ``TransactionCategorizer.recategorize``
persists a manual tag: an ``override`` row is written, the transaction is stamped
``manual`` with the edit audit, and a mis-fired learned rule is deactivated (SPEC §3.3).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from coffer.api.dashboard import DashboardReader
from coffer.api.transactions import TransactionCategorizer
from coffer.domain.entities import (
    Account,
    Category,
    Household,
    LearnedRule,
    Member,
    Statement,
    Transaction,
)
from coffer.domain.enums import (
    AccountType,
    Cadence,
    CategorySource,
    CategoryType,
    UploadedVia,
)
from coffer.ingestion.categorize import RuleKey
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlCategoryRepo,
    SqlHouseholdRepo,
    SqlLearnedRuleRepo,
    SqlMemberRepo,
    SqlOverrideRepo,
    SqlStatementRepo,
    SqlTransactionRepo,
)

_TS = datetime.datetime(2026, 7, 16, 12, 0, tzinfo=datetime.UTC)


def _seed_account(session: Session) -> tuple[int, int, int]:
    """A household with one member + one savings account + a statement. Returns
    (household_id, account_id, statement_id)."""
    hh = SqlHouseholdRepo(session).add(Household(name="Yohanes"))
    assert hh.id is not None
    member = SqlMemberRepo(session).add(Member(household_id=hh.id, name="Tommy"))
    assert member.id is not None
    account = SqlAccountRepo(session).add(
        Account(
            member_id=member.id,
            institution="bca",
            account_type=AccountType.BCA_SAVINGS,
            account_number_masked="****1234",
        )
    )
    assert account.id is not None
    stmt = SqlStatementRepo(session).add(
        Statement(
            account_id=account.id,
            period_start=datetime.date(2026, 6, 1),
            period_end=datetime.date(2026, 6, 30),
            file_hash="f".ljust(64, "0"),
            content_hash="c".ljust(64, "0"),
            uploaded_via=UploadedVia.WEB,
            uploaded_at=_TS,
            parser_version="test@1",
            is_encrypted=False,
        )
    )
    assert stmt.id is not None
    return hh.id, account.id, stmt.id


def _routine_cat(session: Session, household_id: int, label: str) -> int:
    cat = SqlCategoryRepo(session).add(
        Category(
            household_id=household_id,
            match_pattern="x",
            label=label,
            type=CategoryType.ROUTINE,
            cadence=Cadence.MONTHLY,
        )
    )
    assert cat.id is not None
    return cat.id


def _txn(
    session: Session,
    *,
    account_id: int,
    statement_id: int,
    day: tuple[int, int],
    debit: str,
    key: str,
    category_id: int | None = None,
    source: CategorySource | None = None,
    counterparty_acct: str | None = None,
) -> int:
    month, d = day
    txn = SqlTransactionRepo(session).add(
        Transaction(
            statement_id=statement_id,
            account_id=account_id,
            date=datetime.date(2026, month, d),
            description=f"TXN {key}",
            dedup_key=key,
            debit=Decimal(debit),
            category_id=category_id,
            category_source=source,
            counterparty_acct=counterparty_acct,
        )
    )
    assert txn.id is not None
    return txn.id


def test_belanja_over_real_repos(session: Session) -> None:
    hh_id, account_id, stmt_id = _seed_account(session)
    groceries = _routine_cat(session, hh_id, "Belanja Harian")

    # three months of routine data (clears the cold-start guard) + one to review.
    for i, month in enumerate((4, 5, 6)):
        _txn(
            session,
            account_id=account_id,
            statement_id=stmt_id,
            day=(month, 10),
            debit="500000",
            key=f"g{i}",
            category_id=groceries,
            source=CategorySource.PARSER,
        )
    _txn(
        session,
        account_id=account_id,
        statement_id=stmt_id,
        day=(6, 20),
        debit="250000",
        key="pending",
        counterparty_acct="99887766",
    )

    view = DashboardReader(session).belanja(hh_id)

    assert view.months_observed == 3
    assert view.base_median_monthly == Decimal("500000")
    assert view.estimate == Decimal("500000")
    pending = [i for i in view.review_queue if i.category_id is None]
    assert len(pending) == 1
    assert pending[0].description == "TXN pending"
    assert pending[0].account_number_masked == "****1234"
    assert {c.id for c in view.categories} == {groceries}


def test_recategorize_persists_override_and_deactivates_rule(session: Session) -> None:
    hh_id, account_id, stmt_id = _seed_account(session)
    transport = _routine_cat(session, hh_id, "Transportasi")
    groceries = _routine_cat(session, hh_id, "Belanja Harian")

    # a learned rule keyed on a counterparty acct, and a txn it auto-classified as transport.
    rule = SqlLearnedRuleRepo(session).add(
        LearnedRule(
            household_id=hh_id,
            category_id=transport,
            created_at=_TS,
            match_counterparty_acct="55554444",
        )
    )
    assert rule.id is not None
    txn_id = _txn(
        session,
        account_id=account_id,
        statement_id=stmt_id,
        day=(6, 5),
        debit="120000",
        key="learned",
        category_id=transport,
        source=CategorySource.LEARNED_RULE,
        counterparty_acct="55554444",
    )

    # the user re-tags it to groceries → refinement over fighting.
    result = TransactionCategorizer(session, lambda: _TS).recategorize(
        transaction_id=txn_id,
        new_category_id=groceries,
        member_id=None,
        generalize=RuleKey.COUNTERPARTY_ACCT,
        confirm_amount_only=False,
        amount_tolerance=None,
    )

    assert result.deactivated_rule_id == rule.id
    assert result.created_rule_id is not None

    # transaction is now manual with the edit audit stamped.
    updated = SqlTransactionRepo(session).get(txn_id)
    assert updated is not None
    assert updated.category_id == groceries
    assert updated.category_source is CategorySource.MANUAL
    assert updated.edited_at == _TS

    # the override row is persisted.
    overrides = SqlOverrideRepo(session).list_by_transaction(txn_id)
    assert len(overrides) == 1
    assert overrides[0].category_id == groceries

    # the mis-fired rule is deactivated; a fresh rule was created for groceries.
    deactivated = SqlLearnedRuleRepo(session).get(rule.id)
    assert deactivated is not None and deactivated.active is False
    active = SqlLearnedRuleRepo(session).list_active_by_household(hh_id)
    assert [r.category_id for r in active] == [groceries]
    assert active[0].match_counterparty_acct == "55554444"
