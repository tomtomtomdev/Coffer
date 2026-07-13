"""Validation stage — SPEC §4 "Validation (before dedup)".

Generalizes the per-parser balance-continuity reconcile into ONE pipeline gate that
produces a routing *decision* rather than raising. Three outcomes:

  ``OK``                  — passes every gate; proceed to dedup/persist.
  ``NEEDS_MANUAL_REVIEW`` — near-empty text extraction (scanned PDF); route to OCR /
                            manual review. NOT an error, NOT an alert.
  ``REJECTED``            — schema mismatch or a hard balance discontinuity on a cash
                            or credit-card statement. Do NOT ingest; raise an alert.

Cash / credit-card balance continuity is a **hard** gate (SPEC §4, §6): a mismatch
means the parse is wrong or the statement was tampered with, and ingesting it would
silently corrupt net worth. Portfolio lot continuity is **soft** (SPEC §3.2) —
corporate actions are legitimate discontinuities — so a portfolio snapshot is never
REJECTED for lot movement; only a structurally empty extraction routes it to review.

The stage re-derives continuity independently of the parser (defense in depth — SPEC
§6 lists balance reconciliation as a High risk). Each parser still raises on its own
reconcile as its contract ("raise, never return partial data"); this stage is where
the pipeline's authoritative routing decision — and the reject-vs-manual distinction
the parsers cannot express — is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from coffer.parsers.statement_types import ParsedPortfolio, ParsedStatement

# Below this many non-whitespace characters, treat extraction as failed (a scanned
# PDF yields little or no text) and route to OCR / manual review rather than parsing
# garbage. Mirrors the guard in the parsers' pdfplumber entry points.
MIN_EXTRACTED_CHARS = 50

# Cash / credit-card reconcile direction, keyed on ``account_type`` (SPEC §2 enum).
#   asset      (savings): closing == opening + Σcredit − Σdebit  (grows on credit)
#   liability  (CC):      closing == opening + Σdebit  − Σcredit  (grows on charge)
_ASSET_ACCOUNT_TYPES = frozenset({"bca_savings"})
_LIABILITY_ACCOUNT_TYPES = frozenset({"bca_credit_card", "cimb_credit_card"})


class ValidationOutcome(StrEnum):
    OK = "ok"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ValidationResult:
    """The gate's decision for one parsed statement/portfolio.

    ``alert`` is True only for REJECTED (a corruption/discontinuity the household
    should be told about); a manual-review route is expected traffic, not an alert.
    """

    outcome: ValidationOutcome
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is ValidationOutcome.OK

    @property
    def alert(self) -> bool:
        return self.outcome is ValidationOutcome.REJECTED


def check_extraction(text: str, *, min_chars: int = MIN_EXTRACTED_CHARS) -> ValidationResult:
    """Near-empty text extraction → manual review (SPEC §4, guards against scanned PDFs)."""
    if len(text.strip()) < min_chars:
        return ValidationResult(
            ValidationOutcome.NEEDS_MANUAL_REVIEW,
            "near-empty text extraction — likely a scanned PDF; route to OCR/manual review",
        )
    return ValidationResult(ValidationOutcome.OK)


def validate(parsed: ParsedStatement | ParsedPortfolio) -> ValidationResult:
    """Route a parsed result. Dispatches by kind; cash/CC continuity is hard-gated,
    portfolio lot continuity is soft."""
    if isinstance(parsed, ParsedPortfolio):
        return _validate_portfolio(parsed)
    return _validate_statement(parsed)


def _validate_statement(stmt: ParsedStatement) -> ValidationResult:
    # Schema check: coherent period ordering (a reversed period means a bad parse).
    if stmt.period_end < stmt.period_start:
        return ValidationResult(
            ValidationOutcome.REJECTED,
            f"period_end {stmt.period_end} precedes period_start {stmt.period_start}",
        )

    credits = sum((t.credit for t in stmt.transactions), Decimal("0"))
    debits = sum((t.debit for t in stmt.transactions), Decimal("0"))

    if stmt.account_type in _ASSET_ACCOUNT_TYPES:
        computed = stmt.opening_balance + credits - debits
    elif stmt.account_type in _LIABILITY_ACCOUNT_TYPES:
        computed = stmt.opening_balance + debits - credits
        # For a CC, the labelled liability (Tagihan Baru) must equal the ending balance.
        if stmt.statement_balance is not None and stmt.statement_balance != stmt.closing_balance:
            return ValidationResult(
                ValidationOutcome.REJECTED,
                f"Tagihan Baru {stmt.statement_balance} != closing {stmt.closing_balance}",
            )
    else:
        # Unknown account type: refuse to guess a sign convention for money — a
        # mis-signed reconcile would corrupt net worth. This is a programmer error
        # (a new account_type shipped without a reconcile rule), not bad statement data.
        raise ValueError(f"no reconcile rule for account_type {stmt.account_type!r}")

    if computed != stmt.closing_balance:
        return ValidationResult(
            ValidationOutcome.REJECTED,
            f"balance discontinuity: computed {computed} != closing {stmt.closing_balance}",
        )
    return ValidationResult(ValidationOutcome.OK)


def _validate_portfolio(pf: ParsedPortfolio) -> ValidationResult:
    # Lot continuity is soft (SPEC §3.2) — corporate actions are legitimate; never
    # reject on it. The only structural failure here is an empty extraction: nothing
    # was pulled out (no holdings and no cash), which looks like a scanned/failed PDF.
    if not pf.holdings and pf.cash_balance is None:
        return ValidationResult(
            ValidationOutcome.NEEDS_MANUAL_REVIEW,
            "portfolio snapshot has no holdings and no cash — route to manual review",
        )
    return ValidationResult(ValidationOutcome.OK)
