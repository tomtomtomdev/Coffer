"""SQLAlchemy 2.0 ORM tables for the full SPEC §2 data model.

Money is mapped with ``Numeric`` (never ``Float``) so ``Decimal`` round-trips
exactly — reintroducing binary-float error is the one thing the whole domain
avoids. Balances use scale 2 (IDR at rest); broker prices/quantities use a wider
scale so fractional average costs survive.

Enums are stored as plain strings and converted to/from the domain ``StrEnum``s in
the mappers — this keeps the ORM decoupled from the domain vocabulary and keeps
migrations free of native-enum type churn.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# IDR money at rest: scale 2 is enough for every balance/amount we persist.
MONEY = Numeric(18, 2, asdecimal=True)
# Broker lots/prices: wider scale so a fractional average cost isn't truncated.
QTY = Numeric(28, 8, asdecimal=True)


class Base(DeclarativeBase):
    pass


class HouseholdRow(Base):
    __tablename__ = "household"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)


class MemberRow(Base):
    __tablename__ = "member"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("household.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    telegram_user_id: Mapped[int | None] = mapped_column(Integer, unique=True)


class AccountRow(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"), index=True)
    institution: Mapped[str] = mapped_column(String(50))
    account_type: Mapped[str] = mapped_column(String(50))
    account_number_masked: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="IDR")


class InstitutionCredentialRow(Base):
    __tablename__ = "institution_credential"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("household.id"), index=True)
    institution: Mapped[str] = mapped_column(String(50))
    password_scheme: Mapped[str] = mapped_column(String(20))
    # Ciphertext only — the plaintext secret is encrypted by the mapper (SPEC §6).
    password_enc: Mapped[str | None] = mapped_column(Text)


class StatementRow(Base):
    __tablename__ = "statement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    period_start: Mapped[datetime.date] = mapped_column(Date)
    period_end: Mapped[datetime.date] = mapped_column(Date)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    uploaded_via: Mapped[str] = mapped_column(String(20))
    uploaded_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("member.id"))
    uploaded_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str] = mapped_column(String(50))
    is_encrypted: Mapped[bool] = mapped_column(Boolean)
    # The account's net-worth value as of this statement (SPEC §3.1 carry-forward);
    # nullable for a statement that carries no balance. See recompute.py for semantics.
    closing_balance: Mapped[Decimal | None] = mapped_column(MONEY)
    # Credit-card bill summary (SPEC §3.4 due-date aggregator); null for non-CC statements.
    due_date: Mapped[datetime.date | None] = mapped_column(Date)
    minimum_payment: Mapped[Decimal | None] = mapped_column(MONEY)
    # The ORIGINAL (still-encrypted) PDF is retained here; plaintext never on disk.
    encrypted_file_path: Mapped[str | None] = mapped_column(Text)


class TransactionRow(Base):
    __tablename__ = "transaction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("statement.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(Text)
    debit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    balance: Mapped[Decimal | None] = mapped_column(MONEY)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"))
    category_source: Mapped[str | None] = mapped_column(String(20))
    counterparty_name: Mapped[str | None] = mapped_column(Text)
    counterparty_acct: Mapped[str | None] = mapped_column(String(100), index=True)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    raw_ref: Mapped[str] = mapped_column(Text, default="")
    edited_by: Mapped[int | None] = mapped_column(ForeignKey("member.id"))
    edited_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class CategoryRow(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("household.id"), index=True)
    match_pattern: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))
    cadence: Mapped[str] = mapped_column(String(20))


class OverrideRow(Base):
    __tablename__ = "override"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transaction.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("member.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


class LearnedRuleRow(Base):
    __tablename__ = "learned_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("household.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    match_counterparty_acct: Mapped[str | None] = mapped_column(String(100), index=True)
    match_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    match_amount_tolerance: Mapped[Decimal | None] = mapped_column(MONEY)
    created_from_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transaction.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


class HoldingRow(Base):
    __tablename__ = "holding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("statement.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(Text)
    lot_balance: Mapped[Decimal] = mapped_column(QTY)
    avg_price: Mapped[Decimal] = mapped_column(QTY)
    market_price: Mapped[Decimal] = mapped_column(QTY)
    market_value: Mapped[Decimal] = mapped_column(MONEY)
    unrealized_pl: Mapped[Decimal] = mapped_column(MONEY)
    as_of_date: Mapped[datetime.date] = mapped_column(Date)


class NetworthSnapshotRow(Base):
    __tablename__ = "networth_snapshot"
    # One snapshot per household per grid point; recompute upserts on this key (§3.1).
    __table_args__ = (UniqueConstraint("household_id", "grid_date", name="uq_snapshot_grid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("household.id"), index=True)
    grid_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    cash_total: Mapped[Decimal] = mapped_column(MONEY)
    credit_liability_total: Mapped[Decimal] = mapped_column(MONEY)
    portfolio_total: Mapped[Decimal] = mapped_column(MONEY)
    net_worth: Mapped[Decimal] = mapped_column(MONEY)
