"""S5 — dedup stage (SPEC §4 "Dedup, three layers").

  Layer 1  file hash (SHA-256 of raw bytes)            → exact re-upload rejected outright
  Layer 2  content hash of the parser's content fields → non-byte-identical re-export caught
  Layer 3  transaction ``dedup_key``                   → overlapping periods dedup per row,
                                                          skip-and-log, never fail the batch

The stage is pure: it takes the raw bytes, the parsed result and a resolved
``account_id``, and queries the domain repo Protocols. Tests inject in-memory fakes
(structural typing), so no Postgres is needed here — the repo round-trips are S4's.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from coffer.domain.entities import Statement, Transaction
from coffer.domain.enums import CategorySource, UploadedVia
from coffer.ingestion.dedup import (
    DedupOutcome,
    content_hash,
    dedup,
    file_hash,
    transaction_dedup_key,
)
from coffer.parsers.statement_types import (
    ParsedHolding,
    ParsedPortfolio,
    ParsedStatement,
    ParsedTransaction,
)

D0 = datetime.date(2026, 6, 1)
D1 = datetime.date(2026, 6, 30)


# ── in-memory fakes (satisfy the StatementRepo / TransactionRepo Protocols) ──────
class FakeStatementRepo:
    def __init__(self) -> None:
        self._by_file: dict[str, Statement] = {}
        self._by_content: dict[str, Statement] = {}

    def seed(self, *, fh: str | None = None, ch: str | None = None) -> None:
        stub = Statement(
            account_id=1,
            period_start=D0,
            period_end=D1,
            file_hash=fh or "x" * 64,
            content_hash=ch or "y" * 64,
            uploaded_via=UploadedVia.WEB,
            uploaded_at=datetime.datetime(2026, 7, 1, 12, 0),
            parser_version="test",
            is_encrypted=True,
            id=99,
        )
        if fh is not None:
            self._by_file[fh] = stub
        if ch is not None:
            self._by_content[ch] = stub

    def by_file_hash(self, file_hash: str) -> Statement | None:
        return self._by_file.get(file_hash)

    def by_content_hash(self, content_hash: str) -> Statement | None:
        return self._by_content.get(content_hash)

    # Rest of the StatementRepo Protocol — unused by the dedup stage.
    def add(self, statement: Statement) -> Statement:
        raise NotImplementedError

    def get(self, statement_id: int) -> Statement | None:
        raise NotImplementedError

    def list_by_account(self, account_id: int) -> list[Statement]:
        raise NotImplementedError


class FakeTransactionRepo:
    def __init__(self) -> None:
        self._by_key: dict[str, Transaction] = {}

    def seed(self, key: str) -> None:
        self._by_key[key] = Transaction(
            statement_id=99,
            account_id=1,
            date=D0,
            description="seeded",
            dedup_key=key,
            id=7,
        )

    def by_dedup_key(self, dedup_key: str) -> Transaction | None:
        return self._by_key.get(dedup_key)

    # Rest of the TransactionRepo Protocol — unused by the dedup stage.
    def add(self, transaction: Transaction) -> Transaction:
        raise NotImplementedError

    def get(self, transaction_id: int) -> Transaction | None:
        raise NotImplementedError

    def list_by_account(self, account_id: int) -> list[Transaction]:
        raise NotImplementedError

    def set_category(
        self,
        transaction_id: int,
        *,
        category_id: int,
        source: CategorySource,
        edited_by: int | None,
        edited_at: datetime.datetime,
    ) -> None:
        raise NotImplementedError


def _txn(desc: str, *, debit: str = "0", credit: str = "0", day: int = 5) -> ParsedTransaction:
    d = datetime.date(2026, 6, day)
    return ParsedTransaction(
        date=d,
        posting_date=d,
        description=desc,
        debit=Decimal(debit),
        credit=Decimal(credit),
    )


def _statement(
    *, opening: str = "1000", closing: str = "1500", txns: list[ParsedTransaction] | None = None
) -> ParsedStatement:
    return ParsedStatement(
        institution="bca",
        account_type="bca_savings",
        parser_version="bca_tahapan/1",
        account_number_masked="1234",
        currency="IDR",
        period_start=D0,
        period_end=D1,
        opening_balance=Decimal(opening),
        closing_balance=Decimal(closing),
        transactions=txns if txns is not None else [_txn("gaji", credit="500")],
    )


# ── hash helpers ─────────────────────────────────────────────────────────────--
def test_file_hash_is_stable_sha256_hex() -> None:
    assert file_hash(b"abc") == file_hash(b"abc")
    assert len(file_hash(b"abc")) == 64
    assert file_hash(b"abc") != file_hash(b"abd")


def test_content_hash_ignores_non_content_fields() -> None:
    # Same content-hash fields (acct, period, opening, closing) → same hash, even if
    # the transactions / parser_version differ. This is what catches a re-export.
    a = _statement(txns=[_txn("gaji", credit="500")])
    b = _statement(txns=[_txn("totally different", debit="9")])
    assert content_hash(a) == content_hash(b)


def test_content_hash_changes_when_a_balance_changes() -> None:
    assert content_hash(_statement(closing="1500")) != content_hash(_statement(closing="1600"))


def test_transaction_dedup_key_depends_on_every_component() -> None:
    base = transaction_dedup_key(1, D0, "kopi", Decimal("10"), Decimal("0"))
    assert base == transaction_dedup_key(1, D0, "kopi", Decimal("10"), Decimal("0"))
    assert base != transaction_dedup_key(2, D0, "kopi", Decimal("10"), Decimal("0"))  # account
    assert base != transaction_dedup_key(1, D1, "kopi", Decimal("10"), Decimal("0"))  # date
    assert base != transaction_dedup_key(1, D0, "teh", Decimal("10"), Decimal("0"))  # desc
    assert base != transaction_dedup_key(1, D0, "kopi", Decimal("11"), Decimal("0"))  # debit
    assert base != transaction_dedup_key(1, D0, "kopi", Decimal("10"), Decimal("1"))  # credit


# ── layer 1: file hash ───────────────────────────────────────────────────────--
def test_exact_reupload_rejected_by_file_hash() -> None:
    raw = b"the exact same bytes"
    stmts = FakeStatementRepo()
    stmts.seed(fh=file_hash(raw))
    txns = FakeTransactionRepo()

    result = dedup(
        raw_bytes=raw, parsed=_statement(), account_id=1, statements=stmts, transactions=txns
    )

    assert result.outcome is DedupOutcome.DUPLICATE_FILE
    assert result.is_duplicate
    assert result.new_transactions == []  # a rejected statement contributes no rows


# ── layer 2: content hash ────────────────────────────────────────────────────--
def test_reexport_caught_by_content_hash() -> None:
    parsed = _statement()
    stmts = FakeStatementRepo()
    stmts.seed(ch=content_hash(parsed))  # same content already stored, different bytes
    txns = FakeTransactionRepo()

    result = dedup(
        raw_bytes=b"a fresh re-export",
        parsed=parsed,
        account_id=1,
        statements=stmts,
        transactions=txns,
    )

    assert result.outcome is DedupOutcome.DUPLICATE_CONTENT
    assert result.new_transactions == []


def test_file_hash_takes_precedence_over_content_hash() -> None:
    raw = b"bytes"
    parsed = _statement()
    stmts = FakeStatementRepo()
    stmts.seed(fh=file_hash(raw), ch=content_hash(parsed))
    result = dedup(
        raw_bytes=raw,
        parsed=parsed,
        account_id=1,
        statements=stmts,
        transactions=FakeTransactionRepo(),
    )
    assert result.outcome is DedupOutcome.DUPLICATE_FILE


# ── layer 3: per-transaction dedup on overlapping periods ────────────────────--
def test_new_statement_all_rows_new_and_keyed() -> None:
    parsed = _statement(txns=[_txn("gaji", credit="500", day=3), _txn("kopi", debit="20", day=4)])
    result = dedup(
        raw_bytes=b"new",
        parsed=parsed,
        account_id=1,
        statements=FakeStatementRepo(),
        transactions=FakeTransactionRepo(),
    )
    assert result.outcome is DedupOutcome.NEW
    assert not result.is_duplicate
    assert len(result.new_transactions) == 2
    assert result.duplicate_transaction_count == 0
    # every emitted row carries the key the persist stage will store
    for kt in result.new_transactions:
        assert kt.dedup_key == transaction_dedup_key(
            1,
            kt.transaction.date,
            kt.transaction.description,
            kt.transaction.debit,
            kt.transaction.credit,
        )


def test_overlapping_period_dedups_rows_without_failing_batch() -> None:
    overlap = _txn("gaji", credit="500", day=3)
    fresh = _txn("kopi", debit="20", day=4)
    parsed = _statement(txns=[overlap, fresh])

    txns = FakeTransactionRepo()
    # the overlapping row is already stored from a prior statement covering that period
    txns.seed(
        transaction_dedup_key(1, overlap.date, overlap.description, overlap.debit, overlap.credit)
    )

    result = dedup(
        raw_bytes=b"overlapping",
        parsed=parsed,
        account_id=1,
        statements=FakeStatementRepo(),
        transactions=txns,
    )

    assert result.outcome is DedupOutcome.NEW  # the batch is NOT failed
    assert result.duplicate_transaction_count == 1
    assert [kt.transaction.description for kt in result.new_transactions] == ["kopi"]


def test_identical_rows_within_one_batch_dedup_against_each_other() -> None:
    # The dedup_key column is UNIQUE; two rows with an identical key in one batch would
    # break the persist. The stage keeps the first and counts the rest as duplicates.
    dup = _txn("biaya admin", debit="6500", day=10)
    dup2 = _txn("biaya admin", debit="6500", day=10)
    parsed = _statement(txns=[dup, dup2])
    result = dedup(
        raw_bytes=b"x",
        parsed=parsed,
        account_id=1,
        statements=FakeStatementRepo(),
        transactions=FakeTransactionRepo(),
    )
    assert len(result.new_transactions) == 1
    assert result.duplicate_transaction_count == 1


# ── portfolio path ───────────────────────────────────────────────────────────--
def _portfolio(*, txns: list[ParsedTransaction] | None = None) -> ParsedPortfolio:
    return ParsedPortfolio(
        institution="ajaib",
        account_type="ajaib_portfolio",
        parser_version="ajaib/1",
        account_number_masked="RDN-1",
        currency="IDR",
        as_of=D1,
        holdings=[
            ParsedHolding(
                ticker="AMRT",
                name="Alfaria",
                lot_balance=Decimal("10"),
                share_balance=Decimal("1000"),
                avg_price=Decimal("2500"),
                market_price=Decimal("2600"),
                market_value=Decimal("2600000"),
                unrealized=Decimal("100000"),
            )
        ],
        cash_balance=Decimal("50000"),
        transactions=txns or [],
    )


def test_portfolio_reexport_caught_by_content_hash() -> None:
    pf = _portfolio()
    stmts = FakeStatementRepo()
    stmts.seed(ch=content_hash(pf))
    result = dedup(
        raw_bytes=b"pf",
        parsed=pf,
        account_id=2,
        statements=stmts,
        transactions=FakeTransactionRepo(),
    )
    assert result.outcome is DedupOutcome.DUPLICATE_CONTENT


def test_portfolio_dividend_rows_dedup_per_row() -> None:
    div = _txn("dividen AMRT", credit="12000", day=15)
    pf = _portfolio(txns=[div])
    txns = FakeTransactionRepo()
    txns.seed(transaction_dedup_key(2, div.date, div.description, div.debit, div.credit))
    result = dedup(
        raw_bytes=b"pf2", parsed=pf, account_id=2, statements=FakeStatementRepo(), transactions=txns
    )
    assert result.outcome is DedupOutcome.NEW
    assert result.duplicate_transaction_count == 1
    assert result.new_transactions == []
