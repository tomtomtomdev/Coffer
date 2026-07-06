"""CIMB Niaga credit-card statement parser.

Built against a real MC GOLD REGULER statement (Tgl. Statement 17/03/26).

Layout facts this parser relies on (verified against the sample):

  * Amounts are ``1,234,567.89`` — comma thousands, dot decimals. (Note: CIMB's
    *promotional prose* uses ``100.000`` dot-thousands, but every real monetary
    figure in the tables uses the comma/dot form. We only parse table figures.)
  * A credit line (payment / refund) is suffixed with `` CR``. No suffix = a
    charge (debit / spend).
  * Transaction rows: ``DD/MM DD/MM <description> <amount>[ CR]`` — the two dates
    are transaction date and posting date, WITHOUT a year. The year is inferred
    from ``Tgl. Statement`` with month-rollover handling.
  * Row-level balances are NOT printed; only ``LAST BALANCE`` (opening) and
    ``ENDING BALANCE`` (closing). Continuity is checked at the statement level:
        opening + Σ charges − Σ credits == closing
  * ``PAYMENT-THANK YOU`` is the card-bill payment (the CR counterpart to the
    savings-side ``KARTU KREDIT/PL`` transfer). This parser records it as a
    credit; the categorization layer types it ``transfer`` so it is not counted
    as income and not double-counted against spend (SPEC §3.3).

Design contract (SPEC §4, §6):
  * ``parse(pdf_path)`` — production entry point (pdfplumber extraction).
  * ``parse_text(text)`` — pure function on already-extracted text, so tests use
    an anonymized text fixture and never commit a real PDF containing PII.
  * On any structural mismatch or balance mismatch we RAISE, never return
    partial data.
"""

from __future__ import annotations

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

PARSER_VERSION = "cimb_kartu_kredit/1.0.0"
INSTITUTION = "cimb"
ACCOUNT_TYPE = "cimb_credit_card"
CURRENCY = "IDR"

_AMOUNT = r"[\d,]+\.\d{2}"

# DD/MM DD/MM  <description>  <amount>[ CR]
_TXN_RE = re.compile(
    rf"^(?P<txn>\d{{2}}/\d{{2}})\s+(?P<post>\d{{2}}/\d{{2}})\s+"
    rf"(?P<desc>.+?)\s+(?P<amt>{_AMOUNT})(?P<cr>\s+CR)?$"
)
_STATEMENT_DATE_RE = re.compile(r"Tgl\.\s*Statement\s+(\d{2}/\d{2}/\d{2})")
_DUE_DATE_RE = re.compile(r"Tgl\.\s*Jatuh\s*Tempo\s+(\d{2}/\d{2}/\d{2})")
# card-summary block. In the real extraction this is appended to the end of the
# address line, e.g. "...SENAYAN 5481 17XX XXXX 8086 838,303.83 0.00 50,000.00",
# so we .search() and anchor only the end.
_SUMMARY_RE = re.compile(
    rf"(?P<card>\d{{4}}\s+\w{{2}}XX\s+XXXX\s+\d{{4}})\s+"
    rf"(?P<baru>{_AMOUNT})\s+(?P<tertunggak>{_AMOUNT})\s+(?P<minimum>{_AMOUNT})$"
)
_LAST_BALANCE_RE = re.compile(rf"^LAST BALANCE\s+(?P<amt>{_AMOUNT})$")
_ENDING_BALANCE_RE = re.compile(rf"^ENDING BALANCE\s+(?P<amt>{_AMOUNT})$")


def _money(s: str) -> Decimal:
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - guarded by regex
        raise StatementParseError(f"unparseable amount: {s!r}") from exc


def _infer_year(day_month: str, statement_date: date) -> date:
    """Transaction rows carry DD/MM only. A transaction whose month is *after*
    the statement month must belong to the previous calendar year (billing cycle
    straddling a year boundary)."""
    d, m = (int(x) for x in day_month.split("/"))
    year = statement_date.year
    if m > statement_date.month:
        year -= 1
    try:
        return date(year, m, d)
    except ValueError as exc:
        raise StatementParseError(f"invalid transaction date {day_month!r}") from exc


def _parse_ddmmyy(s: str) -> date:
    d, m, y = (int(x) for x in s.split("/"))
    return date(2000 + y, m, d)


def parse_text(text: str) -> ParsedStatement:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    statement_date: date | None = None
    due_date: date | None = None
    card_masked: str | None = None
    statement_balance: Decimal | None = None
    minimum_payment: Decimal | None = None
    overdue_minimum: Decimal | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    txns: list[ParsedTransaction] = []

    in_txn_table = False

    for raw in lines:
        if statement_date is None:
            if m := _STATEMENT_DATE_RE.search(raw):
                statement_date = _parse_ddmmyy(m.group(1))
        if due_date is None:
            if m := _DUE_DATE_RE.search(raw):
                due_date = _parse_ddmmyy(m.group(1))

        if card_masked is None:
            if m := _SUMMARY_RE.search(raw):
                card_masked = re.sub(r"\s+", " ", m.group("card"))
                statement_balance = _money(m.group("baru"))
                overdue_minimum = _money(m.group("tertunggak"))
                minimum_payment = _money(m.group("minimum"))
                continue

        # Transaction table boundaries
        if raw.startswith("Tgl. Transaksi"):
            in_txn_table = True
            continue
        if raw.startswith("*** END OF STATEMENT"):
            in_txn_table = False

        if m := _LAST_BALANCE_RE.match(raw):
            opening_balance = _money(m.group("amt"))
            continue
        if m := _ENDING_BALANCE_RE.match(raw):
            closing_balance = _money(m.group("amt"))
            continue

        if in_txn_table and (m := _TXN_RE.match(raw)):
            if statement_date is None:
                raise StatementParseError(
                    "transaction row encountered before statement date was found"
                )
            amt = _money(m.group("amt"))
            is_credit = m.group("cr") is not None
            txns.append(
                ParsedTransaction(
                    date=_infer_year(m.group("txn"), statement_date),
                    posting_date=_infer_year(m.group("post"), statement_date),
                    description=re.sub(r"\s+", " ", m.group("desc")).strip(),
                    debit=Decimal("0") if is_credit else amt,
                    credit=amt if is_credit else Decimal("0"),
                    raw_ref=raw,
                )
            )

    statement_date = _required(statement_date, "Tgl. Statement not found")
    due_date = _required(due_date, "Tgl. Jatuh Tempo not found")
    card_masked = _required(card_masked, "card summary line not found")
    statement_balance = _required(statement_balance, "Tagihan Baru not found")
    minimum_payment = _required(minimum_payment, "Pembayaran Minimum not found")
    overdue_minimum = _required(overdue_minimum, "Tagihan Minimum Tertunggak not found")
    opening_balance = _required(opening_balance, "LAST BALANCE not found")
    closing_balance = _required(closing_balance, "ENDING BALANCE not found")
    if not txns:
        raise StatementParseError("no transactions parsed")

    period_start = min(t.date for t in txns)

    stmt = ParsedStatement(
        institution=INSTITUTION,
        account_type=ACCOUNT_TYPE,
        parser_version=PARSER_VERSION,
        account_number_masked=card_masked,
        currency=CURRENCY,
        period_start=period_start,
        period_end=statement_date,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        statement_balance=statement_balance,
        minimum_payment=minimum_payment,
        overdue_minimum=overdue_minimum,
        due_date=due_date,
        transactions=txns,
    )
    _reconcile(stmt)
    return stmt


def _reconcile(stmt: ParsedStatement) -> None:
    """SPEC §4/§6 balance continuity — hard gate before ingest.

    opening + Σ charges − Σ credits must equal closing, AND closing must equal
    the stated new-billing figure (Tagihan Baru).
    """
    charges = sum((t.debit for t in stmt.transactions), Decimal("0"))
    credits = sum((t.credit for t in stmt.transactions), Decimal("0"))
    computed = stmt.opening_balance + charges - credits
    if computed != stmt.closing_balance:
        raise BalanceReconciliationError(
            f"balance mismatch: LAST {stmt.opening_balance} + charges {charges} "
            f"- credits {credits} = {computed}, but ENDING BALANCE is "
            f"{stmt.closing_balance}"
        )
    if stmt.statement_balance != stmt.closing_balance:
        raise BalanceReconciliationError(
            f"Tagihan Baru {stmt.statement_balance} != ENDING BALANCE {stmt.closing_balance}"
        )


def _required[T](value: T | None, msg: str) -> T:
    if value is None:
        raise StatementParseError(msg)
    return value


def parse(pdf_source: str | bytes | bytearray | IO[bytes]) -> ParsedStatement:
    """Production entry point. Accepts an already-**decrypted** source: a path
    (str/Path), raw bytes, or a binary file-like (e.g. the ``BytesIO`` produced
    by the in-memory decryption stage, SPEC §4). Decryption is NOT this function's
    job — plaintext should never be written to disk on its account.

    Near-empty extraction routes to OCR/manual review upstream; here we fail
    loudly if there's no usable text layer.
    """
    import io

    import pdfplumber

    if isinstance(pdf_source, (bytes, bytearray)):
        pdf_source = io.BytesIO(pdf_source)

    # pdf_source is a path or a binary stream (bytes already wrapped above);
    # pdfplumber accepts both — its stricter signature just doesn't spell IO[bytes].
    with pdfplumber.open(pdf_source) as pdf:  # type: ignore[arg-type]
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if len(text.strip()) < 50:
        raise StatementParseError(
            "near-empty text extraction — likely a scanned PDF; route to OCR/manual review"
        )
    return parse_text(text)
