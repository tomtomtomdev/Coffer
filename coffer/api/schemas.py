"""Pydantic models — HTTP edge only (never domain entities).

The api layer validates/serializes at the boundary and converts to/from the domain
value objects (here: ``IngestResult``). Money/formatting stay out of this layer; the
web edge does ``id-ID`` currency formatting.
"""

from __future__ import annotations

from pydantic import BaseModel

from coffer.ingestion.pipeline import IngestResult


class IngestResponse(BaseModel):
    """Surfaces every SPEC §4 outcome + the per-row counts for one uploaded file."""

    outcome: str
    reason: str = ""
    new_transactions: int = 0
    duplicate_transactions: int = 0
    holdings: int = 0
    statement_id: int | None = None
    alert: bool = False

    @classmethod
    def from_result(cls, result: IngestResult) -> IngestResponse:
        return cls(
            outcome=result.outcome.value,
            reason=result.reason,
            new_transactions=result.new_transactions,
            duplicate_transactions=result.duplicate_transactions,
            holdings=result.holdings,
            statement_id=result.statement_id,
            alert=result.alert,
        )
