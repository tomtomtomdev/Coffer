"""S7 — recompute wired through the real SQL repositories (Postgres).

The pure grid/carry-forward logic is covered in ``test_recompute.py`` with in-memory
fakes. This proves the engine reads accounts/statements and upserts snapshots through
the actual ``coffer.persistence`` repos — Decimal money survives the round trip and the
month-end grid aggregates a multi-account, async-period household correctly (SPEC §3.1).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from coffer.domain.entities import Account, Household, Member, Statement
from coffer.domain.enums import AccountType, UploadedVia
from coffer.ingestion.recompute import InProcessRecomputeLock, recompute_all
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlHouseholdRepo,
    SqlMemberRepo,
    SqlNetworthSnapshotRepo,
    SqlStatementRepo,
)

_TS = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=datetime.UTC)
MAY = datetime.date(2026, 5, 31)
JUN = datetime.date(2026, 6, 30)


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
    repo: SqlStatementRepo, account_id: int, period_end: datetime.date, closing: Decimal
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
        )
    )


def test_recompute_all_over_real_repos(session: Session) -> None:
    households = SqlHouseholdRepo(session)
    members = SqlMemberRepo(session)
    accounts = SqlAccountRepo(session)
    statements = SqlStatementRepo(session)
    snapshots = SqlNetworthSnapshotRepo(session)

    hh = households.add(Household(name="Yohanes"))
    assert hh.id is not None
    member = members.add(Member(household_id=hh.id, name="Tommy"))
    assert member.id is not None

    savings = _account(accounts, member.id, AccountType.BCA_SAVINGS, "****1000")
    card = _account(accounts, member.id, AccountType.CIMB_CREDIT_CARD, "****2000")
    broker = _account(accounts, member.id, AccountType.AJAIB_PORTFOLIO, "****3000")

    _statement(statements, savings, MAY, Decimal("10000000.00"))
    _statement(statements, savings, JUN, Decimal("11000000.00"))
    _statement(statements, card, datetime.date(2026, 6, 18), Decimal("2000000.00"))  # liability
    _statement(statements, broker, JUN, Decimal("8000000.00"))  # holdings market value only

    written = recompute_all(
        household_id=hh.id,
        accounts=accounts,
        statements=statements,
        snapshots=snapshots,
        lock=InProcessRecomputeLock(),
    )
    assert [s.grid_date for s in written] == [MAY, JUN]

    stored = {s.grid_date: s for s in snapshots.list_by_household(hh.id)}

    # May: only savings has a statement yet.
    assert stored[MAY].cash_total == Decimal("10000000.00")
    assert stored[MAY].credit_liability_total == Decimal("0")
    assert stored[MAY].portfolio_total == Decimal("0")
    assert stored[MAY].net_worth == Decimal("10000000.00")

    # June: the Jun-18 card carries forward to the Jun-end grid; net = cash + portfolio − liability.
    assert stored[JUN].cash_total == Decimal("11000000.00")
    assert stored[JUN].credit_liability_total == Decimal("2000000.00")
    assert stored[JUN].portfolio_total == Decimal("8000000.00")
    assert stored[JUN].net_worth == Decimal("17000000.00")

    # Re-running is idempotent: still one snapshot per grid, values unchanged (§3.1).
    recompute_all(
        household_id=hh.id,
        accounts=accounts,
        statements=statements,
        snapshots=snapshots,
        lock=InProcessRecomputeLock(),
    )
    reloaded = snapshots.list_by_household(hh.id)
    assert [s.grid_date for s in reloaded] == [MAY, JUN]
    assert reloaded[1].net_worth == Decimal("17000000.00")
