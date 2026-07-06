"""Fixture-based tests for the BCA Tapres (savings) parser (SPEC §4, §6, §3.3).

Tapres shares the Tahapan Rekening Koran format via the shared engine; this suite
exercises the Tapres-specific header (title, NOMOR REKENING, date-range PERIODE) and
the glued debit marker (``8,135,533.00DB``). Anonymized fixture; amounts/dates real.
The sample is a brokerage RDN held as a Tapres — mostly transfers to/from AJAIB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from coffer.parsers import bca_tapres as tapres
from coffer.parsers.statement_types import (
    BalanceReconciliationError,
    ParsedStatement,
    StatementParseError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bca_tapres_2026-05.txt"
EMPTY_FIXTURE = Path(__file__).parent / "fixtures" / "bca_tapres_empty_2026-06.txt"


@pytest.fixture()
def stmt() -> ParsedStatement:
    return tapres.parse_text(FIXTURE.read_text())


def test_summary_block(stmt: ParsedStatement) -> None:
    assert stmt.institution == "bca"
    assert stmt.account_type == "bca_savings"
    assert stmt.parser_version == "bca_tapres/1.0.0"
    assert stmt.account_number_masked == "4958XXXXXX"  # NOMOR REKENING
    assert stmt.currency == "IDR"
    assert stmt.period_start == date(2026, 5, 1)  # date-range PERIODE
    assert stmt.period_end == date(2026, 5, 31)
    assert stmt.opening_balance == Decimal("13019239.14")
    assert stmt.closing_balance == Decimal("8702712.14")
    assert stmt.statement_balance is None  # savings, no CC fields
    assert stmt.due_date is None


def test_transaction_counts_match_mutasi_summary(stmt: ParsedStatement) -> None:
    credits = [t for t in stmt.transactions if t.credit > 0]
    debits = [t for t in stmt.transactions if t.debit > 0]
    assert len(credits) == 11
    assert len(debits) == 4
    assert len(stmt.transactions) == 15


def test_glued_debit_marker_is_a_debit(stmt: ParsedStatement) -> None:
    # "8,135,533.00DB" — marker glued to the amount (no space); must still be a debit
    txn = next(t for t in stmt.transactions if t.debit == Decimal("8135533.00"))
    assert txn.date == date(2026, 5, 7)
    assert txn.credit == Decimal("0")


def test_balance_reconciles(stmt: ParsedStatement) -> None:
    total_cr = sum(t.credit for t in stmt.transactions)
    total_db = sum(t.debit for t in stmt.transactions)
    assert total_cr == Decimal("14436252.00")
    assert total_db == Decimal("18752779.00")
    assert stmt.opening_balance + total_cr - total_db == stmt.closing_balance


def test_broker_counterparty_extracted(stmt: ParsedStatement) -> None:
    ajaib = [t for t in stmt.transactions if t.counterparty_name == "AJAIB SEKURITAS AS"]
    assert len(ajaib) == 13
    assert all(t.counterparty_acct is None for t in ajaib)  # FTSCY: name only


def test_own_transfer_and_business_counterparty(stmt: ParsedStatement) -> None:
    own = next(t for t in stmt.transactions if t.counterparty_name == "MEMBER SATU")
    assert own.debit == Decimal("5948582.00")
    sinar = next(t for t in stmt.transactions if t.counterparty_name == "SINAR DIGITAL TERD")
    assert sinar.credit == Decimal("2110002.00")


def test_amounts_are_decimal(stmt: ParsedStatement) -> None:
    t = stmt.transactions[0]
    assert isinstance(t.credit, Decimal)
    assert t.credit == Decimal("2110002.00")


def test_tampered_amount_raises() -> None:
    text = FIXTURE.read_text().replace(
        "TRSF E-BANKING CR 2605/FTSCY/WS95051 37,500.00", "...CR 2605/FTSCY/WS95051 37,600.00"
    )
    with pytest.raises(BalanceReconciliationError):
        tapres.parse_text(text)


def test_missing_period_raises() -> None:
    text = FIXTURE.read_text().replace("PERIODE : 01-05-2026 S/D 31-05-2026", "")
    with pytest.raises(StatementParseError):
        tapres.parse_text(text)


def test_empty_statement_no_transactions() -> None:
    # a dormant account: "* TIDAK ADA TRANSAKSI PADA BULAN INI *", MUTASI CR/DB 0.00 (0).
    # This is valid, not an error — it must parse and reconcile trivially.
    stmt = tapres.parse_text(EMPTY_FIXTURE.read_text())
    assert stmt.transactions == []
    assert stmt.opening_balance == Decimal("1.33")
    assert stmt.closing_balance == Decimal("1.33")
    assert stmt.period_start == date(2026, 6, 1)
    assert stmt.period_end == date(2026, 6, 30)
