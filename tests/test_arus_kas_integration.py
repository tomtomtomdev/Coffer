"""S14 — Arus Kas read path wired through the real SQL repos (Postgres).

Proves ``DashboardReader.arus_kas`` reads accounts / transactions / categories through the
actual ``coffer.persistence`` repos and assembles the §3.5 cash-flow view: the monthly
income − spend series, the latest month's cash flow, and the income-source / spend-type
breakdown lists.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from coffer.api.dashboard import DashboardReader
from coffer.domain.entities import Account, Category, Household, Member, Statement, Transaction
from coffer.domain.enums import AccountType, Cadence, CategoryType, UploadedVia
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlCategoryRepo,
    SqlHouseholdRepo,
    SqlMemberRepo,
    SqlStatementRepo,
    SqlTransactionRepo,
)

_TS = datetime.datetime(2026, 7, 16, 12, 0, tzinfo=datetime.UTC)


def _seed_account(session: Session) -> tuple[int, int, int]:
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


def _cat(session: Session, household_id: int, label: str, type_: CategoryType) -> int:
    cat = SqlCategoryRepo(session).add(
        Category(
            household_id=household_id,
            match_pattern="x",
            label=label,
            type=type_,
            cadence=Cadence.IRREGULAR if type_ is CategoryType.INCOME else Cadence.MONTHLY,
        )
    )
    assert cat.id is not None
    return cat.id


def _txn(
    session: Session,
    *,
    account_id: int,
    statement_id: int,
    month: int,
    debit: str = "0",
    credit: str = "0",
    key: str,
    category_id: int,
) -> None:
    txn = SqlTransactionRepo(session).add(
        Transaction(
            statement_id=statement_id,
            account_id=account_id,
            date=datetime.date(2026, month, 10),
            description=f"TXN {key}",
            dedup_key=key,
            debit=Decimal(debit),
            credit=Decimal(credit),
            category_id=category_id,
        )
    )
    assert txn.id is not None


def test_arus_kas_over_real_repos(session: Session) -> None:
    hh_id, account_id, stmt_id = _seed_account(session)
    salary = _cat(session, hh_id, "Gaji", CategoryType.INCOME)
    groceries = _cat(session, hh_id, "Belanja Harian", CategoryType.ROUTINE)
    big = _cat(session, hh_id, "Beli Kulkas", CategoryType.ONE_OFF)

    # May: income + routine spend.
    _txn(
        session,
        account_id=account_id,
        statement_id=stmt_id,
        month=5,
        credit="8000000",
        key="i5",
        category_id=salary,
    )
    _txn(
        session,
        account_id=account_id,
        statement_id=stmt_id,
        month=5,
        debit="3000000",
        key="s5",
        category_id=groceries,
    )
    # June (latest): income + routine + a one-off.
    _txn(
        session,
        account_id=account_id,
        statement_id=stmt_id,
        month=6,
        credit="10000000",
        key="i6",
        category_id=salary,
    )
    _txn(
        session,
        account_id=account_id,
        statement_id=stmt_id,
        month=6,
        debit="3500000",
        key="s6",
        category_id=groceries,
    )
    _txn(
        session,
        account_id=account_id,
        statement_id=stmt_id,
        month=6,
        debit="2000000",
        key="o6",
        category_id=big,
    )

    view = DashboardReader(session).arus_kas(hh_id)

    assert [m.month for m in view.months] == [datetime.date(2026, 5, 1), datetime.date(2026, 6, 1)]
    assert view.latest_month == datetime.date(2026, 6, 1)
    assert view.months[-1].income == Decimal("10000000")
    assert view.months[-1].spend == Decimal("5500000")  # 3.5M routine + 2M one-off
    assert view.latest_cash_flow == Decimal("4500000")

    assert [(s.label, s.amount) for s in view.income_sources] == [("Gaji", Decimal("10000000"))]
    assert [(s.type, s.amount) for s in view.spend_by_type] == [
        (CategoryType.ROUTINE, Decimal("3500000")),
        (CategoryType.ONE_OFF, Decimal("2000000")),
    ]
