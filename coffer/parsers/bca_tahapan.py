"""BCA Tahapan (savings) statement parser.

Built against a real "REKENING TAHAPAN" e-statement (PERIODE JUNI 2026, 6 pages).

Layout facts this parser relies on (verified against the sample):

  * Amounts are ``1,234,567.89`` — comma thousands, dot decimals.
  * The statement is a **calendar-month** period (``PERIODE : JUNI 2026``); the
    account currency is ``MATA UANG : IDR``; the masked account number follows
    ``NO. REKENING :``. Each page repeats this header block.
  * The mutation table starts after the ``TANGGAL KETERANGAN CBG MUTASI SALDO``
    column header and continues until ``Bersambung ke halaman berikut`` (page
    break) or the footer summary block.
  * A transaction row starts with ``DD/MM`` and spans **several lines**: the first
    line carries the type/reference + the MUTASI amount (+ ``DB`` for debits, +
    an intermittently-printed running SALDO), followed by detail lines that carry
    the counterparty. Row-level SALDO is printed only sometimes, so continuity is
    checked at the **statement level** against the footer summary, not per row:
        SALDO AWAL + Σ credits − Σ debits == SALDO AKHIR
    and, as an extra gate, the parsed CR/DB totals and counts must equal the
    stated ``MUTASI CR`` / ``MUTASI DB`` figures.
  * Debit vs. credit: a debit row prints ``DB`` immediately after the MUTASI
    amount; a credit row (``TRSF E-BANKING CR ...``) does not.

Counterparty extraction (feeds learned rules / intra-household netting, SPEC §3.3)
depends on the transfer sub-type in the reference token:
  * ``FTSCY`` — transfer to another BCA account: detail carries the **name** only.
  * ``FTFVA`` — biller / e-wallet (DANA, SHOPEE, GOAPOTIK): ``<code>/<NAME>`` and a
    trailing virtual-account / phone number.
  * ``FTQRS`` — QR transfer: a masked ``Q...`` account and the **name**.
  * ``PYBCA`` — payroll (SALARY ...): a credit with a SALARY description.
  * ``KARTU KREDIT/PL`` — the savings-side counterpart of a BCA credit-card bill;
    detail carries the linked card number (``counterparty_acct``).
  * ``TRANSAKSI DEBIT`` — QR merchant purchase: ``00000.00<merchant>``.

Design contract (SPEC §4, §6):
  * ``parse(pdf_source)`` — production entry point (in-memory pdfplumber extraction).
  * ``parse_text(text)`` — pure function on already-extracted text (tests use an
    anonymized text fixture; no real PDF/PII committed).
  * On any structural or balance mismatch we RAISE, never return partial data.
"""

from __future__ import annotations

import calendar
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

PARSER_VERSION = "bca_tahapan/1.0.0"
INSTITUTION = "bca"
ACCOUNT_TYPE = "bca_savings"

_AMOUNT = r"[\d,]+\.\d{2}"
_AMOUNT_RE = re.compile(_AMOUNT)

_ACCT_RE = re.compile(r"NO\.\s*REKENING\s*:\s*(?P<acct>\S+)")
_CURRENCY_RE = re.compile(r"MATA\s*UANG\s*:\s*(?P<cur>\w+)")
_PERIOD_RE = re.compile(r"PERIODE\s*:\s*(?P<month>[A-Z]+)\s+(?P<year>\d{4})")
_COLUMN_HEADER = "TANGGAL KETERANGAN"
_CONTINUED = "Bersambung"

_SALDO_AWAL_RE = re.compile(rf"^SALDO AWAL\s*:\s*(?P<amt>{_AMOUNT})")
_SALDO_AKHIR_RE = re.compile(rf"^SALDO AKHIR\s*:\s*(?P<amt>{_AMOUNT})")
_MUTASI_CR_RE = re.compile(rf"^MUTASI CR\s*:\s*(?P<amt>{_AMOUNT})\s+(?P<n>\d+)")
_MUTASI_DB_RE = re.compile(rf"^MUTASI DB\s*:\s*(?P<amt>{_AMOUNT})\s+(?P<n>\d+)")

# A transaction row begins with DD/MM followed by a known keterangan type.
_ROW_START_RE = re.compile(r"^(?P<day>\d{2})/(?P<mon>\d{2})\s+(?P<ket>.+)$")

_INDONESIAN_MONTHS = {
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
# Transfer sub-types found in the reference token (e.g. "0406/FTSCY/WS95271").
_TRANSFER_SUBTYPES = ("FTSCY", "FTFVA", "FTQRS", "PYBCA")


def _money(s: str) -> Decimal:
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - guarded by regex
        raise StatementParseError(f"unparseable amount: {s!r}") from exc


def _required[T](value: T | None, msg: str) -> T:
    if value is None:
        raise StatementParseError(msg)
    return value


class _Raw:
    """A transaction accumulated across its multiple source lines."""

    __slots__ = ("day", "mon", "ket", "detail")

    def __init__(self, day: int, mon: int, ket: str) -> None:
        self.day = day
        self.mon = mon
        self.ket = ket
        self.detail: list[str] = []


def parse_text(text: str) -> ParsedStatement:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    acct = currency = None
    period_month = period_year = None
    saldo_awal = saldo_akhir = mutasi_cr = mutasi_db = None
    n_cr = n_db = None

    raws: list[_Raw] = []
    current: _Raw | None = None
    in_table = False

    for raw in lines:
        # header fields (repeat per page; first hit wins)
        if acct is None and (m := _ACCT_RE.search(raw)):
            acct = m.group("acct")
        if currency is None and (m := _CURRENCY_RE.search(raw)):
            currency = m.group("cur")
        if period_month is None and (m := _PERIOD_RE.search(raw)):
            period_month = _INDONESIAN_MONTHS.get(m.group("month"))
            if period_month is None:
                raise StatementParseError(f"unknown period month: {m.group('month')!r}")
            period_year = int(m.group("year"))

        # footer summary (the reconciliation anchor)
        if m := _SALDO_AWAL_RE.match(raw):
            saldo_awal = _money(m.group("amt"))
            in_table = False
            current = None
            continue
        if m := _SALDO_AKHIR_RE.match(raw):
            saldo_akhir = _money(m.group("amt"))
            continue
        if m := _MUTASI_CR_RE.match(raw):
            mutasi_cr, n_cr = _money(m.group("amt")), int(m.group("n"))
            continue
        if m := _MUTASI_DB_RE.match(raw):
            mutasi_db, n_db = _money(m.group("amt")), int(m.group("n"))
            continue

        # table boundaries
        if raw.startswith(_COLUMN_HEADER):
            in_table = True
            continue
        if raw.startswith(_CONTINUED):
            in_table = False
            current = None
            continue
        if not in_table:
            continue

        if m := _ROW_START_RE.match(raw):
            ket = m.group("ket")
            if ket.startswith("SALDO AWAL"):  # opening-balance row, not a transaction
                current = None
                continue
            current = _Raw(int(m.group("day")), int(m.group("mon")), ket)
            raws.append(current)
        elif current is not None:
            current.detail.append(raw)

    acct = _required(acct, "NO. REKENING not found")
    currency = _required(currency, "MATA UANG not found")
    period_month = _required(period_month, "PERIODE month not found")
    period_year = _required(period_year, "PERIODE year not found")
    saldo_awal = _required(saldo_awal, "SALDO AWAL not found")
    saldo_akhir = _required(saldo_akhir, "SALDO AKHIR not found")
    mutasi_cr = _required(mutasi_cr, "MUTASI CR not found")
    mutasi_db = _required(mutasi_db, "MUTASI DB not found")
    if not raws:
        raise StatementParseError("no transactions parsed")

    txns = [_build_txn(r, period_year) for r in raws]

    period_start = date(period_year, period_month, 1)
    period_end = date(period_year, period_month, calendar.monthrange(period_year, period_month)[1])

    stmt = ParsedStatement(
        institution=INSTITUTION,
        account_type=ACCOUNT_TYPE,
        parser_version=PARSER_VERSION,
        account_number_masked=acct,
        currency=currency,
        period_start=period_start,
        period_end=period_end,
        opening_balance=saldo_awal,
        closing_balance=saldo_akhir,
        transactions=txns,
    )
    _reconcile(stmt, mutasi_cr, mutasi_db, _required(n_cr, "CR count"), _required(n_db, "DB count"))
    return stmt


def _build_txn(r: _Raw, year: int) -> ParsedTransaction:
    try:
        txn_date = date(year, r.mon, r.day)
    except ValueError as exc:
        raise StatementParseError(f"invalid transaction date {r.day:02d}/{r.mon:02d}") from exc

    amt_match = _AMOUNT_RE.search(r.ket)
    if amt_match is None:
        raise StatementParseError(f"no amount on transaction line: {r.ket!r}")
    mutasi = _money(amt_match.group())
    is_debit = r.ket[amt_match.end() :].lstrip().startswith("DB")

    description = r.ket[: amt_match.start()].strip()
    name, acct = _counterparty(description, r.detail)

    return ParsedTransaction(
        date=txn_date,
        posting_date=txn_date,  # BCA savings prints a single date per row
        description=description,
        debit=mutasi if is_debit else Decimal("0"),
        credit=Decimal("0") if is_debit else mutasi,
        counterparty_name=name,
        counterparty_acct=acct,
        raw_ref=" | ".join([r.ket, *r.detail]),
    )


def _counterparty(description: str, detail: list[str]) -> tuple[str | None, str | None]:
    """Best-effort structured counterparty extraction, keyed by transaction type."""
    if description.startswith("TRANSAKSI DEBIT"):
        # QR merchant purchase; merchant name follows a "00000.00" reference prefix.
        for ln in detail:
            if m := re.match(r"^[\d.]+(?P<name>\D.*)$", ln):
                return m.group("name").strip(), None
        return None, None

    if description.startswith("BIAYA ADM"):
        return None, None  # bank fee, no counterparty

    if description.startswith("KARTU KREDIT"):
        # detail: ["0100 BCA CARD", "<card number>", "<name>"]
        acct = next((ln for ln in detail if ln.isdigit()), None)
        return "BCA CARD", acct

    if description.startswith("TRSF E-BANKING"):
        subtype = next((s for s in _TRANSFER_SUBTYPES if s in description), None)
        if subtype == "FTFVA":
            # detail: ["<code>/<BILLER>", "-", "-", "<va/phone>"]
            name = None
            if detail and "/" in detail[0]:
                name = detail[0].split("/", 1)[1].strip()
            acct = next((ln for ln in reversed(detail) if ln.isdigit()), None)
            return name, acct
        if subtype == "FTQRS":
            # detail: ["Q...masked acct...", "<name>"]
            acct = next((ln for ln in detail if ln.startswith("Q")), None)
            name = next((ln for ln in detail if not ln.startswith("Q")), None)
            return (name.strip() if name else None), acct
        if subtype == "PYBCA":
            return (detail[0].strip() if detail else None), None  # "SALARY 062026"
        # FTSCY (or unknown): a person-to-person transfer, name only, no acct shown.
        name = detail[-1].strip() if detail else None
        return name, None

    return None, None


def _reconcile(
    stmt: ParsedStatement, mutasi_cr: Decimal, mutasi_db: Decimal, n_cr: int, n_db: int
) -> None:
    """SPEC §4/§6 balance continuity — hard gate before ingest.

    Savings grows on credit and shrinks on debit. Cross-check the parsed totals and
    counts against the statement's own MUTASI CR / MUTASI DB footer figures.
    """
    credits = [t for t in stmt.transactions if t.credit > 0]
    debits = [t for t in stmt.transactions if t.debit > 0]
    total_cr = sum((t.credit for t in credits), Decimal("0"))
    total_db = sum((t.debit for t in debits), Decimal("0"))

    if total_cr != mutasi_cr or len(credits) != n_cr:
        raise BalanceReconciliationError(
            f"credit mismatch: parsed {total_cr} ({len(credits)} rows) vs "
            f"MUTASI CR {mutasi_cr} ({n_cr} rows)"
        )
    if total_db != mutasi_db or len(debits) != n_db:
        raise BalanceReconciliationError(
            f"debit mismatch: parsed {total_db} ({len(debits)} rows) vs "
            f"MUTASI DB {mutasi_db} ({n_db} rows)"
        )
    computed = stmt.opening_balance + total_cr - total_db
    if computed != stmt.closing_balance:
        raise BalanceReconciliationError(
            f"balance mismatch: SALDO AWAL {stmt.opening_balance} + CR {total_cr} "
            f"- DB {total_db} = {computed}, but SALDO AKHIR is {stmt.closing_balance}"
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
