"""S3 — validation gate (SPEC §4 "Validation (before dedup)").

The stage generalizes the per-parser reconcile into ONE pipeline gate that returns
a routing decision instead of raising:

  OK                  — proceed to dedup/persist
  NEEDS_MANUAL_REVIEW — near-empty extraction (scanned PDF) → OCR / manual, no alert
  REJECTED            — schema mismatch or hard balance discontinuity → alert, no ingest

Cash/CC balance continuity is a hard gate; portfolio lot continuity is soft.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from coffer.ingestion.validate import (
    MIN_EXTRACTED_CHARS,
    ValidationOutcome,
    check_extraction,
    validate,
)
from coffer.parsers import ajaib_portfolio as ajaib
from coffer.parsers import cimb_kartu_kredit as cimb
from coffer.parsers.statement_types import (
    ParsedHolding,
    ParsedPortfolio,
    ParsedStatement,
    ParsedTransaction,
)

FIXTURES = Path(__file__).parent / "fixtures"

D0 = datetime.date(2026, 6, 1)
D1 = datetime.date(2026, 6, 30)


def _txn(debit: str = "0", credit: str = "0") -> ParsedTransaction:
    return ParsedTransaction(
        date=D0,
        posting_date=D0,
        description="X",
        debit=Decimal(debit),
        credit=Decimal(credit),
    )


def _savings(opening: str, closing: str, txns: list[ParsedTransaction]) -> ParsedStatement:
    return ParsedStatement(
        institution="bca",
        account_type="bca_savings",
        parser_version="test",
        account_number_masked="1234",
        currency="IDR",
        period_start=D0,
        period_end=D1,
        opening_balance=Decimal(opening),
        closing_balance=Decimal(closing),
        transactions=txns,
    )


def _credit_card(
    opening: str, closing: str, txns: list[ParsedTransaction], *, tagihan: str | None = None
) -> ParsedStatement:
    return ParsedStatement(
        institution="cimb",
        account_type="cimb_credit_card",
        parser_version="test",
        account_number_masked="5481",
        currency="IDR",
        period_start=D0,
        period_end=D1,
        opening_balance=Decimal(opening),
        closing_balance=Decimal(closing),
        statement_balance=Decimal(tagihan if tagihan is not None else closing),
        transactions=txns,
    )


# --- near-empty extraction → manual review -----------------------------------


def test_near_empty_text_routes_to_manual_review() -> None:
    res = check_extraction("   \n  ")
    assert res.outcome is ValidationOutcome.NEEDS_MANUAL_REVIEW
    assert res.alert is False  # a scanned PDF is not a corruption alert


def test_just_under_threshold_routes_to_manual_review() -> None:
    res = check_extraction("x" * (MIN_EXTRACTED_CHARS - 1))
    assert res.outcome is ValidationOutcome.NEEDS_MANUAL_REVIEW


def test_ample_text_passes_extraction_check() -> None:
    res = check_extraction("x" * (MIN_EXTRACTED_CHARS + 10))
    assert res.outcome is ValidationOutcome.OK
    assert res.ok


# --- savings continuity (asset: opening + credit − debit == closing) ---------


def test_valid_savings_passes() -> None:
    # 100 + 30cr − 20db = 110
    stmt = _savings("100", "110", [_txn(credit="30"), _txn(debit="20")])
    assert validate(stmt).outcome is ValidationOutcome.OK


def test_dormant_savings_passes() -> None:
    stmt = _savings("100", "100", [])  # zero mutasi, valid
    assert validate(stmt).outcome is ValidationOutcome.OK


def test_tampered_savings_rejected_and_alerts() -> None:
    stmt = _savings("100", "111", [_txn(credit="30"), _txn(debit="20")])  # off by 1
    res = validate(stmt)
    assert res.outcome is ValidationOutcome.REJECTED
    assert res.alert is True


# --- credit-card continuity (liability: opening + debit − credit == closing) --


def test_valid_credit_card_passes() -> None:
    # 4,247,403.83 + 838,900 − 4,248,000 = 838,303.83 (the real CIMB numbers)
    stmt = _credit_card("4247403.83", "838303.83", [_txn(debit="838900"), _txn(credit="4248000")])
    assert validate(stmt).outcome is ValidationOutcome.OK


def test_tampered_credit_card_rejected_and_alerts() -> None:
    stmt = _credit_card("4247403.83", "900000", [_txn(debit="838900"), _txn(credit="4248000")])
    res = validate(stmt)
    assert res.outcome is ValidationOutcome.REJECTED
    assert res.alert is True


def test_credit_card_tagihan_mismatch_rejected() -> None:
    # continuity holds, but Tagihan Baru != ENDING BALANCE → reject
    stmt = _credit_card(
        "4247403.83",
        "838303.83",
        [_txn(debit="838900"), _txn(credit="4248000")],
        tagihan="999999",
    )
    res = validate(stmt)
    assert res.outcome is ValidationOutcome.REJECTED
    assert res.alert is True


def test_incoherent_period_rejected() -> None:
    stmt = _savings("100", "100", [])
    bad = ParsedStatement(
        institution=stmt.institution,
        account_type=stmt.account_type,
        parser_version=stmt.parser_version,
        account_number_masked=stmt.account_number_masked,
        currency=stmt.currency,
        period_start=D1,
        period_end=D0,  # end before start
        opening_balance=stmt.opening_balance,
        closing_balance=stmt.closing_balance,
    )
    assert validate(bad).outcome is ValidationOutcome.REJECTED


def test_unknown_account_type_is_programmer_error() -> None:
    bad = ParsedStatement(
        institution="bca",
        account_type="bca_time_deposit",  # not a reconcilable type we know
        parser_version="test",
        account_number_masked="1",
        currency="IDR",
        period_start=D0,
        period_end=D1,
        opening_balance=Decimal("100"),
        closing_balance=Decimal("100"),
    )
    with pytest.raises(ValueError):
        validate(bad)


# --- portfolio: lot continuity is soft, never a rejection --------------------


def _holding(mv: str) -> ParsedHolding:
    return ParsedHolding(
        ticker="AMRT",
        name="X",
        lot_balance=Decimal("1"),
        share_balance=Decimal("100"),
        avg_price=Decimal("1"),
        market_price=Decimal(mv),
        market_value=Decimal(mv),
        unrealized=Decimal("0"),
    )


def test_portfolio_with_holdings_passes() -> None:
    pf = ParsedPortfolio(
        institution="ajaib",
        account_type="ajaib_portfolio",
        parser_version="test",
        account_number_masked="1",
        currency="IDR",
        as_of=D1,
        holdings=[_holding("1000")],
    )
    assert validate(pf).outcome is ValidationOutcome.OK


def test_cash_only_portfolio_passes() -> None:
    pf = ParsedPortfolio(
        institution="stockbit",
        account_type="stockbit_portfolio",
        parser_version="test",
        account_number_masked="1",
        currency="IDR",
        as_of=D1,
        holdings=[],
        cash_balance=Decimal("500"),
    )
    assert validate(pf).outcome is ValidationOutcome.OK


def test_empty_portfolio_routes_to_manual_review() -> None:
    pf = ParsedPortfolio(
        institution="ajaib",
        account_type="ajaib_portfolio",
        parser_version="test",
        account_number_masked="1",
        currency="IDR",
        as_of=D1,
        holdings=[],
        cash_balance=None,
    )
    res = validate(pf)
    assert res.outcome is ValidationOutcome.NEEDS_MANUAL_REVIEW
    assert res.alert is False


# --- real fixtures round-trip through the stage ------------------------------


def test_real_cimb_fixture_validates_ok() -> None:
    stmt = cimb.parse_text((FIXTURES / "cimb_mc_gold_2026-03.txt").read_text())
    assert validate(stmt).outcome is ValidationOutcome.OK


def test_real_ajaib_fixture_validates_ok() -> None:
    pf = ajaib.parse_text((FIXTURES / "ajaib_portfolio_2026-06-30.txt").read_text())
    assert validate(pf).outcome is ValidationOutcome.OK
