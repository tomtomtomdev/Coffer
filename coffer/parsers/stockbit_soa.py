"""Stockbit portfolio parser.

Built against a real "Statement of Account" (period 01/06/2026 - 30/06/2026) that
carries a cash SOA (dividends) followed by a ``PORTFOLIO STATEMENT`` holdings table.
This parser extracts the **holdings snapshot** + broker cash; the cash SOA dividend
rows are left for a later slice (they feed §3.5 income, not net-worth positions).

Layout facts this parser relies on (verified against the sample):

  * ``Date 01/06/2026 - 30/06/2026`` — the snapshot ``as_of`` is the period end.
    Broker cash is ``Cash Investor 100,040.99``; the client id follows ``Client``.
  * The holdings live under the ``PORTFOLIO STATEMENT`` heading. A holding row is:
        <TICKER> <NAME> <qty> <buyPrice> <closePrice> <buyValue> <mktValue> <unreal> <pct%>
    ``qty`` is shares (IDX lot = 100 shares); ``buyPrice``/``pct`` carry two decimals;
    other figures are comma-thousand integers; ``unreal`` may be negative. Long names
    wrap onto following lines and are appended. The statement lists an ``IDR`` cash
    pseudo-row among the holdings; it is kept so Σ market_value matches the Total.
  * The table ends at ``T O T A L <buyValue> <mktValue> <unreal>`` (spaced letters).
    There is an *earlier* cash-SOA ``T O T A L`` too, so holdings are only read after
    the ``PORTFOLIO STATEMENT`` heading.

Structural check (SPEC §6): Σ holding ``market_value`` == the portfolio Total market
value. Lot continuity is soft (§3.2) and cost/unrealized totals are not gated.

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

PARSER_VERSION = "stockbit_soa/1.0.0"
INSTITUTION = "stockbit"
ACCOUNT_TYPE = "stockbit_portfolio"
CURRENCY = "IDR"
_SHARES_PER_LOT = Decimal("100")

_NUM = r"[\d,]+"

_PORTFOLIO_HEADING = "PORTFOLIO STATEMENT"
_HOLDING_RE = re.compile(
    rf"^(?P<ticker>[A-Z]{{2,}})\s+(?P<name>.+?)\s+(?P<qty>{_NUM})\s+"
    rf"(?P<buy>{_NUM}\.\d{{2}})\s+(?P<close>{_NUM})\s+(?P<buyval>{_NUM})\s+"
    rf"(?P<mktval>{_NUM})\s+(?P<unreal>-?{_NUM})\s+(?P<pct>-?{_NUM}\.\d{{2}})$"
)
_TOTAL_RE = re.compile(
    rf"^T O T A L\s+(?P<buyval>{_NUM})\s+(?P<mktval>{_NUM})\s+(?P<unreal>-?{_NUM})$"
)
_NAME_CONT_RE = re.compile(r"^[A-Za-z().\s]+$")
_DATE_RE = re.compile(r"Date\s+\d{2}/\d{2}/\d{4}\s*-\s*(?P<d>\d{2})/(?P<m>\d{2})/(?P<y>\d{4})")
_CASH_RE = re.compile(r"Cash Investor\s+(?P<amt>[\d,]+\.\d{2})")
_CLIENT_RE = re.compile(r"Client\s+(?P<id>\d+)\b")


@dataclass
class _H:
    """Mutable holding accumulator (name may gain wrapped continuation lines)."""

    ticker: str
    name: str
    qty: Decimal
    buy: Decimal
    close: Decimal
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
    in_portfolio = False

    for raw in lines:
        if as_of is None and (m := _DATE_RE.search(raw)):
            as_of = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        if client is None and (m := _CLIENT_RE.search(raw)):
            client = m.group("id")
        if cash_balance is None and (m := _CASH_RE.search(raw)):
            cash_balance = _money(m.group("amt"))

        if raw.startswith(_PORTFOLIO_HEADING):
            in_portfolio = True
            continue
        if not in_portfolio:
            continue  # skip the cash SOA section (incl. its own T O T A L)

        if m := _TOTAL_RE.match(raw):
            total_mktval = _money(m.group("mktval"))
            break  # portfolio table done

        if m := _HOLDING_RE.match(raw):
            records.append(
                _H(
                    ticker=m.group("ticker"),
                    name=re.sub(r"\s+", " ", m.group("name")).strip(),
                    qty=_money(m.group("qty")),
                    buy=_money(m.group("buy")),
                    close=_money(m.group("close")),
                    mktval=_money(m.group("mktval")),
                    unreal=_money(m.group("unreal")),
                )
            )
        elif records and _NAME_CONT_RE.match(raw):
            records[-1].name = f"{records[-1].name} {raw.strip()}"

    as_of = _required(as_of, "SOA date range not found")
    client = _required(client, "Client id not found")
    total_mktval = _required(total_mktval, "PORTFOLIO STATEMENT Total not found")
    if not records:
        raise StatementParseError("no holdings parsed")

    holdings = [
        ParsedHolding(
            ticker=r.ticker,
            name=r.name,
            lot_balance=r.qty / _SHARES_PER_LOT,
            share_balance=r.qty,
            avg_price=r.buy,
            market_price=r.close,
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
    """SPEC §6 structural check: Σ market_value == printed Total market value."""
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
