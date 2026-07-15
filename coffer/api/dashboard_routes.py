"""Dashboard read routes — Humble Objects over the read-side reader (SPEC §3.1).

GET-only, LAN/VPN-facing (SPEC §5). The route calls the injected ``RingkasanReader`` and
shapes the response; no money math or formatting here (that is the domain read model's
job on one side and the web edge's ``id-ID`` formatting on the other).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from coffer.api.dashboard import RingkasanReader
from coffer.api.dashboard_schemas import RingkasanResponse
from coffer.api.dependencies import get_ringkasan_reader

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/ringkasan/{household_id}", response_model=RingkasanResponse)
async def get_ringkasan(
    household_id: int,
    reader: RingkasanReader = Depends(get_ringkasan_reader),
) -> RingkasanResponse:
    """The §3.1 net-worth overview: household + per-member series, delta, Rincian Akun, KPIs."""
    return RingkasanResponse.from_view(reader.ringkasan(household_id))
