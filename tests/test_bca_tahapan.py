"""Fixture-based tests for the BCA Tahapan (savings) parser (SPEC §4, §6, §3.3).

Anonymized text fixture — PII stripped, but every amount/date is real so the
balance-continuity reconciliation (saldo_awal + ΣCR − ΣDB == saldo_akhir) and the
BCA mutasi count/total checks are genuine.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from coffer.parsers import bca_tahapan as bca
from coffer.parsers.statement_types import (
    BalanceReconciliationError,
    ParsedStatement,
    StatementParseError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bca_tahapan_2026-06.txt"


@pytest.fixture()
def stmt() -> ParsedStatement:
    return bca.parse_text(FIXTURE.read_text())


def test_summary_block(stmt: ParsedStatement) -> None:
    assert stmt.institution == "bca"
    assert stmt.account_type == "bca_savings"
    assert stmt.account_number_masked == "0160XXXXXX"
    assert stmt.currency == "IDR"
    assert stmt.period_start == date(2026, 6, 1)
    assert stmt.period_end == date(2026, 6, 30)
    assert stmt.opening_balance == Decimal("1271334.69")  # SALDO AWAL
    assert stmt.closing_balance == Decimal("6125000.69")  # SALDO AKHIR
    # savings has no credit-card summary fields
    assert stmt.statement_balance is None
    assert stmt.minimum_payment is None
    assert stmt.overdue_minimum is None
    assert stmt.due_date is None


def test_transaction_counts_match_mutasi_summary(stmt: ParsedStatement) -> None:
    # footer: MUTASI CR ... 4, MUTASI DB ... 57
    credits = [t for t in stmt.transactions if t.credit > 0]
    debits = [t for t in stmt.transactions if t.debit > 0]
    assert len(credits) == 4
    assert len(debits) == 57
    assert len(stmt.transactions) == 61


def test_balance_reconciles_savings_direction(stmt: ParsedStatement) -> None:
    total_cr = sum(t.credit for t in stmt.transactions)
    total_db = sum(t.debit for t in stmt.transactions)
    assert total_cr == Decimal("36129637.00")  # MUTASI CR total
    assert total_db == Decimal("31275971.00")  # MUTASI DB total
    # savings: balance grows on credit, shrinks on debit (opposite of a CC)
    assert stmt.opening_balance + total_cr - total_db == stmt.closing_balance


def test_multipage_last_row_present_no_header_leak(stmt: ParsedStatement) -> None:
    # last transaction is on page 6 (30/06); header text must not leak into a txn
    last = [t for t in stmt.transactions if t.date == date(2026, 6, 30)]
    assert len(last) == 1
    assert last[0].debit == Decimal("36000.00")
    assert last[0].counterparty_name == "PT ROYAL W"
    assert not any("REKENING TAHAPAN" in t.description for t in stmt.transactions)
    assert not any("HALAMAN" in t.description for t in stmt.transactions)


def test_amounts_are_decimal(stmt: ParsedStatement) -> None:
    adm = next(t for t in stmt.transactions if t.description.startswith("BIAYA ADM"))
    assert adm.debit == Decimal("17000.00")
    assert isinstance(adm.debit, Decimal)
    assert adm.credit == Decimal("0")


# ── counterparty extraction (feeds learned rules / transfer netting, §3.3) ──────


def test_ftscy_person_transfer_name_no_acct(stmt: ParsedStatement) -> None:
    # 4 outbound transfers to a stable third-party name, no account number shown
    cp_a = [t for t in stmt.transactions if t.counterparty_name == "COUNTERPARTY A"]
    assert len(cp_a) == 4
    assert all(t.debit > 0 and t.counterparty_acct is None for t in cp_a)


def test_intra_household_transfers_to_member(stmt: ParsedStatement) -> None:
    # transfers to the other household member (feeds intra-household netting)
    member = [t for t in stmt.transactions if t.counterparty_name == "MEMBER DUA"]
    assert len(member) == 4
    assert all(t.debit > 0 for t in member)


def test_ftfva_biller_has_name_and_va_acct(stmt: ParsedStatement) -> None:
    dana = [t for t in stmt.transactions if t.counterparty_name == "DANA"]
    assert len(dana) == 3
    assert {t.counterparty_acct for t in dana} == {"8100000000", "081200000000"}


def test_ftqrs_transfer_has_masked_acct(stmt: ParsedStatement) -> None:
    qr = next(t for t in stmt.transactions if t.counterparty_name == "COUNTERPARTY B")
    assert qr.counterparty_acct == "Q0812XXXXXX06"
    assert qr.debit == Decimal("74000.00")


def test_salary_credit(stmt: ParsedStatement) -> None:
    salary = next(t for t in stmt.transactions if t.credit == Decimal("34069137.00"))
    assert salary.counterparty_name is not None
    assert "SALARY" in salary.counterparty_name


def test_credit_card_payment_links_cc_account(stmt: ParsedStatement) -> None:
    # KARTU KREDIT/PL — the savings-side counterpart to the CC bill (§3.3).
    ccpay = next(t for t in stmt.transactions if t.description.startswith("KARTU KREDIT"))
    assert ccpay.debit == Decimal("2177067.00")  # == CC Tagihan Baru
    assert ccpay.counterparty_acct == "0000000000000000"


def test_qr_merchant_name(stmt: ParsedStatement) -> None:
    idm = [t for t in stmt.transactions if t.counterparty_name == "IDM INDOMA"]
    assert len(idm) >= 5
    assert all(t.debit > 0 and t.counterparty_acct is None for t in idm)


# ── hard-fail behaviour ─────────────────────────────────────────────────────---


def test_tampered_amount_raises(stmt: ParsedStatement) -> None:
    text = FIXTURE.read_text().replace("BIAYA ADM 0998 17,000.00", "BIAYA ADM 0998 18,000.00")
    with pytest.raises(BalanceReconciliationError):
        bca.parse_text(text)


def test_missing_period_raises() -> None:
    text = FIXTURE.read_text().replace("PERIODE : JUNI 2026", "")
    with pytest.raises(StatementParseError):
        bca.parse_text(text)
