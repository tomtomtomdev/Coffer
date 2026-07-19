"""SQLAlchemy-backed implementations of the domain repository interfaces.

Each repo holds a ``Session`` and translates at the boundary via ``mappers`` — no
ORM row escapes into the domain. ``add`` flushes so the DB-assigned ``id`` is
available on the returned entity (the caller stays inside the surrounding
transaction; commit is the unit-of-work's job, per the skill).

These classes structurally satisfy the Protocols in ``coffer.domain.repositories``.
"""

from __future__ import annotations

import datetime

from sqlalchemy import select, update
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
from coffer.domain.enums import CategorySource
from coffer.persistence import mappers
from coffer.persistence.crypto import FieldCipher
from coffer.persistence.models import (
    AccountRow,
    CategoryRow,
    HoldingRow,
    HouseholdRow,
    InstitutionCredentialRow,
    LearnedRuleRow,
    MemberRow,
    NetworthSnapshotRow,
    OverrideRow,
    StatementRow,
    TransactionRow,
)


class SqlHouseholdRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, household: Household) -> Household:
        row = mappers.household_to_row(household)
        self._session.add(row)
        self._session.flush()
        return mappers.household_to_domain(row)

    def get(self, household_id: int) -> Household | None:
        row = self._session.get(HouseholdRow, household_id)
        return mappers.household_to_domain(row) if row else None

    def by_name(self, name: str) -> Household | None:
        row = self._session.scalar(select(HouseholdRow).where(HouseholdRow.name == name))
        return mappers.household_to_domain(row) if row else None


class SqlMemberRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, member: Member) -> Member:
        row = mappers.member_to_row(member)
        self._session.add(row)
        self._session.flush()
        return mappers.member_to_domain(row)

    def get(self, member_id: int) -> Member | None:
        row = self._session.get(MemberRow, member_id)
        return mappers.member_to_domain(row) if row else None

    def by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        row = self._session.scalar(
            select(MemberRow).where(MemberRow.telegram_user_id == telegram_user_id)
        )
        return mappers.member_to_domain(row) if row else None

    def list_by_household(self, household_id: int) -> list[Member]:
        rows = self._session.scalars(
            select(MemberRow).where(MemberRow.household_id == household_id).order_by(MemberRow.id)
        )
        return [mappers.member_to_domain(r) for r in rows]


class SqlAccountRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, account: Account) -> Account:
        row = mappers.account_to_row(account)
        self._session.add(row)
        self._session.flush()
        return mappers.account_to_domain(row)

    def get(self, account_id: int) -> Account | None:
        row = self._session.get(AccountRow, account_id)
        return mappers.account_to_domain(row) if row else None

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        row = self._session.scalar(
            select(AccountRow).where(AccountRow.account_number_masked == account_number_masked)
        )
        return mappers.account_to_domain(row) if row else None

    def list_by_household(self, household_id: int) -> list[Account]:
        rows = self._session.scalars(
            select(AccountRow)
            .join(MemberRow, AccountRow.member_id == MemberRow.id)
            .where(MemberRow.household_id == household_id)
            .order_by(AccountRow.id)
        )
        return [mappers.account_to_domain(r) for r in rows]


class SqlInstitutionCredentialRepo:
    """The credential repo carries a ``FieldCipher`` — it is the only repo that
    touches encryption at rest (SPEC §6)."""

    def __init__(self, session: Session, cipher: FieldCipher) -> None:
        self._session = session
        self._cipher = cipher

    def add(self, credential: InstitutionCredential) -> InstitutionCredential:
        row = mappers.credential_to_row(credential, self._cipher)
        self._session.add(row)
        self._session.flush()
        return mappers.credential_to_domain(row, self._cipher)

    def get(self, credential_id: int) -> InstitutionCredential | None:
        row = self._session.get(InstitutionCredentialRow, credential_id)
        return mappers.credential_to_domain(row, self._cipher) if row else None

    def by_household_institution(
        self, household_id: int, institution: str
    ) -> InstitutionCredential | None:
        row = self._session.scalar(
            select(InstitutionCredentialRow).where(
                InstitutionCredentialRow.household_id == household_id,
                InstitutionCredentialRow.institution == institution,
            )
        )
        return mappers.credential_to_domain(row, self._cipher) if row else None

    def delete(self, credential_id: int) -> None:
        """Remove a credential row. Used by the seed CLI's ``--replace`` path: there is
        no DB unique constraint on ``(household, institution)`` to upsert against, so a
        replace is delete-then-add. A no-op if the id is already gone."""
        row = self._session.get(InstitutionCredentialRow, credential_id)
        if row is not None:
            self._session.delete(row)
            self._session.flush()


class SqlStatementRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, statement: Statement) -> Statement:
        row = mappers.statement_to_row(statement)
        self._session.add(row)
        self._session.flush()
        return mappers.statement_to_domain(row)

    def get(self, statement_id: int) -> Statement | None:
        row = self._session.get(StatementRow, statement_id)
        return mappers.statement_to_domain(row) if row else None

    def by_file_hash(self, file_hash: str) -> Statement | None:
        row = self._session.scalar(select(StatementRow).where(StatementRow.file_hash == file_hash))
        return mappers.statement_to_domain(row) if row else None

    def by_content_hash(self, content_hash: str) -> Statement | None:
        row = self._session.scalar(
            select(StatementRow).where(StatementRow.content_hash == content_hash)
        )
        return mappers.statement_to_domain(row) if row else None

    def list_by_account(self, account_id: int) -> list[Statement]:
        rows = self._session.scalars(
            select(StatementRow)
            .where(StatementRow.account_id == account_id)
            .order_by(StatementRow.period_end)
        )
        return [mappers.statement_to_domain(r) for r in rows]


class SqlTransactionRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, transaction: Transaction) -> Transaction:
        row = mappers.transaction_to_row(transaction)
        self._session.add(row)
        self._session.flush()
        return mappers.transaction_to_domain(row)

    def get(self, transaction_id: int) -> Transaction | None:
        row = self._session.get(TransactionRow, transaction_id)
        return mappers.transaction_to_domain(row) if row else None

    def by_dedup_key(self, dedup_key: str) -> Transaction | None:
        row = self._session.scalar(
            select(TransactionRow).where(TransactionRow.dedup_key == dedup_key)
        )
        return mappers.transaction_to_domain(row) if row else None

    def list_by_account(self, account_id: int) -> list[Transaction]:
        rows = self._session.scalars(
            select(TransactionRow)
            .where(TransactionRow.account_id == account_id)
            .order_by(TransactionRow.date, TransactionRow.id)
        )
        return [mappers.transaction_to_domain(r) for r in rows]

    def set_category(
        self,
        transaction_id: int,
        *,
        category_id: int,
        source: CategorySource,
        edited_by: int | None,
        edited_at: datetime.datetime,
    ) -> None:
        """Apply a manual re-tag (SPEC §3.3): set the category + its provenance and stamp
        the edit audit. ``source`` is stored as its string value (models keep enums as text)."""
        self._session.execute(
            update(TransactionRow)
            .where(TransactionRow.id == transaction_id)
            .values(
                category_id=category_id,
                category_source=source.value,
                edited_by=edited_by,
                edited_at=edited_at,
            )
        )


class SqlCategoryRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, category: Category) -> Category:
        row = mappers.category_to_row(category)
        self._session.add(row)
        self._session.flush()
        return mappers.category_to_domain(row)

    def get(self, category_id: int) -> Category | None:
        row = self._session.get(CategoryRow, category_id)
        return mappers.category_to_domain(row) if row else None

    def list_by_household(self, household_id: int) -> list[Category]:
        rows = self._session.scalars(
            select(CategoryRow)
            .where(CategoryRow.household_id == household_id)
            .order_by(CategoryRow.id)
        )
        return [mappers.category_to_domain(r) for r in rows]


class SqlOverrideRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, override: Override) -> Override:
        row = mappers.override_to_row(override)
        self._session.add(row)
        self._session.flush()
        return mappers.override_to_domain(row)

    def list_by_transaction(self, transaction_id: int) -> list[Override]:
        rows = self._session.scalars(
            select(OverrideRow)
            .where(OverrideRow.transaction_id == transaction_id)
            .order_by(OverrideRow.created_at, OverrideRow.id)
        )
        return [mappers.override_to_domain(r) for r in rows]


class SqlLearnedRuleRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, rule: LearnedRule) -> LearnedRule:
        row = mappers.learned_rule_to_row(rule)
        self._session.add(row)
        self._session.flush()
        return mappers.learned_rule_to_domain(row)

    def get(self, rule_id: int) -> LearnedRule | None:
        row = self._session.get(LearnedRuleRow, rule_id)
        return mappers.learned_rule_to_domain(row) if row else None

    def list_active_by_household(self, household_id: int) -> list[LearnedRule]:
        rows = self._session.scalars(
            select(LearnedRuleRow)
            .where(
                LearnedRuleRow.household_id == household_id,
                LearnedRuleRow.active.is_(True),
            )
            .order_by(LearnedRuleRow.id)
        )
        return [mappers.learned_rule_to_domain(r) for r in rows]

    def bump_hit_count(self, rule_id: int, *, by: int = 1) -> None:
        """Atomic increment (``hit_count = hit_count + by``) so concurrent ingests
        that both fire the same rule don't clobber each other's count."""
        self._session.execute(
            update(LearnedRuleRow)
            .where(LearnedRuleRow.id == rule_id)
            .values(hit_count=LearnedRuleRow.hit_count + by)
        )

    def set_active(self, rule_id: int, *, active: bool) -> None:
        """Activate/deactivate a rule — a re-tag deactivates the rule that mis-fired (§3.3)."""
        self._session.execute(
            update(LearnedRuleRow).where(LearnedRuleRow.id == rule_id).values(active=active)
        )


class SqlHoldingRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, holding: Holding) -> Holding:
        row = mappers.holding_to_row(holding)
        self._session.add(row)
        self._session.flush()
        return mappers.holding_to_domain(row)

    def list_by_statement(self, statement_id: int) -> list[Holding]:
        rows = self._session.scalars(
            select(HoldingRow)
            .where(HoldingRow.statement_id == statement_id)
            .order_by(HoldingRow.ticker)
        )
        return [mappers.holding_to_domain(r) for r in rows]


class SqlNetworthSnapshotRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, snapshot: NetworthSnapshot) -> NetworthSnapshot:
        """Insert or replace the snapshot for ``(household_id, grid_date)`` (§3.1
        recompute is idempotent on the grid key)."""
        row = self._session.scalar(
            select(NetworthSnapshotRow).where(
                NetworthSnapshotRow.household_id == snapshot.household_id,
                NetworthSnapshotRow.grid_date == snapshot.grid_date,
            )
        )
        if row is None:
            row = mappers.snapshot_to_row(snapshot)
            self._session.add(row)
        else:
            row.cash_total = snapshot.cash_total
            row.credit_liability_total = snapshot.credit_liability_total
            row.portfolio_total = snapshot.portfolio_total
            row.net_worth = snapshot.net_worth
        self._session.flush()
        return mappers.snapshot_to_domain(row)

    def by_grid(self, household_id: int, grid_date: datetime.date) -> NetworthSnapshot | None:
        row = self._session.scalar(
            select(NetworthSnapshotRow).where(
                NetworthSnapshotRow.household_id == household_id,
                NetworthSnapshotRow.grid_date == grid_date,
            )
        )
        return mappers.snapshot_to_domain(row) if row else None

    def list_by_household(self, household_id: int) -> list[NetworthSnapshot]:
        rows = self._session.scalars(
            select(NetworthSnapshotRow)
            .where(NetworthSnapshotRow.household_id == household_id)
            .order_by(NetworthSnapshotRow.grid_date)
        )
        return [mappers.snapshot_to_domain(r) for r in rows]
