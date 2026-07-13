"""Boundary mappers: domain entities ↔ SQLAlchemy rows.

Kept out of the repositories so the translation is in one place and the repos stay
thin. The credential mapper is the one place the ``FieldCipher`` is applied — the
plaintext ``secret`` is encrypted on the way to the row and decrypted on the way
back, so the ORM/DB only ever hold ciphertext (SPEC §6).
"""

from __future__ import annotations

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


def household_to_row(entity: Household) -> HouseholdRow:
    return HouseholdRow(id=entity.id, name=entity.name)


def household_to_domain(row: HouseholdRow) -> Household:
    return Household(id=row.id, name=row.name)


def member_to_row(entity: Member) -> MemberRow:
    return MemberRow(
        id=entity.id,
        household_id=entity.household_id,
        name=entity.name,
        telegram_user_id=entity.telegram_user_id,
    )


def member_to_domain(row: MemberRow) -> Member:
    return Member(
        id=row.id,
        household_id=row.household_id,
        name=row.name,
        telegram_user_id=row.telegram_user_id,
    )


def account_to_row(entity: Account) -> AccountRow:
    return AccountRow(
        id=entity.id,
        member_id=entity.member_id,
        institution=entity.institution,
        account_type=entity.account_type.value,
        account_number_masked=entity.account_number_masked,
        currency=entity.currency,
    )


def account_to_domain(row: AccountRow) -> Account:
    return Account(
        id=row.id,
        member_id=row.member_id,
        institution=row.institution,
        account_type=AccountType(row.account_type),
        account_number_masked=row.account_number_masked,
        currency=row.currency,
    )


def credential_to_row(
    entity: InstitutionCredential, cipher: FieldCipher
) -> InstitutionCredentialRow:
    return InstitutionCredentialRow(
        id=entity.id,
        household_id=entity.household_id,
        institution=entity.institution,
        password_scheme=entity.password_scheme.value,
        password_enc=cipher.encrypt(entity.secret) if entity.secret is not None else None,
    )


def credential_to_domain(
    row: InstitutionCredentialRow, cipher: FieldCipher
) -> InstitutionCredential:
    return InstitutionCredential(
        id=row.id,
        household_id=row.household_id,
        institution=row.institution,
        password_scheme=PasswordScheme(row.password_scheme),
        secret=cipher.decrypt(row.password_enc) if row.password_enc is not None else None,
    )


def statement_to_row(entity: Statement) -> StatementRow:
    return StatementRow(
        id=entity.id,
        account_id=entity.account_id,
        period_start=entity.period_start,
        period_end=entity.period_end,
        file_hash=entity.file_hash,
        content_hash=entity.content_hash,
        uploaded_via=entity.uploaded_via.value,
        uploaded_by_member_id=entity.uploaded_by_member_id,
        uploaded_at=entity.uploaded_at,
        parser_version=entity.parser_version,
        is_encrypted=entity.is_encrypted,
        encrypted_file_path=entity.encrypted_file_path,
    )


def statement_to_domain(row: StatementRow) -> Statement:
    return Statement(
        id=row.id,
        account_id=row.account_id,
        period_start=row.period_start,
        period_end=row.period_end,
        file_hash=row.file_hash,
        content_hash=row.content_hash,
        uploaded_via=UploadedVia(row.uploaded_via),
        uploaded_by_member_id=row.uploaded_by_member_id,
        uploaded_at=row.uploaded_at,
        parser_version=row.parser_version,
        is_encrypted=row.is_encrypted,
        encrypted_file_path=row.encrypted_file_path,
    )


def transaction_to_row(entity: Transaction) -> TransactionRow:
    return TransactionRow(
        id=entity.id,
        statement_id=entity.statement_id,
        account_id=entity.account_id,
        date=entity.date,
        description=entity.description,
        debit=entity.debit,
        credit=entity.credit,
        balance=entity.balance,
        category_id=entity.category_id,
        category_source=entity.category_source.value if entity.category_source else None,
        counterparty_name=entity.counterparty_name,
        counterparty_acct=entity.counterparty_acct,
        dedup_key=entity.dedup_key,
        raw_ref=entity.raw_ref,
        edited_by=entity.edited_by,
        edited_at=entity.edited_at,
    )


def transaction_to_domain(row: TransactionRow) -> Transaction:
    return Transaction(
        id=row.id,
        statement_id=row.statement_id,
        account_id=row.account_id,
        date=row.date,
        description=row.description,
        debit=row.debit,
        credit=row.credit,
        balance=row.balance,
        category_id=row.category_id,
        category_source=CategorySource(row.category_source) if row.category_source else None,
        counterparty_name=row.counterparty_name,
        counterparty_acct=row.counterparty_acct,
        dedup_key=row.dedup_key,
        raw_ref=row.raw_ref,
        edited_by=row.edited_by,
        edited_at=row.edited_at,
    )


def category_to_row(entity: Category) -> CategoryRow:
    return CategoryRow(
        id=entity.id,
        household_id=entity.household_id,
        match_pattern=entity.match_pattern,
        label=entity.label,
        type=entity.type.value,
        cadence=entity.cadence.value,
    )


def category_to_domain(row: CategoryRow) -> Category:
    return Category(
        id=row.id,
        household_id=row.household_id,
        match_pattern=row.match_pattern,
        label=row.label,
        type=CategoryType(row.type),
        cadence=Cadence(row.cadence),
    )


def override_to_row(entity: Override) -> OverrideRow:
    return OverrideRow(
        id=entity.id,
        transaction_id=entity.transaction_id,
        category_id=entity.category_id,
        member_id=entity.member_id,
        created_at=entity.created_at,
    )


def override_to_domain(row: OverrideRow) -> Override:
    return Override(
        id=row.id,
        transaction_id=row.transaction_id,
        category_id=row.category_id,
        member_id=row.member_id,
        created_at=row.created_at,
    )


def learned_rule_to_row(entity: LearnedRule) -> LearnedRuleRow:
    return LearnedRuleRow(
        id=entity.id,
        household_id=entity.household_id,
        category_id=entity.category_id,
        match_counterparty_acct=entity.match_counterparty_acct,
        match_amount=entity.match_amount,
        match_amount_tolerance=entity.match_amount_tolerance,
        created_from_transaction_id=entity.created_from_transaction_id,
        active=entity.active,
        created_at=entity.created_at,
        hit_count=entity.hit_count,
    )


def learned_rule_to_domain(row: LearnedRuleRow) -> LearnedRule:
    return LearnedRule(
        id=row.id,
        household_id=row.household_id,
        category_id=row.category_id,
        match_counterparty_acct=row.match_counterparty_acct,
        match_amount=row.match_amount,
        match_amount_tolerance=row.match_amount_tolerance,
        created_from_transaction_id=row.created_from_transaction_id,
        active=row.active,
        created_at=row.created_at,
        hit_count=row.hit_count,
    )


def holding_to_row(entity: Holding) -> HoldingRow:
    return HoldingRow(
        id=entity.id,
        account_id=entity.account_id,
        statement_id=entity.statement_id,
        ticker=entity.ticker,
        name=entity.name,
        lot_balance=entity.lot_balance,
        avg_price=entity.avg_price,
        market_price=entity.market_price,
        market_value=entity.market_value,
        unrealized_pl=entity.unrealized_pl,
        as_of_date=entity.as_of_date,
    )


def holding_to_domain(row: HoldingRow) -> Holding:
    return Holding(
        id=row.id,
        account_id=row.account_id,
        statement_id=row.statement_id,
        ticker=row.ticker,
        name=row.name,
        lot_balance=row.lot_balance,
        avg_price=row.avg_price,
        market_price=row.market_price,
        market_value=row.market_value,
        unrealized_pl=row.unrealized_pl,
        as_of_date=row.as_of_date,
    )


def snapshot_to_row(entity: NetworthSnapshot) -> NetworthSnapshotRow:
    return NetworthSnapshotRow(
        id=entity.id,
        household_id=entity.household_id,
        grid_date=entity.grid_date,
        cash_total=entity.cash_total,
        credit_liability_total=entity.credit_liability_total,
        portfolio_total=entity.portfolio_total,
        net_worth=entity.net_worth,
    )


def snapshot_to_domain(row: NetworthSnapshotRow) -> NetworthSnapshot:
    return NetworthSnapshot(
        id=row.id,
        household_id=row.household_id,
        grid_date=row.grid_date,
        cash_total=row.cash_total,
        credit_liability_total=row.credit_liability_total,
        portfolio_total=row.portfolio_total,
        net_worth=row.net_worth,
    )
