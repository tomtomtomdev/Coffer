"""Fixture-based tests for the CIMB Niaga credit-card parser (SPEC §6).

Runs against an anonymized text fixture — amounts and dates are the real ones,
so the balance-continuity assertion is a genuine test, but no PII or PDF binary
is committed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from coffer.parsers import cimb_kartu_kredit as cimb
from coffer.parsers.statement_types import (
    BalanceReconciliationError,
    ParsedStatement,
    StatementParseError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cimb_mc_gold_2026-03.txt"


@pytest.fixture()
def stmt() -> ParsedStatement:
    return cimb.parse_text(FIXTURE.read_text())


def test_summary_block(stmt: ParsedStatement) -> None:
    assert stmt.institution == "cimb"
    assert stmt.account_type == "cimb_credit_card"
    assert stmt.account_number_masked == "5481 17XX XXXX 0000"
    assert stmt.currency == "IDR"
    assert stmt.period_end == date(2026, 3, 17)  # Tgl. Statement
    assert stmt.due_date == date(2026, 4, 6)  # Tgl. Jatuh Tempo
    assert stmt.statement_balance == Decimal("838303.83")  # Tagihan Baru
    assert stmt.minimum_payment == Decimal("50000.00")
    assert stmt.overdue_minimum == Decimal("0.00")
    assert stmt.opening_balance == Decimal("4247403.83")
    assert stmt.closing_balance == Decimal("838303.83")


def test_transaction_count_and_split(stmt: ParsedStatement) -> None:
    # 7 charges + 1 payment = 8 line items (LAST/SUBTOTAL/ENDING are not txns)
    assert len(stmt.transactions) == 8
    charges = [t for t in stmt.transactions if t.debit > 0]
    credits = [t for t in stmt.transactions if t.credit > 0]
    assert len(charges) == 7
    assert len(credits) == 1
    assert credits[0].description == "PAYMENT-THANK YOU"
    assert credits[0].credit == Decimal("4248000.00")


def test_year_inference_across_month_boundary(stmt: ParsedStatement) -> None:
    # statement is March 2026; Feb rows must land in 2026, not roll to 2025
    feb = [t for t in stmt.transactions if t.date.month == 2]
    mar = [t for t in stmt.transactions if t.date.month == 3]
    assert all(t.date.year == 2026 for t in feb + mar)
    assert stmt.period_start == date(2026, 2, 18)  # earliest txn


def test_amount_parsing_is_decimal(stmt: ParsedStatement) -> None:
    first_charge = next(t for t in stmt.transactions if "9WEENF7WX9RFAV" in t.description)
    assert first_charge.debit == Decimal("54500.00")
    assert isinstance(first_charge.debit, Decimal)
    assert first_charge.credit == Decimal("0")


def test_balance_reconciles(stmt: ParsedStatement) -> None:
    charges = sum(t.debit for t in stmt.transactions)
    credits = sum(t.credit for t in stmt.transactions)
    assert charges == Decimal("838900.00")  # == Pembelanjaan 828,900 + Adm 10,000
    assert credits == Decimal("4248000.00")
    assert stmt.opening_balance + charges - credits == stmt.closing_balance


def test_reconciliation_hard_fails_on_tampered_amount() -> None:
    text = FIXTURE.read_text().replace(
        "18/02 19/02 Grab* A-9WEENF7WX9RFAV JAKARTA PUSATIDN 54,500.00",
        "18/02 19/02 Grab* A-9WEENF7WX9RFAV JAKARTA PUSATIDN 55,500.00",
    )
    with pytest.raises(BalanceReconciliationError):
        cimb.parse_text(text)


def test_missing_statement_date_raises() -> None:
    text = FIXTURE.read_text().replace("Tgl. Statement 17/03/26 ", "")
    with pytest.raises(StatementParseError):
        cimb.parse_text(text)
