"""Transaction write routes — the Tag/Ubah action behind the Belanja review queue (§3.3).

A Humble Object over the injected ``TransactionCategorizer``: it parses the request,
maps the domain errors to HTTP status, and shapes the response. All re-tag logic lives
in ``coffer.ingestion.recategorize``. LAN/VPN-facing like the rest of the dashboard API.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException

from coffer.api.dependencies import get_transaction_categorizer
from coffer.api.transactions import TransactionCategorizer
from coffer.api.transactions_schemas import RecategorizeRequest, RecategorizeResponse
from coffer.ingestion.categorize import RuleKey
from coffer.ingestion.recategorize import CategoryNotFoundError, TransactionNotFoundError

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.post("/{transaction_id}/category", response_model=RecategorizeResponse)
async def recategorize(
    transaction_id: int,
    body: RecategorizeRequest,
    categorizer: TransactionCategorizer = Depends(get_transaction_categorizer),
) -> RecategorizeResponse:
    """Apply a manual tag to a transaction (records an override, stamps it ``manual``,
    refines a mis-fired learned rule, optionally generalizes into a new rule)."""
    tolerance = _parse_tolerance(body.amount_tolerance)
    try:
        result = categorizer.recategorize(
            transaction_id=transaction_id,
            new_category_id=body.category_id,
            member_id=body.member_id,
            generalize=(None if body.generalize is None else RuleKey(body.generalize)),
            confirm_amount_only=body.confirm_amount_only,
            amount_tolerance=tolerance,
        )
    except (TransactionNotFoundError, CategoryNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # e.g. an amount-only rule without explicit confirmation (SPEC §3.3).
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RecategorizeResponse.from_result(result)


def _parse_tolerance(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise HTTPException(status_code=422, detail="amount_tolerance is not a number") from exc
