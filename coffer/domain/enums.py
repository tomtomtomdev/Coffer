"""Domain enums — the controlled vocabularies of the SPEC §2 data model.

Domain is the innermost layer: this module imports nothing from Coffer and
nothing outside the standard library. Every other layer may depend on these
names; they may depend on no other layer (Clean Architecture, CLAUDE.md).
"""

from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    """SPEC §2 ``account.account_type`` enum."""

    BCA_SAVINGS = "bca_savings"
    BCA_CREDIT_CARD = "bca_credit_card"
    CIMB_CREDIT_CARD = "cimb_credit_card"
    AJAIB_PORTFOLIO = "ajaib_portfolio"
    STOCKBIT_PORTFOLIO = "stockbit_portfolio"


class CategoryType(StrEnum):
    """SPEC §2 ``category.type`` — drives what counts as spend vs. flow (§3.3, §3.5)."""

    ROUTINE = "routine"  # recurring living spend; enters the routine estimate
    DISCRETIONARY = "discretionary"  # spend, but not "routine"
    TRANSFER = "transfer"  # same-owner / intra-household movement — not spend
    ONE_OFF = "one_off"  # real spend, excluded from the routine estimate
    INVESTMENT_MOVE = "investment_move"  # funding/withdrawing a brokerage — not spend
    INCOME = "income"  # salary and other credits (§3.5)


class Cadence(StrEnum):
    """SPEC §2 ``category.cadence`` — how a routine category enters the estimate (§3.3 step 4)."""

    MONTHLY = "monthly"
    ANNUAL = "annual"  # amortized to a monthly-equivalent
    IRREGULAR = "irregular"


class CategorySource(StrEnum):
    """SPEC §2 ``transaction.category_source`` — provenance of the category assignment.

    Precedence on ingest is parser → learned_rule → regex → uncategorized; a manual
    tag always wins (SPEC §3.3). Kept visible so an auto assignment can't silently
    corrupt spend/net-worth numbers.
    """

    PARSER = "parser"
    LEARNED_RULE = "learned_rule"
    MANUAL = "manual"
    ONBOARDING = "onboarding"


class UploadedVia(StrEnum):
    """SPEC §4 ingestion source — the two entry points into the pipeline."""

    TELEGRAM = "telegram"
    WEB = "web"


class PasswordScheme(StrEnum):
    """How an institution's statement password is obtained (SPEC §2/§4).

    Lives in the domain so both the ingestion decrypt stage and the persistence
    credential store speak one vocabulary (the decrypt module re-exports it).
    """

    STATIC = "static"  # same password every statement
    DERIVED = "derived"  # computed from stored inputs (e.g. DOB + card digits)
    PER_STATEMENT = "per_statement"  # a new password each time; prompt, never persist
