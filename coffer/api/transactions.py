"""Write-side adapter for the Tag/Ubah action (SPEC §3.3). A Humble Object mirroring
``DashboardReader``: it wires session-bound SQL repos into the ``recategorize_transaction``
use-case and injects the clock. All logic lives in ``coffer.ingestion.recategorize``."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy.orm import Session

from coffer.ingestion.categorize import RuleKey
from coffer.ingestion.recategorize import RecategorizeResult, recategorize_transaction
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlCategoryRepo,
    SqlLearnedRuleRepo,
    SqlMemberRepo,
    SqlOverrideRepo,
    SqlTransactionRepo,
)


class TransactionCategorizer:
    """Applies a manual re-tag over one read-write session (commit is the DI's job)."""

    def __init__(self, session: Session, clock: Callable[[], datetime.datetime]) -> None:
        self._session = session
        self._clock = clock

    def recategorize(
        self,
        *,
        transaction_id: int,
        new_category_id: int,
        member_id: int | None,
        generalize: RuleKey | None,
        confirm_amount_only: bool,
        amount_tolerance: Decimal | None,
    ) -> RecategorizeResult:
        return recategorize_transaction(
            transaction_id=transaction_id,
            new_category_id=new_category_id,
            member_id=member_id,
            generalize=generalize,
            confirm_amount_only=confirm_amount_only,
            amount_tolerance=amount_tolerance,
            now=self._clock(),
            transactions=SqlTransactionRepo(self._session),
            accounts=SqlAccountRepo(self._session),
            members=SqlMemberRepo(self._session),
            categories=SqlCategoryRepo(self._session),
            overrides=SqlOverrideRepo(self._session),
            learned_rules=SqlLearnedRuleRepo(self._session),
        )
