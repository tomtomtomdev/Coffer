"""S11 — Ringkasan read path wired through the real SQL repositories (Postgres).

The pure assembly is covered in ``test_ringkasan.py`` with in-memory fakes; this proves
``RingkasanReader`` → ``compute_ringkasan`` reads accounts/members/statements/snapshots
through the actual ``coffer.persistence`` repos, that Decimal money survives the round
trip, and that the household series (from the materialized snapshot) and the on-read
per-member series agree with the seeded balances (SPEC §3.1).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from coffer.api.dashboard import RingkasanReader
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


def test_ringkasan_over_real_repos(session: Session) -> None:
    households = SqlHouseholdRepo(session)
    members = SqlMemberRepo(session)
    accounts = SqlAccountRepo(session)
    statements = SqlStatementRepo(session)
    snapshots = SqlNetworthSnapshotRepo(session)

    hh = households.add(Household(name="Yohanes"))
    assert hh.id is not None
    tommy = members.add(Member(household_id=hh.id, name="Tommy"))
    priskila = members.add(Member(household_id=hh.id, name="Priskila"))
    assert tommy.id is not None and priskila.id is not None

    savings = _account(accounts, tommy.id, AccountType.BCA_SAVINGS, "****1000")
    card = _account(accounts, tommy.id, AccountType.CIMB_CREDIT_CARD, "****2000")
    broker = _account(accounts, priskila.id, AccountType.AJAIB_PORTFOLIO, "****3000")

    _statement(statements, savings, MAY, Decimal("600000000"))
    _statement(statements, savings, JUN, Decimal("611000000"))
    _statement(statements, card, MAY, Decimal("8000000"))
    _statement(statements, card, JUN, Decimal("8000000"))
    _statement(statements, broker, MAY, Decimal("300000000"))
    _statement(statements, broker, JUN, Decimal("340000000"))

    # Materialize the household net-worth grid (the read path reads it back).
    recompute_all(
        household_id=hh.id,
        accounts=accounts,
        statements=statements,
        snapshots=snapshots,
        lock=InProcessRecomputeLock(),
    )

    view = RingkasanReader(session).ringkasan(hh.id)

    # Headline + delta (JUN net 943M vs MAY net 892M).
    assert view.as_of == JUN
    assert view.net_worth == Decimal("943000000")
    assert view.delta is not None
    assert view.delta.amount == Decimal("51000000")

    # Household series straight from the materialized snapshot.
    assert [p.grid_date for p in view.household_series] == [MAY, JUN]
    jun = view.household_series[-1]
    assert (jun.cash, jun.portfolio, jun.liability, jun.net_worth) == (
        Decimal("611000000"),
        Decimal("340000000"),
        Decimal("8000000"),
        Decimal("943000000"),
    )

    # Per-member series computed on read (Tommy = savings − CC; Priskila = portfolio).
    by_name = {m.member_name: m for m in view.member_series}
    assert [(p.grid_date, p.net_worth) for p in by_name["Tommy"].points] == [
        (MAY, Decimal("592000000")),
        (JUN, Decimal("603000000")),
    ]
    assert [(p.grid_date, p.net_worth) for p in by_name["Priskila"].points] == [
        (MAY, Decimal("300000000")),
        (JUN, Decimal("340000000")),
    ]

    # Rincian Akun: latest balances, correct buckets, per-account as-of.
    by_bucket = {a.bucket.value: a for a in view.accounts}
    assert by_bucket["cash"].balance == Decimal("611000000")
    assert by_bucket["liability"].balance == Decimal("8000000")
    assert by_bucket["portfolio"].balance == Decimal("340000000")
    assert all(a.as_of == JUN for a in view.accounts)

    # No transactions/categories seeded → KPIs report cold-start rather than a fake zero.
    assert view.kpis.routine_spend_monthly is None
    assert view.kpis.savings_rate is None
    assert view.kpis.monthly_cash_flow is None
