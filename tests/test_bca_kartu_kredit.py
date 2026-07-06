"""Fixture-based tests for the BCA credit-card parser (SPEC §4, §6, §3.1/§3.4).

Anonymized text fixture — PII stripped, amounts/dates real. This is a **multi-card**
statement (VISA + BCA Everyday under one customer); the parser merges line items and
reconciles at the statement level:
    Σ SALDO SEBELUMNYA + Σ charges − Σ credits == TAGIHAN BARU.
Amounts are dot-thousand, no decimals (2.177.067) — distinct from CIMB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from coffer.parsers import bca_kartu_kredit as bca_cc
from coffer.parsers.statement_types import (
    BalanceReconciliationError,
    ParsedStatement,
    StatementParseError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bca_kartu_kredit_2026-06.txt"


@pytest.fixture()
def stmt() -> ParsedStatement:
    return bca_cc.parse_text(FIXTURE.read_text())


def test_summary_block(stmt: ParsedStatement) -> None:
    assert stmt.institution == "bca"
    assert stmt.account_type == "bca_credit_card"
    assert stmt.account_number_masked == "99999999"  # NOMOR CUSTOMER (links §3.3)
    assert stmt.currency == "IDR"
    assert stmt.period_end == date(2026, 6, 16)  # TANGGAL REKENING
    assert stmt.due_date == date(2026, 7, 2)  # TANGGAL JATUH TEMPO
    assert stmt.statement_balance == Decimal("2177067")  # TAGIHAN BARU
    assert stmt.minimum_payment == Decimal("108854")  # PEMBAYARAN MINIMUM
    assert stmt.opening_balance == Decimal("5157491")  # Σ SALDO SEBELUMNYA
    assert stmt.closing_balance == Decimal("2177067")


def test_period_start_is_earliest_txn(stmt: ParsedStatement) -> None:
    assert stmt.period_start == date(2026, 5, 18)  # 18-MEI


def test_transaction_counts(stmt: ParsedStatement) -> None:
    charges = [t for t in stmt.transactions if t.debit > 0]
    credits = [t for t in stmt.transactions if t.credit > 0]
    assert len(credits) == 2  # one MYBCA payment per card
    assert len(charges) == 47
    assert len(stmt.transactions) == 49


def test_dot_thousand_amounts_are_decimal(stmt: ParsedStatement) -> None:
    baby = next(t for t in stmt.transactions if "BABYSHOP" in t.description)
    assert baby.debit == Decimal("106700")  # "106.700" → 106700, not 106.700
    assert isinstance(baby.debit, Decimal)
    assert baby.credit == Decimal("0")


def test_payments_are_credits(stmt: ParsedStatement) -> None:
    credits = [t for t in stmt.transactions if t.credit > 0]
    assert all("PEMBAYARAN" in t.description for t in credits)
    assert sum(t.credit for t in credits) == Decimal("5157491")


def test_bea_meterai_is_a_charge(stmt: ParsedStatement) -> None:
    bea = next(t for t in stmt.transactions if "BEA METERAI" in t.description)
    assert bea.debit == Decimal("10000")
    assert bea.date == date(2026, 6, 16)


def test_year_inference_across_cards(stmt: ParsedStatement) -> None:
    # billing cycle mid-May → mid-June 2026; both MEI and JUN rows land in 2026
    assert all(t.date.year == 2026 for t in stmt.transactions)
    assert {t.date.month for t in stmt.transactions} == {5, 6}


def test_balance_reconciles(stmt: ParsedStatement) -> None:
    charges = sum(t.debit for t in stmt.transactions)
    credits = sum(t.credit for t in stmt.transactions)
    assert charges == Decimal("2177067")
    assert credits == Decimal("5157491")
    assert stmt.opening_balance + charges - credits == stmt.closing_balance


def test_tampered_amount_raises() -> None:
    text = FIXTURE.read_text().replace(
        "BABYSHOP SUPERMALL KRWC TANGERANG ID 106.700",
        "BABYSHOP SUPERMALL KRWC TANGERANG ID 106.800",
    )
    with pytest.raises(BalanceReconciliationError):
        bca_cc.parse_text(text)


def test_missing_tagihan_baru_raises() -> None:
    text = FIXTURE.read_text().replace("TAGIHAN BARU : RP 2.177.067", "")
    with pytest.raises(StatementParseError):
        bca_cc.parse_text(text)
