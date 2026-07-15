"""S12 — Portofolio consolidation read model (SPEC §3.2).

Merges the latest ``holding`` rows from the household's broker accounts (Ajaib +
Stockbit) by ticker: combined lots, lots-weighted avg price, market value, unrealized
P/L, and a per-broker breakdown, plus household totals. The **mixed-as-of-date** guard
(SPEC §3.2): when brokers price as-of different dates the combined P/L is flagged rather
than presented as a single honest number.

Pure and repo-driven (mirrors S8/S11): in-memory fakes over the domain Protocols.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from coffer.domain.entities import Account, Holding, Statement
from coffer.domain.enums import AccountType, UploadedVia
from coffer.domain.read_models import PortfolioView, portfolio_consolidation

HOUSEHOLD = 1
JUN30 = datetime.date(2026, 6, 30)
JUN28 = datetime.date(2026, 6, 28)

AJAIB, STOCKBIT = 10, 11


def account(id_: int, institution: str, account_type: AccountType) -> Account:
    return Account(
        id=id_,
        member_id=1,
        institution=institution,
        account_type=account_type,
        account_number_masked=f"****{id_:04d}",
    )


_stmt_seq = 0


def statement(account_id: int, period_end: datetime.date) -> Statement:
    global _stmt_seq
    _stmt_seq += 1
    return Statement(
        id=_stmt_seq,
        account_id=account_id,
        period_start=period_end.replace(day=1),
        period_end=period_end,
        file_hash=f"f{_stmt_seq}",
        content_hash=f"c{_stmt_seq}",
        uploaded_via=UploadedVia.WEB,
        uploaded_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        parser_version="v1",
        is_encrypted=False,
        closing_balance=Decimal("0"),
    )


def holding(
    account_id: int,
    statement_id: int,
    ticker: str,
    *,
    lots: str,
    avg: str,
    price: str,
    mv: str,
    pl: str,
    as_of: datetime.date = JUN30,
    name: str = "",
) -> Holding:
    return Holding(
        account_id=account_id,
        statement_id=statement_id,
        ticker=ticker,
        name=name or f"{ticker} Tbk",
        lot_balance=Decimal(lots),
        avg_price=Decimal(avg),
        market_price=Decimal(price),
        market_value=Decimal(mv),
        unrealized_pl=Decimal(pl),
        as_of_date=as_of,
    )


class FakeAccountRepo:
    def __init__(self, accounts: list[Account]) -> None:
        self._accounts = accounts

    def list_by_household(self, household_id: int) -> list[Account]:
        return list(self._accounts)

    def add(self, account: Account) -> Account:
        raise NotImplementedError

    def get(self, account_id: int) -> Account | None:
        raise NotImplementedError

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        raise NotImplementedError


class FakeStatementRepo:
    def __init__(self, statements: list[Statement]) -> None:
        self._statements = statements

    def list_by_account(self, account_id: int) -> list[Statement]:
        return sorted(
            (s for s in self._statements if s.account_id == account_id),
            key=lambda s: s.period_end,
        )

    def add(self, statement: Statement) -> Statement:
        raise NotImplementedError

    def get(self, statement_id: int) -> Statement | None:
        raise NotImplementedError

    def by_file_hash(self, file_hash: str) -> Statement | None:
        raise NotImplementedError

    def by_content_hash(self, content_hash: str) -> Statement | None:
        raise NotImplementedError


class FakeHoldingRepo:
    def __init__(self, holdings: list[Holding]) -> None:
        self._holdings = holdings

    def list_by_statement(self, statement_id: int) -> list[Holding]:
        return [h for h in self._holdings if h.statement_id == statement_id]

    def add(self, holding: Holding) -> Holding:
        raise NotImplementedError


def _view(
    accounts: list[Account],
    statements: list[Statement],
    holdings: list[Holding],
) -> PortfolioView:
    return portfolio_consolidation(
        household_id=HOUSEHOLD,
        accounts=FakeAccountRepo(accounts),
        statements=FakeStatementRepo(statements),
        holdings=FakeHoldingRepo(holdings),
    )


def _two_broker_fixture() -> tuple[list[Account], list[Statement], list[Holding]]:
    accounts = [
        account(AJAIB, "ajaib", AccountType.AJAIB_PORTFOLIO),
        account(STOCKBIT, "stockbit", AccountType.STOCKBIT_PORTFOLIO),
        account(1, "bca", AccountType.BCA_SAVINGS),  # non-portfolio, must be ignored
    ]
    aj = statement(AJAIB, JUN30)
    sb = statement(STOCKBIT, JUN30)
    bank = statement(1, JUN30)
    assert aj.id and sb.id
    holdings = [
        holding(
            AJAIB, aj.id, "BBCA", lots="2", avg="9000", price="9500", mv="1900000", pl="100000"
        ),
        holding(AJAIB, aj.id, "ANTM", lots="5", avg="1500", price="1600", mv="800000", pl="50000"),
        holding(
            STOCKBIT, sb.id, "BBCA", lots="3", avg="9200", price="9500", mv="2850000", pl="90000"
        ),
    ]
    return accounts, [aj, sb, bank], holdings


def test_merges_by_ticker_with_weighted_avg() -> None:
    view = _view(*_two_broker_fixture())
    by_ticker = {h.ticker: h for h in view.holdings}
    assert set(by_ticker) == {"BBCA", "ANTM"}

    bbca = by_ticker["BBCA"]
    assert bbca.lots == Decimal("5")
    assert bbca.market_value == Decimal("4750000")
    assert bbca.unrealized_pl == Decimal("190000")
    assert bbca.cost_basis == Decimal("4560000")  # mv − pl
    # lots-weighted avg: (9000·2 + 9200·3) / 5
    assert bbca.avg_price == Decimal("9120")
    assert [b.institution for b in bbca.brokers] == ["ajaib", "stockbit"]


def test_household_totals_and_ordering() -> None:
    view = _view(*_two_broker_fixture())
    assert view.total_market_value == Decimal("5550000")
    assert view.total_unrealized_pl == Decimal("240000")
    assert view.total_cost_basis == Decimal("5310000")
    # Sorted by market value descending → BBCA before ANTM.
    assert [h.ticker for h in view.holdings] == ["BBCA", "ANTM"]


def test_same_as_of_is_not_mixed() -> None:
    view = _view(*_two_broker_fixture())
    assert view.mixed_as_of is False
    assert view.as_of_dates == [JUN30]


def test_mixed_as_of_dates_flagged() -> None:
    accounts = [
        account(AJAIB, "ajaib", AccountType.AJAIB_PORTFOLIO),
        account(STOCKBIT, "stockbit", AccountType.STOCKBIT_PORTFOLIO),
    ]
    aj = statement(AJAIB, JUN30)
    sb = statement(STOCKBIT, JUN28)
    assert aj.id and sb.id
    holdings = [
        holding(
            AJAIB, aj.id, "BBCA", lots="2", avg="9000", price="9500", mv="1900000", pl="100000"
        ),
        holding(
            STOCKBIT,
            sb.id,
            "BBCA",
            lots="3",
            avg="9200",
            price="9500",
            mv="2850000",
            pl="90000",
            as_of=JUN28,
        ),
    ]
    view = _view(accounts, [aj, sb], holdings)
    assert view.mixed_as_of is True
    assert view.as_of_dates == [JUN28, JUN30]


def test_only_latest_statement_per_account() -> None:
    ajaib = account(AJAIB, "ajaib", AccountType.AJAIB_PORTFOLIO)
    may = statement(AJAIB, datetime.date(2026, 5, 31))
    jun = statement(AJAIB, JUN30)
    assert may.id and jun.id
    holdings = [
        holding(AJAIB, may.id, "BBCA", lots="1", avg="8000", price="8000", mv="800000", pl="0"),
        holding(
            AJAIB, jun.id, "BBCA", lots="2", avg="9000", price="9500", mv="1900000", pl="100000"
        ),
    ]
    view = _view([ajaib], [may, jun], holdings)
    # Only June's holdings count (carry-forward = latest statement per account).
    assert len(view.holdings) == 1
    assert view.holdings[0].lots == Decimal("2")
    assert view.total_market_value == Decimal("1900000")


def test_empty_portfolio() -> None:
    view = _view([account(1, "bca", AccountType.BCA_SAVINGS)], [], [])
    assert view.holdings == []
    assert view.total_market_value == Decimal("0")
    assert view.total_unrealized_pl == Decimal("0")
    assert view.mixed_as_of is False
    assert view.as_of_dates == []
