"""Fixture-based tests for the Ajaib portfolio-snapshot parser (SPEC §3.2, §6).

Anonymized fixture — identity fields stripped, all tickers/amounts/holding values
real so the structural check (Σ market_value == printed Total) is genuine. A
portfolio snapshot has no balance-continuity gate; lot continuity is soft (§3.2).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from coffer.parsers import ajaib_portfolio as ajaib
from coffer.parsers.statement_types import (
    BalanceReconciliationError,
    ParsedPortfolio,
    StatementParseError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ajaib_portfolio_2026-06-30.txt"


@pytest.fixture()
def pf() -> ParsedPortfolio:
    return ajaib.parse_text(FIXTURE.read_text())


def test_header(pf: ParsedPortfolio) -> None:
    assert pf.institution == "ajaib"
    assert pf.account_type == "ajaib_portfolio"
    assert pf.account_number_masked == "XXXXXX"  # Client Code
    assert pf.currency == "IDR"
    assert pf.as_of == date(2026, 6, 30)
    assert pf.cash_balance == Decimal("5099584.00")  # Saldo RDN


def test_holding_count(pf: ParsedPortfolio) -> None:
    assert len(pf.holdings) == 12


def test_first_holding_fields(pf: ParsedPortfolio) -> None:
    amrt = pf.holdings[0]
    assert amrt.ticker == "AMRT"
    assert amrt.name == "SUMBER ALFARIA TRIJAYA Tbk"
    assert amrt.lot_balance == Decimal("14.00")
    assert amrt.share_balance == Decimal("1400")
    assert amrt.avg_price == Decimal("1446")
    assert amrt.market_price == Decimal("1370")
    assert amrt.market_value == Decimal("1918000")
    assert amrt.unrealized == Decimal("-107000")
    assert amrt.special_notation is None


def test_wrapped_name_is_joined(pf: ParsedPortfolio) -> None:
    bbri = next(h for h in pf.holdings if h.ticker == "BBRI")
    assert bbri.name == "BANK RAKYAT INDONESIA (PERSERO) Tbk"


def test_odd_lot_holding(pf: ParsedPortfolio) -> None:
    kkgi = next(h for h in pf.holdings if h.ticker == "KKGI")
    assert kkgi.lot_balance == Decimal("0.19")
    assert kkgi.share_balance == Decimal("19")
    assert kkgi.market_value == Decimal("4750")


def test_market_value_reconciles_to_printed_total(pf: ParsedPortfolio) -> None:
    # market value sums exactly to the printed Total (the net-worth-critical figure)
    assert pf.total_market_value() == Decimal("29256150")


def test_broker_rounds_unrealized_total(pf: ParsedPortfolio) -> None:
    # the broker's printed Total unrealized (-5,514,447) is off-by-1 from the true
    # per-line sum (-5,514,448); the parser must NOT gate on it (only market value).
    assert sum(h.unrealized for h in pf.holdings) == Decimal("-5514448")


def test_tampered_market_value_raises() -> None:
    text = FIXTURE.read_text().replace("1,370 1,918,000 -107,000", "1,370 1,918,001 -107,000")
    with pytest.raises(BalanceReconciliationError):
        ajaib.parse_text(text)


def test_missing_total_raises() -> None:
    text = FIXTURE.read_text().replace("Total : 34,770,597 29,256,150 -5,514,447", "")
    with pytest.raises(StatementParseError):
        ajaib.parse_text(text)
