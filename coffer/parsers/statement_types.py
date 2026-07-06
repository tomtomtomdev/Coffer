"""Shared parser output contract.

Every parser (`bca_tahapan`, `bca_kartu_kredit`, `cimb_kartu_kredit`, ...) returns
a `ParsedStatement`. This is the domain boundary between the parsing layer and the
ingestion/validation layer (Clean Architecture: parsers know nothing about the DB).

Money is `Decimal` everywhere — never float. Financial data must not accumulate
binary-float error.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal


class StatementParseError(Exception):
    """Raised when the layout does not match what the parser expects.

    Per SPEC §6 (parser brittleness) this must hard-fail loudly rather than
    return partial/garbage data that would silently corrupt net-worth numbers.
    """


class BalanceReconciliationError(StatementParseError):
    """Raised when the parsed rows do not reconcile with the statement's own
    stated opening/closing balance (SPEC §4, §6 balance continuity)."""


@dataclass(frozen=True)
class ParsedTransaction:
    date: datetime.date  # transaction date (booking year inferred, see parser)
    posting_date: datetime.date
    description: str
    debit: Decimal  # charge / spend — money owed increases. 0 if none.
    credit: Decimal  # payment / refund (CR lines). 0 if none.
    counterparty_name: str | None = None  # merchants have none of interest; kept for schema parity
    counterparty_acct: str | None = None  # CC line items never carry a recipient acct
    raw_ref: str = ""  # the raw source line, for audit / re-parse


@dataclass(frozen=True)
class ParsedStatement:
    institution: str  # "cimb"
    account_type: str  # "cimb_credit_card"
    parser_version: str
    account_number_masked: str
    currency: str

    period_start: datetime.date
    period_end: datetime.date  # = statement date (Tgl. Statement)

    # credit-card summary block (feeds SPEC §3.1 liability + §3.4 bill aggregator)
    opening_balance: Decimal  # LAST BALANCE
    closing_balance: Decimal  # ENDING BALANCE
    statement_balance: Decimal  # Tagihan Baru (new billing) — the liability figure
    minimum_payment: Decimal  # Pembayaran Minimum
    overdue_minimum: Decimal  # Tagihan Minimum Yang Tertunggak
    due_date: datetime.date  # Tgl. Jatuh Tempo

    transactions: list[ParsedTransaction] = field(default_factory=list)

    def content_hash_fields(self) -> tuple[str, str, str, str, str]:
        """SPEC §4 dedup layer 2: (account_number, period_start, period_end,
        opening_balance, closing_balance)."""
        return (
            self.account_number_masked,
            self.period_start.isoformat(),
            self.period_end.isoformat(),
            str(self.opening_balance),
            str(self.closing_balance),
        )
