"""S9 — ingestion orchestration use-case (``coffer.ingestion.pipeline``).

Unit tests over pure in-memory fakes for the domain repo Protocols + the injected
infra ports (``PdfReader`` / ``StatementArchive`` / recompute lock / clock). No real
PDF, no pdfplumber, no Postgres — the concrete adapters are wired + exercised in the
api-layer / integration tests. Here we pin the *routing decisions* and the persist +
categorize + recompute wiring the orchestrator owns (SPEC §4 pipeline).
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from decimal import Decimal

from coffer.domain.entities import (
    Account,
    Category,
    Holding,
    LearnedRule,
    Member,
    NetworthSnapshot,
    Statement,
    Transaction,
)
from coffer.domain.enums import (
    AccountType,
    CategorySource,
    CategoryType,
    UploadedVia,
)
from coffer.ingestion.decrypt import StatementDecryptionError
from coffer.ingestion.dedup import transaction_dedup_key
from coffer.ingestion.pipeline import (
    DecryptedPdf,
    IngestOutcome,
    IngestResult,
    IngestStatement,
    ParserRegistry,
    StatementParser,
)
from coffer.ingestion.recompute import InProcessRecomputeLock
from coffer.parsers.statement_types import (
    ParsedHolding,
    ParsedPortfolio,
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
)

NOW = datetime.datetime(2026, 7, 14, 12, 0, tzinfo=datetime.UTC)
JUN = datetime.date(2026, 6, 30)


# ── in-memory fakes for the domain repo Protocols ────────────────────────────────────
def _seq() -> _Counter:
    return _Counter()


class _Counter:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> int:
        self.n += 1
        return self.n


class _FakeMemberRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, Member] = {}
        self._c = _seq()

    def add(self, member: Member) -> Member:
        m = replace(member, id=self._c.next())
        assert m.id is not None
        self._by_id[m.id] = m
        return m

    def get(self, member_id: int) -> Member | None:
        return self._by_id.get(member_id)

    def by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        return next(
            (m for m in self._by_id.values() if m.telegram_user_id == telegram_user_id), None
        )

    def list_by_household(self, household_id: int) -> list[Member]:
        return [m for m in self._by_id.values() if m.household_id == household_id]


class _FakeAccountRepo:
    def __init__(self, members: _FakeMemberRepo) -> None:
        self._members = members
        self._by_id: dict[int, Account] = {}
        self._c = _seq()

    def add(self, account: Account) -> Account:
        a = replace(account, id=self._c.next())
        assert a.id is not None
        self._by_id[a.id] = a
        return a

    def get(self, account_id: int) -> Account | None:
        return self._by_id.get(account_id)

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        return next(
            (a for a in self._by_id.values() if a.account_number_masked == account_number_masked),
            None,
        )

    def list_by_household(self, household_id: int) -> list[Account]:
        out = []
        for a in self._by_id.values():
            m = self._members.get(a.member_id)
            if m is not None and m.household_id == household_id:
                out.append(a)
        return out


class _FakeStatementRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, Statement] = {}
        self._c = _seq()

    def add(self, statement: Statement) -> Statement:
        s = replace(statement, id=self._c.next())
        assert s.id is not None
        self._by_id[s.id] = s
        return s

    def get(self, statement_id: int) -> Statement | None:
        return self._by_id.get(statement_id)

    def by_file_hash(self, file_hash: str) -> Statement | None:
        return next((s for s in self._by_id.values() if s.file_hash == file_hash), None)

    def by_content_hash(self, content_hash: str) -> Statement | None:
        return next((s for s in self._by_id.values() if s.content_hash == content_hash), None)

    def list_by_account(self, account_id: int) -> list[Statement]:
        rows = [s for s in self._by_id.values() if s.account_id == account_id]
        return sorted(rows, key=lambda s: s.period_end)


class _FakeTransactionRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, Transaction] = {}
        self._c = _seq()

    def add(self, transaction: Transaction) -> Transaction:
        t = replace(transaction, id=self._c.next())
        assert t.id is not None
        self._by_id[t.id] = t
        return t

    def get(self, transaction_id: int) -> Transaction | None:
        return self._by_id.get(transaction_id)

    def by_dedup_key(self, dedup_key: str) -> Transaction | None:
        return next((t for t in self._by_id.values() if t.dedup_key == dedup_key), None)

    def list_by_account(self, account_id: int) -> list[Transaction]:
        return [t for t in self._by_id.values() if t.account_id == account_id]

    def set_category(
        self,
        transaction_id: int,
        *,
        category_id: int,
        source: CategorySource,
        edited_by: int | None,
        edited_at: datetime.datetime,
    ) -> None:
        t = self._by_id[transaction_id]
        self._by_id[transaction_id] = replace(
            t,
            category_id=category_id,
            category_source=source,
            edited_by=edited_by,
            edited_at=edited_at,
        )


class _FakeCategoryRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, Category] = {}
        self._c = _seq()

    def add(self, category: Category) -> Category:
        cat = replace(category, id=self._c.next())
        assert cat.id is not None
        self._by_id[cat.id] = cat
        return cat

    def get(self, category_id: int) -> Category | None:
        return self._by_id.get(category_id)

    def list_by_household(self, household_id: int) -> list[Category]:
        return [c for c in self._by_id.values() if c.household_id == household_id]


class _FakeLearnedRuleRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, LearnedRule] = {}
        self._c = _seq()

    def add(self, rule: LearnedRule) -> LearnedRule:
        r = replace(rule, id=self._c.next())
        assert r.id is not None
        self._by_id[r.id] = r
        return r

    def get(self, rule_id: int) -> LearnedRule | None:
        return self._by_id.get(rule_id)

    def list_active_by_household(self, household_id: int) -> list[LearnedRule]:
        return [r for r in self._by_id.values() if r.household_id == household_id and r.active]

    def bump_hit_count(self, rule_id: int, *, by: int = 1) -> None:
        r = self._by_id[rule_id]
        self._by_id[rule_id] = replace(r, hit_count=r.hit_count + by)

    def set_active(self, rule_id: int, *, active: bool) -> None:
        self._by_id[rule_id] = replace(self._by_id[rule_id], active=active)


class _FakeHoldingRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, Holding] = {}
        self._c = _seq()

    def add(self, holding: Holding) -> Holding:
        h = replace(holding, id=self._c.next())
        assert h.id is not None
        self._by_id[h.id] = h
        return h

    def list_by_statement(self, statement_id: int) -> list[Holding]:
        return [h for h in self._by_id.values() if h.statement_id == statement_id]


class _FakeSnapshotRepo:
    def __init__(self) -> None:
        self._by_key: dict[tuple[int, datetime.date], NetworthSnapshot] = {}
        self._c = _seq()

    def upsert(self, snapshot: NetworthSnapshot) -> NetworthSnapshot:
        key = (snapshot.household_id, snapshot.grid_date)
        existing = self._by_key.get(key)
        stored = replace(snapshot, id=existing.id if existing else self._c.next())
        self._by_key[key] = stored
        return stored

    def by_grid(self, household_id: int, grid_date: datetime.date) -> NetworthSnapshot | None:
        return self._by_key.get((household_id, grid_date))

    def list_by_household(self, household_id: int) -> list[NetworthSnapshot]:
        rows = [s for s in self._by_key.values() if s.household_id == household_id]
        return sorted(rows, key=lambda s: s.grid_date)


class _FakeReader:
    """Stands in for the pikepdf/pdfplumber adapter."""

    def __init__(
        self, text: str = "x" * 200, *, was_encrypted: bool = False, fail: bool = False
    ) -> None:
        self._text = text
        self._was_encrypted = was_encrypted
        self._fail = fail

    def read(self, raw_bytes: bytes, password: str | None) -> DecryptedPdf:
        if self._fail:
            raise StatementDecryptionError("wrong or missing password")
        return DecryptedPdf(text=self._text, was_encrypted=self._was_encrypted)


class _FakeArchive:
    def __init__(self) -> None:
        self.stored: list[tuple[bytes, bool]] = []

    def store(self, *, raw_bytes: bytes, was_encrypted: bool) -> str:
        self.stored.append((raw_bytes, was_encrypted))
        return f"mem://{len(self.stored)}"


class _Ctx:
    """A wired household + use-case for a test, so cases stay terse."""

    def __init__(
        self,
        *,
        parsers: ParserRegistry,
        reader: _FakeReader | None = None,
        account_type: AccountType = AccountType.BCA_SAVINGS,
    ) -> None:
        self.members = _FakeMemberRepo()
        self.accounts = _FakeAccountRepo(self.members)
        self.statements = _FakeStatementRepo()
        self.transactions = _FakeTransactionRepo()
        self.categories = _FakeCategoryRepo()
        self.learned_rules = _FakeLearnedRuleRepo()
        self.holdings = _FakeHoldingRepo()
        self.snapshots = _FakeSnapshotRepo()
        self.archive = _FakeArchive()
        self.reader = reader or _FakeReader()

        member = self.members.add(Member(household_id=1, name="Tommy"))
        assert member.id is not None
        self.member_id = member.id
        acct = self.accounts.add(
            Account(
                member_id=member.id,
                institution="bca",
                account_type=account_type,
                account_number_masked="****1000",
            )
        )
        assert acct.id is not None
        self.account_id = acct.id

        self.uc = IngestStatement(
            accounts=self.accounts,
            members=self.members,
            statements=self.statements,
            transactions=self.transactions,
            categories=self.categories,
            learned_rules=self.learned_rules,
            holdings=self.holdings,
            snapshots=self.snapshots,
            reader=self.reader,
            parsers=parsers,
            archive=self.archive,
            lock=InProcessRecomputeLock(),
            clock=lambda: NOW,
        )

    def execute(
        self, *, account_id: int | None = None, password: str | None = None
    ) -> IngestResult:
        return self.uc.execute(
            raw_bytes=b"%PDF-fake",
            account_id=self.account_id if account_id is None else account_id,
            uploaded_via=UploadedVia.WEB,
            password=password,
        )


def _txn(
    description: str, debit: str, *, counterparty_acct: str | None = None
) -> ParsedTransaction:
    return ParsedTransaction(
        date=datetime.date(2026, 6, 15),
        posting_date=datetime.date(2026, 6, 15),
        description=description,
        debit=Decimal(debit),
        credit=Decimal("0"),
        counterparty_acct=counterparty_acct,
    )


def _savings(
    transactions: list[ParsedTransaction], *, opening: str, closing: str
) -> ParsedStatement:
    return ParsedStatement(
        institution="bca",
        account_type="bca_savings",
        parser_version="bca_tahapan/1.0.0",
        account_number_masked="****1000",
        currency="IDR",
        period_start=datetime.date(2026, 6, 1),
        period_end=JUN,
        opening_balance=Decimal(opening),
        closing_balance=Decimal(closing),
        transactions=transactions,
    )


def _registry(parse: StatementParser) -> dict[AccountType, StatementParser]:
    return {AccountType.BCA_SAVINGS: parse}


# ── routing decisions ────────────────────────────────────────────────────────────────
def test_encrypted_without_password_needs_password() -> None:
    ctx = _Ctx(
        parsers=_registry(lambda t: _savings([], opening="0", closing="0")),
        reader=_FakeReader(fail=True),
    )
    result = ctx.execute()
    assert result.outcome is IngestOutcome.NEEDS_PASSWORD


def test_unknown_account_needs_account() -> None:
    ctx = _Ctx(parsers=_registry(lambda t: _savings([], opening="0", closing="0")))
    result = ctx.execute(account_id=999)  # no such account
    assert result.outcome is IngestOutcome.NEEDS_ACCOUNT


def test_near_empty_extraction_needs_review() -> None:
    ctx = _Ctx(
        parsers=_registry(lambda t: _savings([], opening="0", closing="0")),
        reader=_FakeReader(text="   "),  # below MIN_EXTRACTED_CHARS
    )
    result = ctx.execute()
    assert result.outcome is IngestOutcome.NEEDS_REVIEW
    assert result.alert is False  # a manual-review route is not an alert


def test_parser_raise_is_rejected_and_alerts() -> None:
    def _raise(text: str) -> ParsedStatement:
        raise StatementParseError("layout mismatch")

    ctx = _Ctx(parsers=_registry(_raise))
    result = ctx.execute()
    assert result.outcome is IngestOutcome.REJECTED
    assert result.alert is True


def test_balance_discontinuity_rejected_and_alerts() -> None:
    # opening 100 with a 50 debit should close at 50; claim 999 → validate REJECTs.
    stmt = _savings([_txn("X", "50")], opening="100", closing="999")
    ctx = _Ctx(parsers=_registry(lambda t: stmt))
    result = ctx.execute()
    assert result.outcome is IngestOutcome.REJECTED
    assert result.alert is True


def test_exact_reupload_is_duplicate() -> None:
    stmt = _savings([_txn("X", "50")], opening="100", closing="50")
    ctx = _Ctx(parsers=_registry(lambda t: stmt))
    first = ctx.execute()
    assert first.outcome is IngestOutcome.INGESTED
    again = ctx.execute()  # same bytes → file-hash duplicate
    assert again.outcome is IngestOutcome.DUPLICATE


# ── the happy path: persist + categorize + dedup + recompute ─────────────────────────
def test_ingested_persists_categorizes_dedups_and_recomputes() -> None:
    ctx = _Ctx(parsers={})  # parser injected below once ids are known
    # Seed categories (regex) + a learned rule (recipient-acct key).
    transport = ctx.categories.add(
        Category(
            household_id=1,
            match_pattern=r"GRAB|GOJEK",
            label="Transportasi",
            type=CategoryType.ROUTINE,
        )
    )
    family = ctx.categories.add(
        Category(
            household_id=1,
            match_pattern=r"@family",
            label="Kirim Keluarga",
            type=CategoryType.TRANSFER,
        )
    )
    assert transport.id is not None and family.id is not None
    rule = ctx.learned_rules.add(
        LearnedRule(
            household_id=1, category_id=family.id, created_at=NOW, match_counterparty_acct="999"
        )
    )
    assert rule.id is not None

    # Pre-seed an already-stored transaction so its row dedups out of the batch.
    prev_key = transaction_dedup_key(
        ctx.account_id, datetime.date(2026, 6, 15), "OLD PAYMENT", Decimal("10000"), Decimal("0")
    )
    ctx.transactions.add(
        Transaction(
            statement_id=0,
            account_id=ctx.account_id,
            date=datetime.date(2026, 6, 15),
            description="OLD PAYMENT",
            dedup_key=prev_key,
            debit=Decimal("10000"),
        )
    )

    rows = [
        _txn("GRAB RIDE HOME", "50000"),  # regex → Transportasi
        _txn("TRSF E-BANKING", "100000", counterparty_acct="999"),  # learned rule → family
        _txn("MYSTERY MERCHANT", "25000"),  # uncategorized
        _txn("OLD PAYMENT", "10000"),  # duplicate of the pre-seeded row
    ]
    # opening − Σdebits = closing : 1_000_000 − 185_000 = 815_000
    stmt = _savings(rows, opening="1000000", closing="815000")

    ctx.uc.parsers = {AccountType.BCA_SAVINGS: lambda t: stmt}

    result = ctx.execute()

    assert result.outcome is IngestOutcome.INGESTED
    assert result.new_transactions == 3
    assert result.duplicate_transactions == 1
    assert result.statement_id is not None

    # statement persisted with the carry-forward closing balance + archive path.
    stored = ctx.statements.get(result.statement_id)
    assert stored is not None
    assert stored.closing_balance == Decimal("815000")
    assert stored.period_end == JUN
    assert stored.encrypted_file_path is not None
    assert ctx.archive.stored  # the encrypted original was archived

    # categorization was applied per row.
    grab = ctx.transactions.by_dedup_key(
        transaction_dedup_key(
            ctx.account_id,
            datetime.date(2026, 6, 15),
            "GRAB RIDE HOME",
            Decimal("50000"),
            Decimal("0"),
        )
    )
    assert grab is not None and grab.category_id == transport.id
    assert grab.category_source is CategorySource.PARSER

    trsf = ctx.transactions.by_dedup_key(
        transaction_dedup_key(
            ctx.account_id,
            datetime.date(2026, 6, 15),
            "TRSF E-BANKING",
            Decimal("100000"),
            Decimal("0"),
        )
    )
    assert trsf is not None and trsf.category_id == family.id
    assert trsf.category_source is CategorySource.LEARNED_RULE

    mystery = ctx.transactions.by_dedup_key(
        transaction_dedup_key(
            ctx.account_id,
            datetime.date(2026, 6, 15),
            "MYSTERY MERCHANT",
            Decimal("25000"),
            Decimal("0"),
        )
    )
    assert mystery is not None and mystery.category_id is None

    # the learned rule that fired had its hit_count bumped (SPEC §3.3).
    bumped = ctx.learned_rules.get(rule.id)
    assert bumped is not None and bumped.hit_count == 1

    # net-worth snapshot recomputed at the June grid: savings → cash.
    snap = ctx.snapshots.by_grid(1, JUN)
    assert snap is not None
    assert snap.cash_total == Decimal("815000")
    assert snap.net_worth == Decimal("815000")


def test_portfolio_persists_holdings_and_excludes_broker_cash() -> None:
    portfolio = ParsedPortfolio(
        institution="ajaib",
        account_type="ajaib_portfolio",
        parser_version="ajaib_portfolio/1.0.0",
        account_number_masked="****3000",
        currency="IDR",
        as_of=JUN,
        holdings=[
            ParsedHolding(
                "AMRT",
                "Alfaria",
                Decimal("10"),
                Decimal("1000"),
                Decimal("2500"),
                Decimal("3000"),
                Decimal("3000000"),
                Decimal("500000"),
            ),
            ParsedHolding(
                "BBCA",
                "BCA",
                Decimal("5"),
                Decimal("500"),
                Decimal("9000"),
                Decimal("9500"),
                Decimal("4750000"),
                Decimal("250000"),
            ),
        ],
        cash_balance=Decimal("1234567"),  # broker cash — must NOT enter closing_balance
    )
    ctx = _Ctx(
        parsers={AccountType.AJAIB_PORTFOLIO: lambda t: portfolio},
        account_type=AccountType.AJAIB_PORTFOLIO,
    )
    result = ctx.execute()

    assert result.outcome is IngestOutcome.INGESTED
    assert result.holdings == 2
    assert result.new_transactions == 0

    stored = ctx.statements.get(result.statement_id or -1)
    assert stored is not None
    # closing_balance = Σ market value only (RDN/broker cash counted once on the bank side).
    assert stored.closing_balance == Decimal("7750000")
    assert stored.period_start == JUN and stored.period_end == JUN
    assert len(ctx.holdings.list_by_statement(stored.id or -1)) == 2

    snap = ctx.snapshots.by_grid(1, JUN)
    assert snap is not None
    assert snap.portfolio_total == Decimal("7750000")
    assert snap.cash_total == Decimal("0")
    assert snap.net_worth == Decimal("7750000")
