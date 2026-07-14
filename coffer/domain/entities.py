"""Domain entities — pure value objects for the SPEC §2 data model.

These are plain frozen dataclasses with **no** SQLAlchemy, no DB, no I/O. The
persistence layer maps them to/from ORM rows at its boundary (mappers), so the
domain stays a pure value world and the dependency points inward (CLAUDE.md).

Money is ``Decimal`` everywhere — never float. ``id`` is ``None`` before a row is
persisted and is assigned by the repository on ``add``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from coffer.domain.enums import (
    AccountType,
    Cadence,
    CategorySource,
    CategoryType,
    PasswordScheme,
    UploadedVia,
)


@dataclass(frozen=True)
class Household:
    name: str
    id: int | None = None


@dataclass(frozen=True)
class Member:
    """Attribution + Telegram mapping only; auth is a single shared login (SPEC §5)."""

    household_id: int
    name: str
    telegram_user_id: int | None = None
    id: int | None = None


@dataclass(frozen=True)
class Account:
    member_id: int
    institution: str  # "bca", "cimb", "ajaib", "stockbit"
    account_type: AccountType
    account_number_masked: str
    currency: str = "IDR"
    id: int | None = None


@dataclass(frozen=True)
class InstitutionCredential:
    """One shared statement password per institution (SPEC §2/§4).

    ``secret`` is the plaintext password (``static``) or the derivation inputs
    (``derived``); ``per_statement`` stores nothing (``secret is None``). The
    persistence layer encrypts ``secret`` at rest into the ``password_enc`` column
    — the domain never sees ciphertext and never logs the secret.
    """

    household_id: int
    institution: str
    password_scheme: PasswordScheme
    secret: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class Statement:
    """A parsed statement's persisted metadata (SPEC §2 ``statement``).

    Only the **encrypted original** is retained on disk (``encrypted_file_path``);
    plaintext never touches disk (SPEC §4). Child ``transaction`` / ``holding`` rows
    reference this by id and are persisted through their own repositories.
    """

    account_id: int
    period_start: datetime.date
    period_end: datetime.date
    file_hash: str  # SHA-256 of the raw bytes (dedup layer 1)
    content_hash: str  # hash of the content-hash fields (dedup layer 2)
    uploaded_via: UploadedVia
    uploaded_at: datetime.datetime
    parser_version: str
    is_encrypted: bool
    # The account's net-worth value as of this statement (SPEC §3.1 carry-forward).
    #   savings:   SALDO AKHIR;  credit card: Tagihan Baru (liability magnitude);
    #   portfolio: Σ holdings market value (broker cash is counted once via the
    #              mirroring RDN savings account — never added here, see recompute).
    # Populated by the persist stage (S9); None only for a statement with no balance.
    closing_balance: Decimal | None = None
    encrypted_file_path: str | None = None
    uploaded_by_member_id: int | None = None
    id: int | None = None


@dataclass(frozen=True)
class Transaction:
    statement_id: int
    account_id: int
    date: datetime.date
    description: str
    dedup_key: str  # hash of (account_id, date, description, debit, credit) — SPEC §4
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    balance: Decimal | None = None
    category_id: int | None = None
    category_source: CategorySource | None = None
    counterparty_name: str | None = None
    counterparty_acct: str | None = None
    raw_ref: str = ""
    edited_by: int | None = None
    edited_at: datetime.datetime | None = None
    id: int | None = None


@dataclass(frozen=True)
class Category:
    household_id: int
    match_pattern: str  # regex / substring against the description
    label: str
    type: CategoryType
    cadence: Cadence = Cadence.IRREGULAR
    id: int | None = None


@dataclass(frozen=True)
class Override:
    """A human tag on one transaction — the audit record of a manual reclassification (SPEC §2)."""

    transaction_id: int
    category_id: int
    created_at: datetime.datetime
    member_id: int | None = None
    id: int | None = None


@dataclass(frozen=True)
class LearnedRule:
    """Auto-classifies future matches on **structured** fields only (SPEC §3.3).

    Matches on ``match_counterparty_acct`` (the strong, safe key) and/or
    ``match_amount`` (weak — an amount-only rule requires explicit confirmation),
    never on the noisy description string.
    """

    household_id: int
    category_id: int
    created_at: datetime.datetime
    match_counterparty_acct: str | None = None
    match_amount: Decimal | None = None
    match_amount_tolerance: Decimal | None = None
    created_from_transaction_id: int | None = None
    active: bool = True
    hit_count: int = 0
    id: int | None = None


@dataclass(frozen=True)
class Holding:
    """One equity position from a broker snapshot (SPEC §2 ``holding``, §3.2)."""

    account_id: int
    statement_id: int
    ticker: str
    name: str
    lot_balance: Decimal
    avg_price: Decimal
    market_price: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    as_of_date: datetime.date
    id: int | None = None


@dataclass(frozen=True)
class NetworthSnapshot:
    """A point on the month-end carry-forward grid (SPEC §3.1).

    ``grid_date`` is the calendar month-end, never a single account's ``period_end``
    and never the upload date.
    """

    household_id: int
    grid_date: datetime.date
    cash_total: Decimal
    credit_liability_total: Decimal
    portfolio_total: Decimal
    net_worth: Decimal
    id: int | None = None
