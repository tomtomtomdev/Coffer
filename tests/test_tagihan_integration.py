"""§3.4 — Tagihan (bill due-date) read path wired through the real SQL repos (Postgres).

The pure assembly is covered in ``test_tagihan.py`` with in-memory fakes; this proves
``DashboardReader.tagihan`` → ``compute_tagihan`` reads accounts/members/statements
through the actual ``coffer.persistence`` repos, that the due_date / minimum_payment /
balance survive the round trip, that only credit-card accounts contribute, and that the
bills come back soonest-first with the days-remaining countdown taken from the passed
``today``.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from coffer.api.dashboard import DashboardReader
from coffer.domain.entities import Account, Household, Member, Statement
from coffer.domain.enums import AccountType, UploadedVia
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlHouseholdRepo,
    SqlMemberRepo,
    SqlStatementRepo,
)

_TS = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=datetime.UTC)
TODAY = datetime.date(2026, 7, 19)


def _account(repo: SqlAccountRepo, member_id: int, account_type: AccountType, masked: str) -> int:
    acct = repo.add(
        Account(
            member_id=member_id,
            institution="x",
            account_type=account_type,
            account_number_masked=masked,
        )
    )
    assert acct.id is not None
    return acct.id


def _statement(
    repo: SqlStatementRepo,
    account_id: int,
    period_end: datetime.date,
    *,
    closing: Decimal,
    due_date: datetime.date | None = None,
    minimum: Decimal | None = None,
) -> None:
    tag = f"{account_id}-{period_end.isoformat()}"
    repo.add(
        Statement(
            account_id=account_id,
            period_start=period_end.replace(day=1),
            period_end=period_end,
            file_hash=f"file-{tag}".ljust(64, "0"),
            content_hash=f"content-{tag}".ljust(64, "0"),
            uploaded_via=UploadedVia.WEB,
            uploaded_at=_TS,
            parser_version="test@1",
            is_encrypted=True,
            closing_balance=closing,
            due_date=due_date,
            minimum_payment=minimum,
        )
    )


def test_tagihan_over_real_repos(session: Session) -> None:
    households = SqlHouseholdRepo(session)
    members = SqlMemberRepo(session)
    accounts = SqlAccountRepo(session)
    statements = SqlStatementRepo(session)

    hh = households.add(Household(name="Yohanes"))
    assert hh.id is not None
    tommy = members.add(Member(household_id=hh.id, name="Tommy"))
    priskila = members.add(Member(household_id=hh.id, name="Priskila"))
    assert tommy.id is not None and priskila.id is not None

    savings = _account(accounts, tommy.id, AccountType.BCA_SAVINGS, "****1000")
    bca_cc = _account(accounts, tommy.id, AccountType.BCA_CREDIT_CARD, "****2000")
    cimb_cc = _account(accounts, priskila.id, AccountType.CIMB_CREDIT_CARD, "****3000")

    # Savings has a balance but no bill → excluded.
    _statement(statements, savings, datetime.date(2026, 7, 5), closing=Decimal("611000000"))
    # BCA card: an older + a newer billed statement; the latest wins.
    _statement(
        statements,
        bca_cc,
        datetime.date(2026, 6, 5),
        closing=Decimal("1000000"),
        due_date=datetime.date(2026, 6, 28),
        minimum=Decimal("50000"),
    )
    _statement(
        statements,
        bca_cc,
        datetime.date(2026, 7, 5),
        closing=Decimal("2177067"),
        due_date=datetime.date(2026, 7, 28),
        minimum=Decimal("150000"),
    )
    # CIMB card: due sooner → sorts first.
    _statement(
        statements,
        cimb_cc,
        datetime.date(2026, 7, 3),
        closing=Decimal("838303.83"),
        due_date=datetime.date(2026, 7, 22),
        minimum=Decimal("50000.00"),
    )

    view = DashboardReader(session).tagihan(hh.id, today=TODAY)

    assert view.as_of == TODAY
    # Soonest-first: CIMB (22 Jul, 3d) before BCA (28 Jul, 9d); savings excluded.
    assert [b.account_id for b in view.bills] == [cimb_cc, bca_cc]

    cimb, bca = view.bills
    assert cimb.member_name == "Priskila"
    assert cimb.account_type is AccountType.CIMB_CREDIT_CARD
    assert cimb.due_date == datetime.date(2026, 7, 22)
    assert cimb.days_remaining == 3
    assert cimb.minimum_payment == Decimal("50000.00")
    assert cimb.statement_balance == Decimal("838303.83")

    # Latest billed statement wins for the BCA card (Jul, not Jun).
    assert bca.member_name == "Tommy"
    assert bca.due_date == datetime.date(2026, 7, 28)
    assert bca.days_remaining == 9
    assert bca.statement_balance == Decimal("2177067")
