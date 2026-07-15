"""Read-side adapter for the dashboard — wires session-bound SQL repos into the
domain read models (SPEC §3.1). A Humble Object: it holds no logic, it just hands the
concrete repos to ``compute_ringkasan`` (all the net-worth/spend/flow logic lives in the
domain). Constructed per-request in the composition root (``dependencies``)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from coffer.domain.read_models import RingkasanView, compute_ringkasan
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlCategoryRepo,
    SqlMemberRepo,
    SqlNetworthSnapshotRepo,
    SqlStatementRepo,
    SqlTransactionRepo,
)


class RingkasanReader:
    """Assembles the §3.1 Ringkasan view for a household over one read-only session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ringkasan(self, household_id: int) -> RingkasanView:
        return compute_ringkasan(
            household_id=household_id,
            accounts=SqlAccountRepo(self._session),
            members=SqlMemberRepo(self._session),
            statements=SqlStatementRepo(self._session),
            transactions=SqlTransactionRepo(self._session),
            categories=SqlCategoryRepo(self._session),
            snapshots=SqlNetworthSnapshotRepo(self._session),
        )
