"""Ajaib portfolio-snapshot parser.

Built against a real "Client Portfolio" statement (as of 30 Jun 2026).

Layout facts this parser relies on (verified against the sample):

  * A snapshot as of a single date (``30 Jun 2026``, English abbreviated month),
    not a period. Broker cash is ``Saldo RDN : 5,099,584.00``.
  * A holding row is:
        <no> <TICKER>-<NAME> <lot> <shares> <avg> <cost> <mktPrice> <mktValue> <unreal>
    Amounts are comma-thousand; ``lot`` carries two decimals (``14.00``, ``0.19``
    for odd lots); ``unreal`` may be negative. A long company name may wrap onto
    the next line (e.g. a bare ``Tbk``); such fragments are appended to the name.
  * The table ends at ``Total : <cost> <mktValue> <unreal>``.

Structural check (SPEC §6): Σ holding ``market_value`` must equal the printed
Total **market value** — the net-worth-critical figure (§3.2). The broker's printed
Total *cost* and *unrealized* are rounded and can differ from the per-line sums by
±1, so they are NOT gated on. Lot continuity across snapshots is also soft
(corporate actions, §3.2), so it is not enforced here.

Design contract:
  * ``parse(pdf_source)`` — production entry point (in-memory pdfplumber extraction).
  * ``parse_text(text)`` — pure function on already-extracted text.
  * On a market-value mismatch or structural failure we RAISE, never return partial data.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import IO

from .statement_types import (
    BalanceReconciliationError,
    ParsedHolding,
    ParsedPortfolio,
    StatementParseError,
)

PARSER_VERSION = "ajaib_portfolio/1.0.0"
INSTITUTION = "ajaib"
ACCOUNT_TYPE = "ajaib_portfolio"
CURRENCY = "IDR"

_NUM = r"[\d,]+"
_SIGNED = r"-?[\d,]+"

_HOLDING_RE = re.compile(
    rf"^\d+\s+(?P<ticker>[A-Z0-9]+)-(?P<name>.+?)\s+"
    rf"(?P<lot>\d[\d,]*\.\d{{2}})\s+(?P<shares>{_NUM})\s+(?P<avg>{_NUM})\s+"
    rf"(?P<cost>{_NUM})\s+(?P<mktprice>{_NUM})\s+(?P<mktval>{_NUM})\s+(?P<unreal>{_SIGNED})$"
)
_TOTAL_RE = re.compile(
    rf"^Total\s*:\s*(?P<cost>{_NUM})\s+(?P<mktval>{_NUM})\s+(?P<unreal>{_SIGNED})$"
)
_NAME_CONT_RE = re.compile(r"^[A-Za-z().\s]+$")
_ASOF_RE = re.compile(r"^(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3})\s+(?P<y>\d{4})$")
_CLIENT_RE = re.compile(r"Client Code\s*:\s*(?P<code>\S+)")
_RDN_RE = re.compile(r"Saldo RDN\s*:\s*(?P<amt>[\d,]+\.\d{2})")

_MONTH_ABBR_EN = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


@dataclass
class _H:
    """Mutable holding accumulator (its name may gain wrapped continuation lines)."""

    ticker: str
    name: str
    lot: Decimal
    shares: Decimal
    avg: Decimal
    mktprice: Decimal
    mktval: Decimal
    unreal: Decimal


def _money(s: str) -> Decimal:
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - guarded by regex
        raise StatementParseError(f"unparseable amount: {s!r}") from exc


def _required[T](value: T | None, msg: str) -> T:
    if value is None:
        raise StatementParseError(msg)
    return value


def parse_text(text: str) -> ParsedPortfolio:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    as_of: date | None = None
    client: str | None = None
    cash_balance: Decimal | None = None
    records: list[_H] = []
    total_mktval: Decimal | None = None

    for raw in lines:
        if as_of is None and (m := _ASOF_RE.match(raw)):
            month = _MONTH_ABBR_EN.get(m.group("mon"))
            if month is not None:
                as_of = date(int(m.group("y")), month, int(m.group("d")))
        if client is None and (m := _CLIENT_RE.search(raw)):
            client = m.group("code")
        if cash_balance is None and (m := _RDN_RE.search(raw)):
            cash_balance = _money(m.group("amt"))

        if m := _TOTAL_RE.match(raw):
            total_mktval = _money(m.group("mktval"))
            break  # table done; footer prose follows

        if m := _HOLDING_RE.match(raw):
            records.append(
                _H(
                    ticker=m.group("ticker"),
                    name=re.sub(r"\s+", " ", m.group("name")).strip(),
                    lot=_money(m.group("lot")),
                    shares=_money(m.group("shares")),
                    avg=_money(m.group("avg")),
                    mktprice=_money(m.group("mktprice")),
                    mktval=_money(m.group("mktval")),
                    unreal=_money(m.group("unreal")),
                )
            )
        elif records and _NAME_CONT_RE.match(raw):
            records[-1].name = f"{records[-1].name} {raw.strip()}"

    as_of = _required(as_of, "snapshot date (e.g. '30 Jun 2026') not found")
    client = _required(client, "Client Code not found")
    total_mktval = _required(total_mktval, "Total (market value) not found")
    if not records:
        raise StatementParseError("no holdings parsed")

    holdings = [
        ParsedHolding(
            ticker=r.ticker,
            name=r.name,
            lot_balance=r.lot,
            share_balance=r.shares,
            avg_price=r.avg,
            market_price=r.mktprice,
            market_value=r.mktval,
            unrealized=r.unreal,
        )
        for r in records
    ]

    pf = ParsedPortfolio(
        institution=INSTITUTION,
        account_type=ACCOUNT_TYPE,
        parser_version=PARSER_VERSION,
        account_number_masked=client,
        currency=CURRENCY,
        as_of=as_of,
        holdings=holdings,
        cash_balance=cash_balance,
    )
    _reconcile(pf, total_mktval)
    return pf


def _reconcile(pf: ParsedPortfolio, total_mktval: Decimal) -> None:
    """SPEC §6 structural check: Σ market_value == printed Total market value.

    Not lot continuity (soft, §3.2); not cost/unrealized (broker rounds those totals).
    """
    sum_mktval = pf.total_market_value()
    if sum_mktval != total_mktval:
        raise BalanceReconciliationError(
            f"market-value mismatch: Σ holdings {sum_mktval} != printed Total {total_mktval}"
        )


def parse(pdf_source: str | bytes | bytearray | IO[bytes]) -> ParsedPortfolio:
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
    return parse_text(text)
