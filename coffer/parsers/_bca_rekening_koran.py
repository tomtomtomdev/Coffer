"""Shared BCA *Rekening Koran* (savings-account mutasi) parsing engine.

BCA Tahapan and Tapres e-statements share one statement format — the same multi-line
mutasi table, the same footer summary, and the same transfer-detail layout. Only the
header differs: the title (``REKENING TAHAPAN`` vs ``REKENING TAPRES``), the account
label (``NO. REKENING`` vs ``NOMOR REKENING``), and the period line (``PERIODE : JUNI
2026`` month-name vs ``PERIODE : 01-05-2026 S/D 31-05-2026`` date-range). This engine
handles both; the product-specific modules (`bca_tahapan`, `bca_tapres`) are thin
adapters that only supply their ``parser_version``.

Layout facts (verified against real Tahapan Jun-26 and Tapres/RDN May-26 samples):

  * Amounts are ``1,234,567.89`` (comma thousands, dot decimals). The debit marker may
    be spaced (``59,000.00 DB``) or glued (``8,135,533.00DB``) — both detected.
  * Account type is ``bca_savings`` for both products (SPEC §2 enum).
  * A transaction starts with ``DD/MM`` and spans several lines; row-level SALDO is
    printed intermittently, so continuity is checked at the statement level against the
    footer: SALDO AWAL + Σ credits − Σ debits == SALDO AKHIR, and Σ CR/DB totals + counts
    must equal the stated ``MUTASI CR`` / ``MUTASI DB`` figures (SPEC §4/§6). RAISE on any
    mismatch; never return partial data.
  * Counterparty extraction by transfer sub-type feeds learned rules / intra-household
    netting (SPEC §3.3): FTSCY (name only), FTFVA (biller + VA/phone), FTQRS (masked Q…
    acct + name), PYBCA (SALARY), KARTU KREDIT/PL (linked card number), QR merchant.
"""

from __future__ import annotations

import calendar
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import IO

from .statement_types import (
    BalanceReconciliationError,
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
)

INSTITUTION = "bca"
ACCOUNT_TYPE = "bca_savings"

_AMOUNT = r"[\d,]+\.\d{2}"
_AMOUNT_RE = re.compile(_AMOUNT)

# account label differs by product: "NO. REKENING" (Tahapan) / "NOMOR REKENING" (Tapres)
_ACCT_RE = re.compile(r"(?:NO\.\s*|NOMOR\s+)REKENING\s*:\s*(?P<acct>\S+)")
_CURRENCY_RE = re.compile(r"MATA\s*UANG\s*:\s*(?P<cur>\w+)")
# period line: month-name (Tahapan) or explicit date range (Tapres)
_PERIOD_MONTH_RE = re.compile(r"PERIODE\s*:\s*(?P<month>[A-Z]+)\s+(?P<year>\d{4})")
_PERIOD_RANGE_RE = re.compile(
    r"PERIODE\s*:\s*(?P<d1>\d{2})-(?P<m1>\d{2})-(?P<y1>\d{4})\s*S/D\s*"
    r"(?P<d2>\d{2})-(?P<m2>\d{2})-(?P<y2>\d{4})"
)
_COLUMN_HEADER = "TANGGAL KETERANGAN"
_CONTINUED = "Bersambung"

_SALDO_AWAL_RE = re.compile(rf"^SALDO AWAL\s*:\s*(?P<amt>{_AMOUNT})")
_SALDO_AKHIR_RE = re.compile(rf"^SALDO AKHIR\s*:\s*(?P<amt>{_AMOUNT})")
_MUTASI_CR_RE = re.compile(rf"^MUTASI CR\s*:\s*(?P<amt>{_AMOUNT})\s+(?P<n>\d+)")
_MUTASI_DB_RE = re.compile(rf"^MUTASI DB\s*:\s*(?P<amt>{_AMOUNT})\s+(?P<n>\d+)")

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


@dataclass
class _Period:
    start: date
    end: date
    year: int


@dataclass
class _Raw:
    """A transaction accumulated across its multiple source lines."""

    day: int
    mon: int
    ket: str
    detail: list[str]


def _parse_period(raw: str) -> _Period | None:
    if m := _PERIOD_RANGE_RE.search(raw):
        start = date(int(m.group("y1")), int(m.group("m1")), int(m.group("d1")))
        end = date(int(m.group("y2")), int(m.group("m2")), int(m.group("d2")))
        return _Period(start, end, start.year)
    if m := _PERIOD_MONTH_RE.search(raw):
        month = _INDONESIAN_MONTHS.get(m.group("month"))
        if month is None:
            raise StatementParseError(f"unknown period month: {m.group('month')!r}")
        year = int(m.group("year"))
        last = calendar.monthrange(year, month)[1]
        return _Period(date(year, month, 1), date(year, month, last), year)
    return None


def parse_rekening_koran(text: str, *, parser_version: str) -> ParsedStatement:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    acct = currency = None
    period: _Period | None = None
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
        if period is None:
            period = _parse_period(raw)

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
            current = _Raw(int(m.group("day")), int(m.group("mon")), ket, [])
            raws.append(current)
        elif current is not None:
            current.detail.append(raw)

    acct = _required(acct, "account number (NO./NOMOR REKENING) not found")
    currency = _required(currency, "MATA UANG not found")
    period = _required(period, "PERIODE not found")
    saldo_awal = _required(saldo_awal, "SALDO AWAL not found")
    saldo_akhir = _required(saldo_akhir, "SALDO AKHIR not found")
    mutasi_cr = _required(mutasi_cr, "MUTASI CR not found")
    mutasi_db = _required(mutasi_db, "MUTASI DB not found")

    # A dormant account can have zero mutasi ("* TIDAK ADA TRANSAKSI PADA BULAN INI *").
    # That is valid, not an error — the reconcile below still gates it (0 == MUTASI CR/DB 0);
    # a genuine "rows expected but not parsed" failure surfaces there as a count mismatch.
    txns = [_build_txn(r, period.year) for r in raws]

    stmt = ParsedStatement(
        institution=INSTITUTION,
        account_type=ACCOUNT_TYPE,
        parser_version=parser_version,
        account_number_masked=acct,
        currency=currency,
        period_start=period.start,
        period_end=period.end,
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
        # FTSCY (or unknown): a person/entity transfer; the name is the last detail line.
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


def parse_pdf(
    pdf_source: str | bytes | bytearray | IO[bytes], *, parser_version: str
) -> ParsedStatement:
    """Production entry point. Accepts an already-**decrypted** source (path, bytes,
    or a binary stream). Decryption is not this function's job; plaintext must never
    be written to disk.
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
    return parse_rekening_koran(text, parser_version=parser_version)
