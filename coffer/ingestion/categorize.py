"""Categorization stage + learned-rule engine — SPEC §3.3.

Two responsibilities:

1. **Ingest-time classification** (``classify`` / the repo-driven ``categorize``
   wrapper). Precedence, highest first (SPEC §3.3 "Precedence on ingest"):

     structural  intra-household transfer — the counterparty resolves to another
                 household account → definitively a ``transfer`` that nets out at
                 household level; never spend/income. Top tier because it's a hard
                 fact, not a guess.
     learned     an active ``LearnedRule`` matches on **structured** fields —
                 recipient account (the strong, safe key) first, then amount (weak,
                 guarded). Never on the noisy description string.
     regex       a household ``category.match_pattern`` matches the description.
     uncategorized  nothing matched → queued for a one-time human tag.

   A manual ``override`` always wins over all of the above, but that is recorded at
   re-tag time (``retag`` below), not on ingest.

2. **Learned-rule lifecycle** — ``build_learned_rule`` (create a rule when a user
   generalizes a tag; an amount-only rule needs explicit confirmation) and ``retag``
   (re-tagging a learned-rule result *refines* the rule by deactivating it, rather
   than fighting it with a perpetual override — SPEC §3.3 "Refinement over fighting").

Pure: ``classify`` takes already-fetched domain value objects; ``categorize`` fetches
them via the domain repo Protocols. Timestamps are injected (``now``) so the module
has no clock dependency and is deterministic under test. The dependency points inward
— ingestion → domain / parsers only (import-linter enforced).

**category_source reconciliation (SPEC §2 ↔ §3.3).** The §2 enum lists four sources
(``parser|learned_rule|manual|onboarding``); §3.3's precedence names a *regex* tier
that §2 has no source value for. We keep the authoritative four-value enum and stamp
both the structural (intra-household) and regex assignments as ``parser`` — for the
UI/audit they are the same thing: "system-assigned on ingest, correctable", as
opposed to ``learned_rule`` (auto, learned) or ``manual``/``onboarding`` (human-set).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from coffer.domain.entities import Account, Category, LearnedRule, Override
from coffer.domain.enums import Cadence, CategorySource, CategoryType
from coffer.domain.repositories import AccountRepo, CategoryRepo, LearnedRuleRepo
from coffer.parsers.statement_types import ParsedTransaction

# Identity marker for the seeded intra-household transfer category. It is a lookup
# key, NOT a regex pattern — descriptions are never matched against it (the sentinel
# prefix is skipped in the regex tier), so a description that happens to contain it
# can't be misclassified.
_SENTINEL_PREFIX = "@"
INTRA_HOUSEHOLD_TRANSFER_PATTERN = "@intra_household_transfer"


class RuleKey(StrEnum):
    """Which structured field a new learned rule generalizes on (SPEC §3.3)."""

    COUNTERPARTY_ACCT = "counterparty_acct"  # strong, safe; exact match
    AMOUNT = "amount"  # weak; requires explicit confirmation


@dataclass(frozen=True)
class Categorization:
    """The classifier's decision for one transaction.

    ``category_id is None`` means uncategorized (queue for review). ``matched_rule_id``
    is set only when a learned rule fired, so the caller can bump that rule's
    ``hit_count`` (which rules earn their keep — SPEC §3.3).
    """

    category_id: int | None
    source: CategorySource | None
    matched_rule_id: int | None = None
    reason: str = ""

    @property
    def uncategorized(self) -> bool:
        return self.category_id is None


def _amount(debit: Decimal, credit: Decimal) -> Decimal:
    """The transaction's magnitude: the non-zero side (debit for spend, credit for a
    payment/refund). Amount-keyed rules match on this."""
    return debit if debit != 0 else credit


def _acct_matches(counterparty_acct: str, household_account_number: str) -> bool:
    """Whether a parsed counterparty account is one of the household's own accounts.

    Exact match after trimming whitespace. Bank statements mask account numbers in
    varied ways; normalizing masked-vs-full forms needs the real seeded formats and
    is deferred to account seeding (S9) — we do not invent a masking scheme here
    (CLAUDE.md "Don't invent a format").
    """
    return counterparty_acct.strip() == household_account_number.strip()


def _is_intra_household(txn: ParsedTransaction, household_accounts: list[Account]) -> bool:
    if not txn.counterparty_acct:
        return False
    return any(
        _acct_matches(txn.counterparty_acct, a.account_number_masked) for a in household_accounts
    )


def _rule_amount_matches(rule: LearnedRule, amount: Decimal) -> bool:
    if rule.match_amount is None:
        return True  # an acct-only rule imposes no amount constraint
    tolerance = rule.match_amount_tolerance or Decimal("0")
    return abs(amount - rule.match_amount) <= tolerance


def _match_learned_rule(
    txn: ParsedTransaction, active_rules: list[LearnedRule]
) -> LearnedRule | None:
    """Recipient-acct rules first (strong key), then amount-only rules (weak key)."""
    amount = _amount(txn.debit, txn.credit)

    if txn.counterparty_acct:
        for rule in active_rules:
            if (
                rule.match_counterparty_acct is not None
                and _acct_matches(txn.counterparty_acct, rule.match_counterparty_acct)
                and _rule_amount_matches(rule, amount)
            ):
                return rule

    for rule in active_rules:
        if rule.match_counterparty_acct is None and rule.match_amount is not None:
            if _rule_amount_matches(rule, amount):
                return rule

    return None


def _match_regex_category(txn: ParsedTransaction, categories: list[Category]) -> Category | None:
    for cat in categories:
        if cat.match_pattern.startswith(_SENTINEL_PREFIX):
            continue  # identity markers (e.g. intra-household) are not description regexes
        if re.search(cat.match_pattern, txn.description, re.IGNORECASE):
            return cat
    return None


def classify(
    txn: ParsedTransaction,
    *,
    household_accounts: list[Account],
    categories: list[Category],
    active_rules: list[LearnedRule],
) -> Categorization:
    """Categorize one parsed transaction by the SPEC §3.3 precedence (pure)."""
    # 1. Structural: intra-household / same-owner transfer — a hard fact, top tier.
    if _is_intra_household(txn, household_accounts):
        intra = next(
            (c for c in categories if c.match_pattern == INTRA_HOUSEHOLD_TRANSFER_PATTERN), None
        )
        if intra is None or intra.id is None:
            # Detected a household counterparty but the transfer category isn't seeded:
            # a setup error, not bad data — refuse to guess (cf. validate.py).
            raise ValueError(
                "intra-household transfer detected but no seeded transfer category "
                f"({INTRA_HOUSEHOLD_TRANSFER_PATTERN!r}) is present"
            )
        return Categorization(intra.id, CategorySource.PARSER, reason="intra-household transfer")

    # 2. Learned rule (structured fields: recipient acct, then amount).
    rule = _match_learned_rule(txn, active_rules)
    if rule is not None:
        return Categorization(
            rule.category_id, CategorySource.LEARNED_RULE, matched_rule_id=rule.id
        )

    # 3. Regex category.match_pattern (stamped `parser` — see module docstring).
    cat = _match_regex_category(txn, categories)
    if cat is not None and cat.id is not None:
        return Categorization(cat.id, CategorySource.PARSER, reason="regex category")

    # 4. Uncategorized — queued for a one-time human tag.
    return Categorization(None, None)


def categorize(
    txn: ParsedTransaction,
    *,
    household_id: int,
    accounts: AccountRepo,
    categories: CategoryRepo,
    learned_rules: LearnedRuleRepo,
) -> Categorization:
    """Repo-driven wrapper over ``classify`` — fetches the household's accounts,
    categories and active rules once, then classifies. S9 fetches once per batch."""
    return classify(
        txn,
        household_accounts=accounts.list_by_household(household_id),
        categories=categories.list_by_household(household_id),
        active_rules=learned_rules.list_active_by_household(household_id),
    )


def build_learned_rule(
    *,
    household_id: int,
    category_id: int,
    key: RuleKey,
    counterparty_acct: str | None,
    amount: Decimal,
    now: datetime.datetime,
    created_from_transaction_id: int | None = None,
    amount_tolerance: Decimal | None = None,
    confirm_amount_only: bool = False,
) -> LearnedRule:
    """Create a learned rule from a user's generalized tag (SPEC §3.3).

    ``COUNTERPARTY_ACCT`` — the strong, safe key; requires a recipient account and
    needs no confirmation. ``AMOUNT`` — weak (collides across unrelated spend), so an
    amount-only rule requires ``confirm_amount_only=True`` at creation.
    """
    if key is RuleKey.COUNTERPARTY_ACCT:
        if not counterparty_acct:
            raise ValueError("a counterparty_acct rule requires a counterparty_acct")
        return LearnedRule(
            household_id=household_id,
            category_id=category_id,
            created_at=now,
            match_counterparty_acct=counterparty_acct,
            created_from_transaction_id=created_from_transaction_id,
        )

    # RuleKey.AMOUNT
    if not confirm_amount_only:
        raise ValueError(
            "an amount-only rule (no recipient acct) requires explicit confirmation "
            "(confirm_amount_only=True) — amounts collide across unrelated spend"
        )
    return LearnedRule(
        household_id=household_id,
        category_id=category_id,
        created_at=now,
        match_amount=amount,
        match_amount_tolerance=amount_tolerance,
        created_from_transaction_id=created_from_transaction_id,
    )


@dataclass(frozen=True)
class RetagResult:
    """The effect of a human re-tag: an ``override`` to record, and — when the prior
    assignment came from a learned rule — that rule deactivated (refinement)."""

    override: Override
    deactivated_rule: LearnedRule | None = None


def retag(
    *,
    transaction_id: int,
    new_category_id: int,
    now: datetime.datetime,
    member_id: int | None = None,
    prior_source: CategorySource | None = None,
    prior_rule: LearnedRule | None = None,
) -> RetagResult:
    """Apply a manual tag (SPEC §3.3 "A manual tag always wins").

    Records an ``Override``. If the transaction had been auto-classified by a learned
    rule, that rule is *deactivated* rather than repeatedly overridden — "refinement
    over fighting". Re-tagging a parser/regex or uncategorized result just records the
    override.
    """
    override = Override(
        transaction_id=transaction_id,
        category_id=new_category_id,
        member_id=member_id,
        created_at=now,
    )
    deactivated: LearnedRule | None = None
    if prior_source is CategorySource.LEARNED_RULE and prior_rule is not None and prior_rule.active:
        deactivated = replace(prior_rule, active=False)
    return RetagResult(override, deactivated)


def seed_categories(*, household_id: int) -> list[Category]:
    """The day-one regex category rules (SPEC §3.3 seed + Q4 routine set).

    Returned as unpersisted domain values (``id=None``); S9/onboarding persists them,
    which assigns ids. Patterns are regex/substring matched case-insensitively against
    the transaction description; the intra-household sentinel is an identity marker,
    not a description regex.
    """

    def cat(
        pattern: str,
        label: str,
        type_: CategoryType,
        cadence: Cadence = Cadence.MONTHLY,
    ) -> Category:
        return Category(
            household_id=household_id,
            match_pattern=pattern,
            label=label,
            type=type_,
            cadence=cadence,
        )

    T, R, A = CategoryType.TRANSFER, CategoryType.ROUTINE, Cadence.ANNUAL
    return [
        # transfers / non-spend
        cat(INTRA_HOUSEHOLD_TRANSFER_PATTERN, "Transfer Antar-Anggota", T, Cadence.IRREGULAR),
        cat(r"KARTU KREDIT/PL", "Pembayaran Kartu Kredit", T, Cadence.IRREGULAR),
        # routine — monthly (SPEC §3.3 Q4)
        cat(r"GRAB|GOJEK|GOPAY.*RIDE", "Transportasi", R),
        cat(r"PERTAMINA|SHELL|SPBU|BP AKR", "BBM", R),
        cat(r"TOL |JASA MARGA|E-TOLL|FLAZZ", "Tol", R),
        cat(r"INDOMARET|ALFAMART|SUPERINDO|RANCH|HYPERMART|QR.*INDOMA", "Belanja Harian", R),
        cat(r"GRABFOOD|SHOPEEFOOD|GOFOOD", "Pesan Antar Makanan", R),
        cat(r"\bPLN\b|PDAM|INDIHOME|BIZNET|TELKOMSEL|BYU|XL |INDOSAT", "Utilitas", R),
        cat(r"BPJS", "BPJS / Kesehatan", R),
        cat(r"KPR|ANGSURAN RUMAH", "KPR", R),
        cat(r"IPL|IURAN LINGKUNGAN|ESTATE", "IPL / Estate", R),
        cat(r"APOTEK|KLINIK|PHARMAC", "Apotek & Klinik", R),
        cat(r"NETFLIX|SPOTIFY|ICLOUD|GOOGLE.*STORAGE|YOUTUBE PREMIUM", "Langganan", R),
        # routine — annual (amortized in the estimate, SPEC §3.3 step 4)
        cat(r"STNK|PAJAK KENDARAAN", "STNK / Pajak Kendaraan", R, A),
        cat(r"ASURANSI|INSURANCE", "Asuransi", R, A),
        cat(r"SPP|UANG SEKOLAH|TUITION", "Biaya Sekolah", R, A),
    ]
