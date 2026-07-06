"""BCA credit-card statement parser.

Built against a real "REKENING KARTU KREDIT" e-statement (TANGGAL REKENING
16 JUNI 2026, 3 pages) that is a **multi-card** statement — two cards (VISA +
BCA Everyday) billed under one NOMOR CUSTOMER.

Layout facts this parser relies on (verified against the sample):

  * Amounts are ``2.177.067`` — **dot thousands, no decimals** (distinct from the
    CIMB comma/dot format). Interest-rate prose (``1,75/21,00``) is never parsed.
  * A transaction row is ``DD-MMM DD-MMM <description> <amount>[ CR]`` — two dates
    (transaction, posting) with a 3-letter Indonesian month, WITHOUT a year. The
    year is inferred from ``TANGGAL REKENING`` with month-rollover handling. A
    ``CR`` suffix marks a payment/credit; otherwise the row is a charge/debit.
  * Only these double-dated rows are transactions; ``SALDO SEBELUMNYA``,
    ``SUBTOTAL``/``SUBTOTAL TRANSAKSI``, ``TOTAL``, card headers and page/legal
    text are not, and are skipped by the row pattern.
  * Line items from all cards are merged. Continuity is a **hard gate** at the
    statement level (SPEC §4/§6):
        Σ SALDO SEBELUMNYA + Σ charges − Σ credits == TAGIHAN BARU
    (each card's opening is its ``SALDO SEBELUMNYA``; the statement liability is
    the labelled ``TAGIHAN BARU``, which also equals the page-2 ``TOTAL``).
  * ``PEMBAYARAN - MYBCA`` is the card-bill payment — the CR counterpart to the
    savings-side ``KARTU KREDIT/PL`` transfer (SPEC §3.3); recorded as a credit,
    typed ``transfer`` by the categorization layer.

Labelled summary fields: ``NOMOR CUSTOMER`` (the id that links the savings-side
payment, §3.3), ``TANGGAL REKENING`` (period_end), ``TANGGAL JATUH TEMPO``
(due_date), ``TAGIHAN BARU`` (statement/closing balance), ``PEMBAYARAN MINIMUM``.
``overdue_minimum`` lives only in a positional grid here, so it is left unset.

Design contract (SPEC §4, §6):
  * ``parse(pdf_source)`` — production entry point (in-memory pdfplumber extraction).
  * ``parse_text(text)`` — pure function on already-extracted text (tests use an
    anonymized text fixture; no real PDF/PII committed).
  * On any structural or balance mismatch we RAISE, never return partial data.
"""

from __future__ import annotations

import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import IO

from .statement_types import (
    BalanceReconciliationError,
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
)

PARSER_VERSION = "bca_kartu_kredit/1.0.0"
INSTITUTION = "bca"
ACCOUNT_TYPE = "bca_credit_card"
CURRENCY = "IDR"

# dot-thousand integer, no decimals: 7.000, 2.177.067, 106.700
_AMOUNT = r"\d{1,3}(?:\.\d{3})*"

# DD-MMM DD-MMM <description> <amount>[ CR]
_TXN_RE = re.compile(
    rf"^(?P<td>\d{{2}})-(?P<tm>[A-Z]{{3}})\s+(?P<pd>\d{{2}})-(?P<pm>[A-Z]{{3}})\s+"
    rf"(?P<desc>.+?)\s+(?P<amt>{_AMOUNT})(?P<cr>\s+CR)?$"
)
_SALDO_SEBELUMNYA_RE = re.compile(rf"^SALDO SEBELUMNYA\s+(?P<amt>{_AMOUNT})$")
_CUSTOMER_RE = re.compile(r"NOMOR CUSTOMER\s*:\s*(?P<id>\S+)")
_STMT_DATE_RE = re.compile(r"TANGGAL REKENING\s*:\s*(?P<d>\d{2})\s+(?P<mon>[A-Z]+)\s+(?P<y>\d{4})")
_DUE_DATE_RE = re.compile(
    r"TANGGAL JATUH TEMPO\s*:\s*(?P<d>\d{2})\s+(?P<mon>[A-Z]+)\s+(?P<y>\d{4})"
)
_TAGIHAN_BARU_RE = re.compile(rf"TAGIHAN BARU\s*:\s*RP\s*(?P<amt>{_AMOUNT})")
_MINIMUM_RE = re.compile(rf"PEMBAYARAN MINIMUM\s*:\s*RP\s*(?P<amt>{_AMOUNT})")

_MONTH_ABBR = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MEI": 5,
    "JUN": 6,
    "JUL": 7,
    "AGT": 8,
    "AGU": 8,
    "AGS": 8,
    "SEP": 9,
    "OKT": 10,
    "NOV": 11,
    "DES": 12,
}
_MONTH_FULL = {
    "JANUARI": 1,
    "FEBRUARI": 2,
    "MARET": 3,
    "APRIL": 4,
    "MEI": 5,
    "JUNI": 6,
    "JULI": 7,
    "AGUSTUS": 8,
    "SEPTEMBER": 9,
    "OKTOBER": 10,
    "NOVEMBER": 11,
    "DESEMBER": 12,
}


def _money(s: str) -> Decimal:
    try:
        return Decimal(s.replace(".", ""))
    except InvalidOperation as exc:  # pragma: no cover - guarded by regex
        raise StatementParseError(f"unparseable amount: {s!r}") from exc


def _required[T](value: T | None, msg: str) -> T:
    if value is None:
        raise StatementParseError(msg)
    return value


def _full_date(day: str, month_name: str, year: str) -> date:
    month = _MONTH_FULL.get(month_name)
    if month is None:
        raise StatementParseError(f"unknown month name: {month_name!r}")
    return date(int(year), month, int(day))


def _infer_year(day: str, month_abbr: str, stmt_date: date) -> date:
    month = _MONTH_ABBR.get(month_abbr)
    if month is None:
        raise StatementParseError(f"unknown month abbreviation: {month_abbr!r}")
    year = stmt_date.year - 1 if month > stmt_date.month else stmt_date.year
    try:
        return date(year, month, int(day))
    except ValueError as exc:
        raise StatementParseError(f"invalid transaction date {day}-{month_abbr}") from exc


def parse_text(text: str) -> ParsedStatement:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    customer = statement_balance = minimum_payment = None
    stmt_date: date | None = None
    due_date: date | None = None
    opening = Decimal("0")
    saldo_count = 0
    txns: list[ParsedTransaction] = []

    # first pass: labelled summary fields + per-card openings
    for raw in lines:
        if customer is None and (m := _CUSTOMER_RE.search(raw)):
            customer = m.group("id")
        if stmt_date is None and (m := _STMT_DATE_RE.search(raw)):
            stmt_date = _full_date(m.group("d"), m.group("mon"), m.group("y"))
        if due_date is None and (m := _DUE_DATE_RE.search(raw)):
            due_date = _full_date(m.group("d"), m.group("mon"), m.group("y"))
        if statement_balance is None and (m := _TAGIHAN_BARU_RE.search(raw)):
            statement_balance = _money(m.group("amt"))
        if minimum_payment is None and (m := _MINIMUM_RE.search(raw)):
            minimum_payment = _money(m.group("amt"))
        if m := _SALDO_SEBELUMNYA_RE.match(raw):
            opening += _money(m.group("amt"))
            saldo_count += 1

    customer = _required(customer, "NOMOR CUSTOMER not found")
    stmt_date = _required(stmt_date, "TANGGAL REKENING not found")
    due_date = _required(due_date, "TANGGAL JATUH TEMPO not found")
    statement_balance = _required(statement_balance, "TAGIHAN BARU not found")
    minimum_payment = _required(minimum_payment, "PEMBAYARAN MINIMUM not found")
    if saldo_count == 0:
        raise StatementParseError("no SALDO SEBELUMNYA (card opening) found")

    # second pass: transaction rows (only double-dated lines qualify)
    for raw in lines:
        if not (m := _TXN_RE.match(raw)):
            continue
        amt = _money(m.group("amt"))
        is_credit = m.group("cr") is not None
        txns.append(
            ParsedTransaction(
                date=_infer_year(m.group("td"), m.group("tm"), stmt_date),
                posting_date=_infer_year(m.group("pd"), m.group("pm"), stmt_date),
                description=re.sub(r"\s+", " ", m.group("desc")).strip(),
                debit=Decimal("0") if is_credit else amt,
                credit=amt if is_credit else Decimal("0"),
                raw_ref=raw,
            )
        )

    if not txns:
        raise StatementParseError("no transactions parsed")

    period_start = min(t.date for t in txns)

    stmt = ParsedStatement(
        institution=INSTITUTION,
        account_type=ACCOUNT_TYPE,
        parser_version=PARSER_VERSION,
        account_number_masked=customer,
        currency=CURRENCY,
        period_start=period_start,
        period_end=stmt_date,
        opening_balance=opening,
        closing_balance=statement_balance,
        statement_balance=statement_balance,
        minimum_payment=minimum_payment,
        due_date=due_date,
        transactions=txns,
    )
    _reconcile(stmt)
    return stmt


def _reconcile(stmt: ParsedStatement) -> None:
    """SPEC §4/§6 balance continuity — hard gate before ingest.

    A credit card grows on charges and shrinks on payments:
        Σ SALDO SEBELUMNYA + Σ charges − Σ credits == TAGIHAN BARU.
    """
    charges = sum((t.debit for t in stmt.transactions), Decimal("0"))
    credits = sum((t.credit for t in stmt.transactions), Decimal("0"))
    computed = stmt.opening_balance + charges - credits
    if computed != stmt.closing_balance:
        raise BalanceReconciliationError(
            f"balance mismatch: opening {stmt.opening_balance} + charges {charges} "
            f"- credits {credits} = {computed}, but TAGIHAN BARU is {stmt.closing_balance}"
        )


def parse(pdf_source: str | bytes | bytearray | IO[bytes]) -> ParsedStatement:
    """Production entry point. Accepts an already-**decrypted** source (path, bytes,
    or a binary stream such as the in-memory ``BytesIO`` from the decryption stage).
    Decryption is not this function's job; plaintext must never be written to disk.
    """
    import pdfplumber

    if isinstance(pdf_source, (bytes, bytearray)):
        pdf_source = io.BytesIO(pdf_source)

    with pdfplumber.open(pdf_source) as pdf:  # type: ignore[arg-type]
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if len(text.strip()) < 50:
        raise StatementParseError(
            "near-empty text extraction — likely a scanned PDF; route to OCR/manual review"
        )
    return parse_text(text)
