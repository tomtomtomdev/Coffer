"""Ingestion orchestration use-case — SPEC §4 pipeline.

Ties the stages together in order:

    Decrypt → Parse → Validate → Dedup → Persist → Recompute (serialized per household)

Like every other ingestion stage this is **pure and repo-driven**: it reads and writes
only through the domain repo Protocols and a few injected infra *ports* (a ``PdfReader``
for decrypt+text-extraction, a ``StatementArchive`` for at-rest retention, the recompute
lock, and a clock). It never imports ``coffer.persistence`` — the concrete SQL repos,
the pikepdf/pdfplumber reader and the filesystem archive are all wired by the api layer
(the S9 endpoint), so the use-case is testable with in-memory fakes and no real
PDF/Postgres (mirroring ``dedup`` / ``categorize`` / ``recompute``).

**Outcomes** (one per uploaded file) map straight to the SPEC §4 response
("✅ N new, ⏭️ M duplicates skipped, ⚠️ needs account, 🔒 needs password"):

  ``INGESTED``        persisted; ``new_transactions`` / ``duplicate_transactions`` /
                      ``holdings`` carry the per-row counts.
  ``DUPLICATE``       the whole file / content was already stored (dedup layers 1–2).
  ``NEEDS_PASSWORD``  encrypted and no/wrong password — the source of the password is the
                      caller's concern (runtime entry); this stage never stores or logs it.
  ``NEEDS_ACCOUNT``   the target account could not be resolved (web sends the manually
                      selected ``account_id``; an unknown id routes here).
  ``NEEDS_REVIEW``    near-empty text extraction (scanned PDF) or an empty portfolio
                      snapshot — route to OCR / manual review. Not an alert.
  ``REJECTED``        a parser raised (structural / balance discontinuity) or the
                      validation gate rejected it — do NOT ingest; ``alert`` is True.

**Password handling.** The password is a runtime argument (Tommy prefers runtime entry
over storing it — PROGRESS "Password entry mechanism"). This stage never sources it from
the credential store; the ``PdfReader`` resolves plaintext in memory and raises
``StatementDecryptionError`` on a wrong/missing password, which we surface as
``NEEDS_PASSWORD``. Wiring the ``static``-scheme stored-credential path is a clean
extension (inject a reader that consults ``InstitutionCredentialRepo``).

**closing_balance per family** (SPEC §3.1 carry-forward — populated here, per S7):
savings = SALDO AKHIR; credit card = Tagihan Baru / ENDING BALANCE (liability magnitude,
already reconciled equal by validate); portfolio = Σ holdings market value (broker cash
is excluded — it is counted once via the mirroring RDN savings balance, see recompute).
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from coffer.domain.entities import Holding, Statement, Transaction
from coffer.domain.enums import AccountType, UploadedVia
from coffer.domain.repositories import (
    AccountRepo,
    CategoryRepo,
    HoldingRepo,
    LearnedRuleRepo,
    MemberRepo,
    NetworthSnapshotRepo,
    StatementRepo,
    TransactionRepo,
)
from coffer.ingestion.categorize import classify
from coffer.ingestion.decrypt import StatementDecryptionError
from coffer.ingestion.dedup import KeyedTransaction, dedup
from coffer.ingestion.recompute import HouseholdRecomputeLock, recompute_for_statement
from coffer.ingestion.validate import ValidationOutcome, check_extraction, validate
from coffer.parsers.statement_types import (
    ParsedPortfolio,
    ParsedStatement,
    StatementParseError,
)

__all__ = [
    "DecryptedPdf",
    "IngestOutcome",
    "IngestResult",
    "IngestStatement",
    "ParserRegistry",
    "PdfReader",
    "StatementArchive",
    "StatementParser",
]


# ── injected infra ports (concrete adapters live in the api layer) ───────────────────
@dataclass(frozen=True)
class DecryptedPdf:
    """The result of decrypting (in memory) + extracting text from an uploaded PDF."""

    text: str
    was_encrypted: bool  # whether the *original* upload was password-protected


class PdfReader(Protocol):
    """Decrypt in memory then extract the text layer (pikepdf → pdfplumber).

    Raises ``StatementDecryptionError`` when the PDF is encrypted and the password is
    wrong or missing — never leaks the attempted password (security invariant)."""

    def read(self, raw_bytes: bytes, password: str | None) -> DecryptedPdf: ...


class StatementArchive(Protocol):
    """Persist the retained original (SPEC §4). Only the *encrypted* original is kept;
    an unencrypted arrival is encrypted at rest before storing. Returns the stored path."""

    def store(self, *, raw_bytes: bytes, was_encrypted: bool) -> str: ...


# A parser's pure text entry point: ``parse_text``. Return-type covariance lets a
# ``-> ParsedStatement`` parser satisfy the union.
StatementParser = Callable[[str], ParsedStatement | ParsedPortfolio]
ParserRegistry = Mapping[AccountType, StatementParser]


# ── outcome model ────────────────────────────────────────────────────────────────────
class IngestOutcome(StrEnum):
    INGESTED = "ingested"
    DUPLICATE = "duplicate"
    NEEDS_PASSWORD = "needs_password"
    NEEDS_ACCOUNT = "needs_account"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


@dataclass(frozen=True)
class IngestResult:
    outcome: IngestOutcome
    reason: str = ""
    new_transactions: int = 0
    duplicate_transactions: int = 0
    holdings: int = 0
    statement_id: int | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is IngestOutcome.INGESTED

    @property
    def alert(self) -> bool:
        # A rejected statement is a corruption/tamper signal the household should see;
        # a needs-review / needs-password / needs-account route is expected traffic.
        return self.outcome is IngestOutcome.REJECTED


@dataclass
class IngestStatement:
    """Orchestrates one upload through the pipeline (SPEC §4). Humble callers (the web
    endpoint, the Telegram webhook) parse the request and call ``execute``."""

    accounts: AccountRepo
    members: MemberRepo
    statements: StatementRepo
    transactions: TransactionRepo
    categories: CategoryRepo
    learned_rules: LearnedRuleRepo
    holdings: HoldingRepo
    snapshots: NetworthSnapshotRepo
    reader: PdfReader
    parsers: ParserRegistry
    archive: StatementArchive
    lock: HouseholdRecomputeLock
    clock: Callable[[], datetime.datetime]

    def execute(
        self,
        *,
        raw_bytes: bytes,
        account_id: int,
        uploaded_via: UploadedVia,
        password: str | None = None,
        uploaded_by_member_id: int | None = None,
    ) -> IngestResult:
        # 1. Resolve the target account + its household (account → member → household).
        account = self.accounts.get(account_id)
        if account is None or account.id is None:
            return IngestResult(IngestOutcome.NEEDS_ACCOUNT, reason=f"no account {account_id}")
        member = self.members.get(account.member_id)
        if member is None:
            return IngestResult(IngestOutcome.NEEDS_ACCOUNT, reason="account has no member")
        household_id = member.household_id

        try:
            parse = self.parsers[account.account_type]
        except KeyError:  # a configured account_type with no parser is a wiring error
            raise ValueError(
                f"no parser registered for account_type {account.account_type!r}"
            ) from None

        # 2. Decrypt (in memory) + extract text.
        try:
            pdf = self.reader.read(raw_bytes, password)
        except StatementDecryptionError:
            return IngestResult(
                IngestOutcome.NEEDS_PASSWORD, reason="statement is encrypted — password required"
            )

        # 3. Near-empty extraction (scanned PDF) → OCR/manual review, before parsing garbage.
        extraction = check_extraction(pdf.text)
        if extraction.outcome is ValidationOutcome.NEEDS_MANUAL_REVIEW:
            return IngestResult(IngestOutcome.NEEDS_REVIEW, reason=extraction.reason)

        # 4. Parse. A parser raises (structural / balance) rather than returning bad data.
        try:
            parsed = parse(pdf.text)
        except StatementParseError as exc:
            return IngestResult(IngestOutcome.REJECTED, reason=str(exc))

        # 5. Validation gate (defense in depth; also the soft portfolio-empty route).
        result = validate(parsed)
        if result.outcome is ValidationOutcome.REJECTED:
            return IngestResult(IngestOutcome.REJECTED, reason=result.reason)
        if result.outcome is ValidationOutcome.NEEDS_MANUAL_REVIEW:
            return IngestResult(IngestOutcome.NEEDS_REVIEW, reason=result.reason)

        # 6. Dedup (three layers). A whole-file / whole-content dup contributes no rows.
        dedup_result = dedup(
            raw_bytes=raw_bytes,
            parsed=parsed,
            account_id=account.id,
            statements=self.statements,
            transactions=self.transactions,
        )
        if dedup_result.is_duplicate:
            return IngestResult(IngestOutcome.DUPLICATE, reason=dedup_result.outcome.value)

        # 7. Persist: archive the encrypted original, add the statement, its (categorized)
        #    transactions and any holdings.
        period_start, period_end, closing = _statement_boundaries(parsed)
        due_date, minimum_payment = _bill_summary(parsed)
        encrypted_file_path = self.archive.store(
            raw_bytes=raw_bytes, was_encrypted=pdf.was_encrypted
        )
        statement = self.statements.add(
            Statement(
                account_id=account.id,
                period_start=period_start,
                period_end=period_end,
                file_hash=dedup_result.file_hash,
                content_hash=dedup_result.content_hash,
                uploaded_via=uploaded_via,
                uploaded_at=self.clock(),
                parser_version=parsed.parser_version,
                is_encrypted=pdf.was_encrypted,
                closing_balance=closing,
                due_date=due_date,
                minimum_payment=minimum_payment,
                encrypted_file_path=encrypted_file_path,
                uploaded_by_member_id=uploaded_by_member_id,
            )
        )
        assert statement.id is not None

        new_count = self._persist_transactions(
            dedup_result.new_transactions,
            account_id=account.id,
            statement_id=statement.id,
            household_id=household_id,
        )
        holding_count = self._persist_holdings(
            parsed, account_id=account.id, statement_id=statement.id
        )

        # 8. Recompute the affected net-worth grid points (serialized per household).
        recompute_for_statement(
            household_id=household_id,
            account_id=account.id,
            period_end=period_end,
            accounts=self.accounts,
            statements=self.statements,
            snapshots=self.snapshots,
            lock=self.lock,
        )

        return IngestResult(
            IngestOutcome.INGESTED,
            new_transactions=new_count,
            duplicate_transactions=dedup_result.duplicate_transaction_count,
            holdings=holding_count,
            statement_id=statement.id,
        )

    def _persist_transactions(
        self,
        keyed: list[KeyedTransaction],
        *,
        account_id: int,
        statement_id: int,
        household_id: int,
    ) -> int:
        if not keyed:
            return 0
        # Fetch the categorization inputs once per batch (SPEC §3.3 / categorize note).
        household_accounts = self.accounts.list_by_household(household_id)
        categories = self.categories.list_by_household(household_id)
        active_rules = self.learned_rules.list_active_by_household(household_id)

        hits: dict[int, int] = {}
        for item in keyed:
            txn = item.transaction
            decision = classify(
                txn,
                household_accounts=household_accounts,
                categories=categories,
                active_rules=active_rules,
            )
            self.transactions.add(
                Transaction(
                    statement_id=statement_id,
                    account_id=account_id,
                    date=txn.date,
                    description=txn.description,
                    dedup_key=item.dedup_key,
                    debit=txn.debit,
                    credit=txn.credit,
                    category_id=decision.category_id,
                    category_source=decision.source,
                    counterparty_name=txn.counterparty_name,
                    counterparty_acct=txn.counterparty_acct,
                    raw_ref=txn.raw_ref,
                )
            )
            if decision.matched_rule_id is not None:
                hits[decision.matched_rule_id] = hits.get(decision.matched_rule_id, 0) + 1

        for rule_id, by in hits.items():
            self.learned_rules.bump_hit_count(rule_id, by=by)
        return len(keyed)

    def _persist_holdings(
        self,
        parsed: ParsedStatement | ParsedPortfolio,
        *,
        account_id: int,
        statement_id: int,
    ) -> int:
        if not isinstance(parsed, ParsedPortfolio):
            return 0
        for holding in parsed.holdings:
            self.holdings.add(
                Holding(
                    account_id=account_id,
                    statement_id=statement_id,
                    ticker=holding.ticker,
                    name=holding.name,
                    lot_balance=holding.lot_balance,
                    avg_price=holding.avg_price,
                    market_price=holding.market_price,
                    market_value=holding.market_value,
                    unrealized_pl=holding.unrealized,
                    as_of_date=parsed.as_of,
                )
            )
        return len(parsed.holdings)


def _statement_boundaries(
    parsed: ParsedStatement | ParsedPortfolio,
) -> tuple[datetime.date, datetime.date, Decimal]:
    """(period_start, period_end, closing_balance) for the persisted ``statement``.

    A portfolio snapshot has a single ``as_of`` date and a carry-forward value of Σ
    holdings market value (broker cash excluded — see module docstring / recompute)."""
    if isinstance(parsed, ParsedPortfolio):
        return parsed.as_of, parsed.as_of, parsed.total_market_value()
    return parsed.period_start, parsed.period_end, parsed.closing_balance


def _bill_summary(
    parsed: ParsedStatement | ParsedPortfolio,
) -> tuple[datetime.date | None, Decimal | None]:
    """(due_date, minimum_payment) for the persisted ``statement`` — the credit-card bill
    fields (SPEC §3.4 due-date aggregator). Only a ``ParsedStatement`` carries them, and a
    savings statement leaves them None; a portfolio snapshot has no bill."""
    if isinstance(parsed, ParsedStatement):
        return parsed.due_date, parsed.minimum_payment
    return None, None
