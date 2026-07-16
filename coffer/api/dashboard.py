"""Read-side adapter for the dashboard — wires session-bound SQL repos into the domain
read models (SPEC §3). A Humble Object: it holds no logic, it just hands the concrete
repos to the read-model functions (all net-worth / spend / flow / portfolio logic lives
in the domain). Constructed per-request in the composition root (``dependencies``)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from coffer.domain.read_models import (
    ArusKasView,
    BelanjaView,
    PortfolioView,
    RingkasanView,
    compute_arus_kas,
    compute_belanja,
    compute_ringkasan,
    portfolio_consolidation,
)
from coffer.persistence.repositories import (
    SqlAccountRepo,
    SqlCategoryRepo,
    SqlHoldingRepo,
    SqlMemberRepo,
    SqlNetworthSnapshotRepo,
    SqlStatementRepo,
    SqlTransactionRepo,
)


class DashboardReader:
    """Assembles dashboard read views for a household over one read-only session."""

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

    def portofolio(self, household_id: int) -> PortfolioView:
        return portfolio_consolidation(
            household_id=household_id,
            accounts=SqlAccountRepo(self._session),
            statements=SqlStatementRepo(self._session),
            holdings=SqlHoldingRepo(self._session),
        )

    def belanja(self, household_id: int) -> BelanjaView:
        return compute_belanja(
            household_id=household_id,
            accounts=SqlAccountRepo(self._session),
            transactions=SqlTransactionRepo(self._session),
            categories=SqlCategoryRepo(self._session),
        )

    def arus_kas(self, household_id: int) -> ArusKasView:
        return compute_arus_kas(
            household_id=household_id,
            accounts=SqlAccountRepo(self._session),
            transactions=SqlTransactionRepo(self._session),
            categories=SqlCategoryRepo(self._session),
        )
