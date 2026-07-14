"""S9 — the ingestion use-case wired through the real SQL repos (Postgres).

``test_pipeline.py`` covers the routing/persist logic with in-memory fakes. This proves
the orchestrator drives the *real* ``coffer.persistence`` repos end to end on a real
statement: the CIMB parser runs on the anonymized fixture text, the statement +
transactions persist (Decimal money intact), the net-worth snapshot recomputes onto the
month-end grid, and an exact re-upload is rejected as a duplicate (SPEC §4).

The ``PdfReader`` is faked to return the fixture text (no pdfplumber/PDF); everything
below it — parse, validate, dedup, persist, recompute — is the production path.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from coffer.api.parsing import PARSERS
from coffer.domain.entities import Account, Household, Member
from coffer.domain.enums import AccountType, UploadedVia
from coffer.ingestion.pipeline import DecryptedPdf, IngestOutcome, IngestStatement
from coffer.ingestion.recompute import InProcessRecomputeLock, month_end
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlCategoryRepo,
    SqlHoldingRepo,
    SqlHouseholdRepo,
    SqlLearnedRuleRepo,
    SqlMemberRepo,
    SqlNetworthSnapshotRepo,
    SqlStatementRepo,
    SqlTransactionRepo,
)

_TS = datetime.datetime(2026, 7, 14, 12, 0, tzinfo=datetime.UTC)
_FIXTURE = Path(__file__).parent / "fixtures" / "cimb_mc_gold_2026-03.txt"


class _TextReader:
    """A ``PdfReader`` that returns canned text (stands in for pikepdf+pdfplumber)."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self, raw_bytes: bytes, password: str | None) -> DecryptedPdf:
        return DecryptedPdf(text=self._text, was_encrypted=False)


class _MemArchive:
    def __init__(self) -> None:
        self.count = 0

    def store(self, *, raw_bytes: bytes, was_encrypted: bool) -> str:
        self.count += 1
        return f"mem://{self.count}"


def _use_case(session: Session, text: str) -> IngestStatement:
    return IngestStatement(
        accounts=SqlAccountRepo(session),
        members=SqlMemberRepo(session),
        statements=SqlStatementRepo(session),
        transactions=SqlTransactionRepo(session),
        categories=SqlCategoryRepo(session),
        learned_rules=SqlLearnedRuleRepo(session),
        holdings=SqlHoldingRepo(session),
        snapshots=SqlNetworthSnapshotRepo(session),
        reader=_TextReader(text),
        parsers=PARSERS,
        archive=_MemArchive(),
        lock=InProcessRecomputeLock(),
        clock=lambda: _TS,
    )


def test_cimb_statement_ingests_persists_and_recomputes(session: Session) -> None:
    households = SqlHouseholdRepo(session)
    members = SqlMemberRepo(session)
    accounts = SqlAccountRepo(session)

    hh = households.add(Household(name="Yohanes"))
    assert hh.id is not None
    member = members.add(Member(household_id=hh.id, name="Tommy"))
    assert member.id is not None
    account = accounts.add(
        Account(
            member_id=member.id,
            institution="cimb",
            account_type=AccountType.CIMB_CREDIT_CARD,
            account_number_masked="5481 17XX XXXX 0000",
        )
    )
    assert account.id is not None

    text = _FIXTURE.read_text()
    use_case = _use_case(session, text)

    result = use_case.execute(
        raw_bytes=b"cimb-statement-original-bytes",
        account_id=account.id,
        uploaded_via=UploadedVia.WEB,
    )

    assert result.outcome is IngestOutcome.INGESTED
    assert result.new_transactions == 8
    assert result.duplicate_transactions == 0
    assert result.statement_id is not None

    # statement persisted with the CC liability magnitude as closing_balance (Tagihan Baru).
    stored = SqlStatementRepo(session).get(result.statement_id)
    assert stored is not None
    assert stored.closing_balance == Decimal("838303.83")
    assert stored.period_end == datetime.date(2026, 3, 17)
    assert stored.is_encrypted is False
    assert stored.encrypted_file_path == "mem://1"

    # all 8 line items persisted, keyed for dedup, uncategorized (no rules seeded yet).
    txns = SqlTransactionRepo(session).list_by_account(account.id)
    assert len(txns) == 8
    assert all(t.dedup_key for t in txns)
    assert all(t.category_id is None for t in txns)

    # net-worth snapshot recomputed at the March grid: CC → liability, net is negative.
    grid = month_end(datetime.date(2026, 3, 17))
    snap = SqlNetworthSnapshotRepo(session).by_grid(hh.id, grid)
    assert snap is not None
    assert snap.credit_liability_total == Decimal("838303.83")
    assert snap.cash_total == Decimal("0")
    assert snap.portfolio_total == Decimal("0")
    assert snap.net_worth == Decimal("-838303.83")


def test_exact_reupload_is_duplicate(session: Session) -> None:
    households = SqlHouseholdRepo(session)
    members = SqlMemberRepo(session)
    accounts = SqlAccountRepo(session)

    hh = households.add(Household(name="Yohanes"))
    assert hh.id is not None
    member = members.add(Member(household_id=hh.id, name="Tommy"))
    assert member.id is not None
    account = accounts.add(
        Account(
            member_id=member.id,
            institution="cimb",
            account_type=AccountType.CIMB_CREDIT_CARD,
            account_number_masked="5481 17XX XXXX 0000",
        )
    )
    assert account.id is not None

    text = _FIXTURE.read_text()
    use_case = _use_case(session, text)
    raw = b"identical-original-bytes"

    first = use_case.execute(raw_bytes=raw, account_id=account.id, uploaded_via=UploadedVia.WEB)
    assert first.outcome is IngestOutcome.INGESTED

    again = use_case.execute(raw_bytes=raw, account_id=account.id, uploaded_via=UploadedVia.WEB)
    assert again.outcome is IngestOutcome.DUPLICATE
    # no second statement, no doubled transactions.
    assert len(SqlStatementRepo(session).list_by_account(account.id)) == 1
    assert len(SqlTransactionRepo(session).list_by_account(account.id)) == 8
