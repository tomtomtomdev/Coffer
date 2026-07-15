"""Pydantic edge models for the Tag/Ubah write endpoint (SPEC §3.3).

The request is the only place Pydantic parses inbound money (``amount_tolerance``) — it
arrives as a string and is converted to ``Decimal`` at the edge, never a float. The
response echoes the resulting provenance (always ``manual``) + any rule ids touched.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from coffer.ingestion.recategorize import RecategorizeResult


class RecategorizeRequest(BaseModel):
    """Body of ``POST /api/transactions/{id}/category``.

    ``generalize`` opts into creating a learned rule: ``counterparty_acct`` (safe, needs a
    recipient acct) or ``amount`` (weak — requires ``confirm_amount_only=True``, SPEC §3.3).
    """

    category_id: int
    member_id: int | None = None
    generalize: Literal["counterparty_acct", "amount"] | None = None
    confirm_amount_only: bool = False
    amount_tolerance: str | None = None  # Decimal string; parsed at the edge


class RecategorizeResponse(BaseModel):
    transaction_id: int
    category_id: int
    category_source: str  # always "manual" — a manual tag always wins (§3.3)
    deactivated_rule_id: int | None
    created_rule_id: int | None

    @classmethod
    def from_result(cls, result: RecategorizeResult) -> RecategorizeResponse:
        return cls(
            transaction_id=result.transaction_id,
            category_id=result.category_id,
            category_source="manual",
            deactivated_rule_id=result.deactivated_rule_id,
            created_rule_id=result.created_rule_id,
        )
