"""S12 — Portofolio read path wired through the real SQL repositories (Postgres).

Proves ``DashboardReader.portofolio`` → ``portfolio_consolidation`` reads accounts /
statements / holdings through the actual ``coffer.persistence`` repos, merges a ticker
held at two brokers, and that Decimal money (incl. the lots-weighted average) survives
the round trip (SPEC §3.2).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from coffer.api.dashboard import DashboardReader
from coffer.domain.entities import Account, Holding, Household, Member, Statement
from coffer.domain.enums import AccountType, UploadedVia
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlHoldingRepo,
    SqlHouseholdRepo,
    SqlMemberRepo,
    SqlStatementRepo,
)

_TS = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=datetime.UTC)
JUN = datetime.date(2026, 6, 30)


def _statement(repo: SqlStatementRepo, account_id: int, closing: Decimal) -> int:
    tag = f"{account_id}-{JUN.isoformat()}"
    stmt = repo.add(
        Statement(
            account_id=account_id,
            period_start=JUN.replace(day=1),
            period_end=JUN,
            file_hash=f"file-{tag}".ljust(64, "0"),
            content_hash=f"content-{tag}".ljust(64, "0"),
            uploaded_via=UploadedVia.WEB,
            uploaded_at=_TS,
            parser_version="test@1",
            is_encrypted=False,
            closing_balance=closing,
        )
    )
    assert stmt.id is not None
    return stmt.id


def _holding(
    repo: SqlHoldingRepo,
    account_id: int,
    statement_id: int,
    *,
    lots: str,
    avg: str,
    price: str,
    mv: str,
    pl: str,
) -> None:
    repo.add(
        Holding(
            account_id=account_id,
            statement_id=statement_id,
            ticker="BBCA",
            name="Bank Central Asia Tbk",
            lot_balance=Decimal(lots),
            avg_price=Decimal(avg),
            market_price=Decimal(price),
            market_value=Decimal(mv),
            unrealized_pl=Decimal(pl),
            as_of_date=JUN,
        )
    )


def test_portofolio_over_real_repos(session: Session) -> None:
    households = SqlHouseholdRepo(session)
    members = SqlMemberRepo(session)
    accounts = SqlAccountRepo(session)
    statements = SqlStatementRepo(session)
    holdings = SqlHoldingRepo(session)

    hh = households.add(Household(name="Yohanes"))
    assert hh.id is not None
    member = members.add(Member(household_id=hh.id, name="Tommy"))
    assert member.id is not None

    ajaib = accounts.add(
        Account(
            member_id=member.id,
            institution="ajaib",
            account_type=AccountType.AJAIB_PORTFOLIO,
            account_number_masked="****4958",
        )
    )
    stockbit = accounts.add(
        Account(
            member_id=member.id,
            institution="stockbit",
            account_type=AccountType.STOCKBIT_PORTFOLIO,
            account_number_masked="****4996",
        )
    )
    assert ajaib.id is not None and stockbit.id is not None

    aj_stmt = _statement(statements, ajaib.id, Decimal("1900000"))
    sb_stmt = _statement(statements, stockbit.id, Decimal("2850000"))
    _holding(
        holdings, ajaib.id, aj_stmt, lots="2", avg="9000", price="9500", mv="1900000", pl="100000"
    )
    _holding(
        holdings, stockbit.id, sb_stmt, lots="3", avg="9200", price="9500", mv="2850000", pl="90000"
    )

    view = DashboardReader(session).portofolio(hh.id)

    assert view.total_market_value == Decimal("4750000")
    assert view.total_unrealized_pl == Decimal("190000")
    assert view.mixed_as_of is False

    assert len(view.holdings) == 1
    bbca = view.holdings[0]
    assert bbca.ticker == "BBCA"
    assert bbca.lots == Decimal("5")
    assert bbca.avg_price == Decimal("9120")  # (9000·2 + 9200·3) / 5
    assert bbca.market_value == Decimal("4750000")
    assert bbca.cost_basis == Decimal("4560000")
    assert [b.institution for b in bbca.brokers] == ["ajaib", "stockbit"]
