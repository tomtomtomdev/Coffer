"""Repository round-trip tests (S4) — one per SPEC §2 aggregate.

Each test proves an entity survives ``add`` → reload byte-exact (Decimal money must
not drift), plus the domain-driven lookups the later slices rely on (dedup hashes,
telegram-id / account-number resolution, active learned rules, snapshot upsert).

The ``institution_credential`` test also proves the secret is **encrypted at rest**
(SPEC §6): the raw column holds ciphertext, and only the repo (via its cipher) yields
the plaintext back.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from coffer.domain.entities import (
    Account,
    Category,
    Holding,
    Household,
    InstitutionCredential,
    LearnedRule,
    Member,
    NetworthSnapshot,
    Override,
    Statement,
    Transaction,
)
from coffer.domain.enums import (
    AccountType,
    Cadence,
    CategorySource,
    CategoryType,
    PasswordScheme,
    UploadedVia,
)
from coffer.persistence.crypto import FieldCipher
from coffer.persistence.models import InstitutionCredentialRow
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlCategoryRepo,
    SqlHoldingRepo,
    SqlHouseholdRepo,
    SqlInstitutionCredentialRepo,
    SqlLearnedRuleRepo,
    SqlMemberRepo,
    SqlNetworthSnapshotRepo,
    SqlOverrideRepo,
    SqlStatementRepo,
    SqlTransactionRepo,
)

_TS = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=datetime.UTC)


def _seed_household(session: Session, name: str = "Yohanes") -> int:
    hh = SqlHouseholdRepo(session).add(Household(name=name))
    assert hh.id is not None
    return hh.id


def _seed_member(session: Session, household_id: int, telegram_user_id: int | None = None) -> int:
    m = SqlMemberRepo(session).add(
        Member(household_id=household_id, name="Tommy", telegram_user_id=telegram_user_id)
    )
    assert m.id is not None
    return m.id


def _seed_account(session: Session, member_id: int, masked: str = "****1234") -> int:
    a = SqlAccountRepo(session).add(
        Account(
            member_id=member_id,
            institution="bca",
            account_type=AccountType.BCA_SAVINGS,
            account_number_masked=masked,
        )
    )
    assert a.id is not None
    return a.id


def _seed_statement(session: Session, account_id: int, file_hash: str = "f" * 64) -> int:
    s = SqlStatementRepo(session).add(
        Statement(
            account_id=account_id,
            period_start=datetime.date(2026, 6, 1),
            period_end=datetime.date(2026, 6, 30),
            file_hash=file_hash,
            content_hash="c" * 40,
            uploaded_via=UploadedVia.WEB,
            uploaded_at=_TS,
            parser_version="bca_tahapan@1",
            is_encrypted=True,
        )
    )
    assert s.id is not None
    return s.id


def _seed_category(session: Session, household_id: int) -> int:
    c = SqlCategoryRepo(session).add(
        Category(
            household_id=household_id,
            match_pattern="GRAB*",
            label="Transport",
            type=CategoryType.ROUTINE,
            cadence=Cadence.MONTHLY,
        )
    )
    assert c.id is not None
    return c.id


def test_household_round_trip(session: Session) -> None:
    repo = SqlHouseholdRepo(session)
    saved = repo.add(Household(name="Yohanes"))
    assert saved.id is not None
    assert repo.get(saved.id) == saved
    assert repo.by_name("Yohanes") == saved
    assert repo.by_name("nobody") is None
    assert repo.get(999_999) is None


def test_member_round_trip_and_lookups(session: Session) -> None:
    hid = _seed_household(session)
    repo = SqlMemberRepo(session)
    tommy = repo.add(Member(household_id=hid, name="Tommy", telegram_user_id=111))
    priskila = repo.add(Member(household_id=hid, name="Priskila", telegram_user_id=222))
    assert tommy.id is not None
    assert repo.get(tommy.id) == tommy
    assert repo.by_telegram_user_id(222) == priskila
    assert repo.by_telegram_user_id(999) is None
    assert repo.list_by_household(hid) == [tommy, priskila]


def test_account_round_trip_and_lookups(session: Session) -> None:
    hid = _seed_household(session)
    mid = _seed_member(session, hid)
    repo = SqlAccountRepo(session)
    acct = repo.add(
        Account(
            member_id=mid,
            institution="bca",
            account_type=AccountType.BCA_SAVINGS,
            account_number_masked="****4958",
        )
    )
    assert acct.id is not None
    got = repo.get(acct.id)
    assert got == acct
    assert got is not None and got.account_type is AccountType.BCA_SAVINGS  # enum, not str
    assert repo.by_number_masked("****4958") == acct
    assert repo.by_number_masked("****0000") is None
    assert repo.list_by_household(hid) == [acct]


def test_credential_is_encrypted_at_rest(session: Session, cipher: FieldCipher) -> None:
    hid = _seed_household(session)
    repo = SqlInstitutionCredentialRepo(session, cipher)
    secret = "cimb-static-password"
    saved = repo.add(
        InstitutionCredential(
            household_id=hid,
            institution="cimb",
            password_scheme=PasswordScheme.STATIC,
            secret=secret,
        )
    )
    assert saved.id is not None

    # The repo returns the plaintext secret back (transparently decrypted).
    assert repo.by_household_institution(hid, "cimb") == saved
    reloaded = repo.get(saved.id)
    assert reloaded is not None and reloaded.secret == secret

    # ...but the raw column holds ciphertext, never the plaintext (SPEC §6).
    row = session.get(InstitutionCredentialRow, saved.id)
    assert row is not None
    assert row.password_enc is not None
    assert row.password_enc != secret
    assert secret not in row.password_enc
    assert cipher.decrypt(row.password_enc) == secret


def test_credential_per_statement_stores_no_secret(session: Session, cipher: FieldCipher) -> None:
    hid = _seed_household(session)
    repo = SqlInstitutionCredentialRepo(session, cipher)
    saved = repo.add(
        InstitutionCredential(
            household_id=hid,
            institution="ajaib",
            password_scheme=PasswordScheme.PER_STATEMENT,
            secret=None,
        )
    )
    assert saved.id is not None
    row = session.get(InstitutionCredentialRow, saved.id)
    assert row is not None and row.password_enc is None
    reloaded = repo.get(saved.id)
    assert reloaded is not None and reloaded.secret is None


def test_statement_round_trip_and_dedup_lookups(session: Session) -> None:
    hid = _seed_household(session)
    mid = _seed_member(session, hid)
    aid = _seed_account(session, mid)
    repo = SqlStatementRepo(session)
    stmt = repo.add(
        Statement(
            account_id=aid,
            period_start=datetime.date(2026, 6, 1),
            period_end=datetime.date(2026, 6, 30),
            file_hash="a" * 64,
            content_hash="b" * 40,
            uploaded_via=UploadedVia.TELEGRAM,
            uploaded_at=_TS,
            parser_version="bca_tahapan@1",
            is_encrypted=True,
            encrypted_file_path="/vault/2026-06.pdf.enc",
            uploaded_by_member_id=mid,
        )
    )
    assert stmt.id is not None
    assert repo.get(stmt.id) == stmt
    assert repo.by_file_hash("a" * 64) == stmt  # dedup layer 1
    assert repo.by_content_hash("b" * 40) == stmt  # dedup layer 2
    assert repo.by_file_hash("z" * 64) is None
    assert repo.list_by_account(aid) == [stmt]


def test_transaction_round_trip_preserves_decimal(session: Session) -> None:
    hid = _seed_household(session)
    mid = _seed_member(session, hid)
    aid = _seed_account(session, mid)
    sid = _seed_statement(session, aid)
    cid = _seed_category(session, hid)
    repo = SqlTransactionRepo(session)
    txn = repo.add(
        Transaction(
            statement_id=sid,
            account_id=aid,
            date=datetime.date(2026, 6, 15),
            description="TRSF E-BANKING CR",
            dedup_key="dedup-abc",
            debit=Decimal("0"),
            credit=Decimal("838303.83"),
            balance=Decimal("1271334.69"),
            category_id=cid,
            category_source=CategorySource.PARSER,
            counterparty_name="PRISKILA",
            counterparty_acct="1234567890",
            raw_ref="raw line",
        )
    )
    assert txn.id is not None
    got = repo.get(txn.id)
    assert got == txn
    # Decimal value round-trips exactly — no binary-float drift.
    assert got is not None and got.credit == Decimal("838303.83")
    assert isinstance(got.credit, Decimal)
    assert got.category_source is CategorySource.PARSER
    assert repo.by_dedup_key("dedup-abc") == txn  # dedup layer 3
    assert repo.by_dedup_key("missing") is None
    assert repo.list_by_account(aid) == [txn]


def test_category_round_trip_and_list(session: Session) -> None:
    hid = _seed_household(session)
    repo = SqlCategoryRepo(session)
    cat = repo.add(
        Category(
            household_id=hid,
            match_pattern="QR.*INDOMA",
            label="Groceries",
            type=CategoryType.ROUTINE,
            cadence=Cadence.MONTHLY,
        )
    )
    assert cat.id is not None
    got = repo.get(cat.id)
    assert got == cat
    assert got is not None and got.type is CategoryType.ROUTINE and got.cadence is Cadence.MONTHLY
    assert repo.list_by_household(hid) == [cat]


def test_override_round_trip(session: Session) -> None:
    hid = _seed_household(session)
    mid = _seed_member(session, hid)
    aid = _seed_account(session, mid)
    sid = _seed_statement(session, aid)
    cid = _seed_category(session, hid)
    txn = SqlTransactionRepo(session).add(
        Transaction(
            statement_id=sid,
            account_id=aid,
            date=datetime.date(2026, 6, 15),
            description="x",
            dedup_key="k1",
            debit=Decimal("50000"),
        )
    )
    assert txn.id is not None
    repo = SqlOverrideRepo(session)
    ov = repo.add(Override(transaction_id=txn.id, category_id=cid, member_id=mid, created_at=_TS))
    assert ov.id is not None
    assert repo.list_by_transaction(txn.id) == [ov]


def test_learned_rule_round_trip_and_active_filter(session: Session) -> None:
    hid = _seed_household(session)
    cid = _seed_category(session, hid)
    repo = SqlLearnedRuleRepo(session)
    active = repo.add(
        LearnedRule(
            household_id=hid,
            category_id=cid,
            created_at=_TS,
            match_counterparty_acct="1234567890",
            match_amount=Decimal("2177067.00"),
            match_amount_tolerance=Decimal("0.00"),
            active=True,
            hit_count=3,
        )
    )
    inactive = repo.add(
        LearnedRule(household_id=hid, category_id=cid, created_at=_TS, active=False)
    )
    assert active.id is not None
    assert repo.get(active.id) == active
    assert active.match_amount == Decimal("2177067.00")
    # Only active rules are applied on ingest (SPEC §3.3).
    listed = repo.list_active_by_household(hid)
    assert active in listed
    assert inactive not in listed


def test_holding_round_trip_preserves_fractional_price(session: Session) -> None:
    hid = _seed_household(session)
    mid = _seed_member(session, hid)
    aid = _seed_account(session, mid, masked="****4996")
    sid = _seed_statement(session, aid, file_hash="h" * 64)
    repo = SqlHoldingRepo(session)
    holding = repo.add(
        Holding(
            account_id=aid,
            statement_id=sid,
            ticker="AMRT",
            name="SUMBER ALFARIA TRIJAYA Tbk",
            lot_balance=Decimal("120"),
            avg_price=Decimal("2543.7500"),
            market_price=Decimal("2900"),
            market_value=Decimal("34800000.00"),
            unrealized_pl=Decimal("4275000.00"),
            as_of_date=datetime.date(2026, 6, 30),
        )
    )
    assert holding.id is not None
    listed = repo.list_by_statement(sid)
    assert listed == [holding]
    assert listed[0].avg_price == Decimal("2543.7500")  # fractional cost preserved


def test_snapshot_upsert_is_idempotent_on_grid(session: Session) -> None:
    hid = _seed_household(session)
    repo = SqlNetworthSnapshotRepo(session)
    grid = datetime.date(2026, 6, 30)
    first = repo.upsert(
        NetworthSnapshot(
            household_id=hid,
            grid_date=grid,
            cash_total=Decimal("1000000.00"),
            credit_liability_total=Decimal("200000.00"),
            portfolio_total=Decimal("5000000.00"),
            net_worth=Decimal("5800000.00"),
        )
    )
    assert first.id is not None
    # Re-computing the same grid point replaces in place — no duplicate row (§3.1).
    second = repo.upsert(
        NetworthSnapshot(
            household_id=hid,
            grid_date=grid,
            cash_total=Decimal("1111111.00"),
            credit_liability_total=Decimal("200000.00"),
            portfolio_total=Decimal("5000000.00"),
            net_worth=Decimal("5911111.00"),
        )
    )
    assert second.id == first.id
    assert repo.list_by_household(hid) == [second]
    got = repo.by_grid(hid, grid)
    assert got is not None and got.cash_total == Decimal("1111111.00")
    assert repo.by_grid(hid, datetime.date(2026, 5, 31)) is None
