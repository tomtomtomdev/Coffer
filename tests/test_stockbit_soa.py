"""Fixture-based tests for the Stockbit portfolio parser (SPEC §3.2, §6).

The statement has a cash SOA (dividends) followed by a PORTFOLIO STATEMENT holdings
table; this parser extracts the holdings + broker cash. Anonymized fixture; tickers
and amounts real so Σ market_value == printed Total is a genuine check.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from coffer.parsers import stockbit_soa as stockbit
from coffer.parsers.statement_types import (
    BalanceReconciliationError,
    ParsedPortfolio,
    StatementParseError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "stockbit_soa_2026-06.txt"


@pytest.fixture()
def pf() -> ParsedPortfolio:
    return stockbit.parse_text(FIXTURE.read_text())


def test_header(pf: ParsedPortfolio) -> None:
    assert pf.institution == "stockbit"
    assert pf.account_type == "stockbit_portfolio"
    assert pf.account_number_masked == "0000000"  # Client id
    assert pf.currency == "IDR"
    assert pf.as_of == date(2026, 6, 30)  # end of the SOA period
    assert pf.cash_balance == Decimal("100040.99")  # Cash Investor


def test_holding_count(pf: ParsedPortfolio) -> None:
    # 5 equities + the IDR cash pseudo-row the statement lists
    assert len(pf.holdings) == 6


def test_first_holding_fields(pf: ParsedPortfolio) -> None:
    bfin = next(h for h in pf.holdings if h.ticker == "BFIN")
    assert bfin.name == "BFI Finance Indonesia Tbk."
    assert bfin.share_balance == Decimal("300")
    assert bfin.lot_balance == Decimal("3")  # 300 shares / 100
    assert bfin.avg_price == Decimal("1103.75")
    assert bfin.market_price == Decimal("735")
    assert bfin.market_value == Decimal("220500")
    assert bfin.unrealized == Decimal("-110625")


def test_wrapped_name_is_joined(pf: ParsedPortfolio) -> None:
    sido = next(h for h in pf.holdings if h.ticker == "SIDO")
    assert sido.name == "Industri Jamu dan Farmasi Sido Muncul Tb"


def test_market_value_reconciles_to_printed_total(pf: ParsedPortfolio) -> None:
    assert pf.total_market_value() == Decimal("848601")


def test_tampered_market_value_raises() -> None:
    text = FIXTURE.read_text().replace("331,125 220,500 -110,625", "331,125 220,501 -110,625")
    with pytest.raises(BalanceReconciliationError):
        stockbit.parse_text(text)


def test_missing_portfolio_total_raises() -> None:
    text = FIXTURE.read_text().replace("T O T A L 1,442,125 848,601 -593,524", "")
    with pytest.raises(StatementParseError):
        stockbit.parse_text(text)
