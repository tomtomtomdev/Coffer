"""Dashboard read routes — Humble Objects over the read-side reader (SPEC §3).

GET-only, LAN/VPN-facing (SPEC §5). Each route calls the injected ``DashboardReader`` and
shapes the response; no money math or formatting here (that is the domain read model's job
on one side and the web edge's ``id-ID`` formatting on the other).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from coffer.api.dashboard import DashboardReader
from coffer.api.dashboard_schemas import BelanjaResponse, PortofolioResponse, RingkasanResponse
from coffer.api.dependencies import get_dashboard_reader

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/ringkasan/{household_id}", response_model=RingkasanResponse)
async def get_ringkasan(
    household_id: int,
    reader: DashboardReader = Depends(get_dashboard_reader),
) -> RingkasanResponse:
    """The §3.1 net-worth overview: household + per-member series, delta, Rincian Akun, KPIs."""
    return RingkasanResponse.from_view(reader.ringkasan(household_id))


@router.get("/portofolio/{household_id}", response_model=PortofolioResponse)
async def get_portofolio(
    household_id: int,
    reader: DashboardReader = Depends(get_dashboard_reader),
) -> PortofolioResponse:
    """The §3.2 consolidated holdings across brokers, with the mixed-as-of-date guard."""
    return PortofolioResponse.from_view(reader.portofolio(household_id))


@router.get("/belanja/{household_id}", response_model=BelanjaResponse)
async def get_belanja(
    household_id: int,
    reader: DashboardReader = Depends(get_dashboard_reader),
) -> BelanjaResponse:
    """The §3.3 spend screen: routine estimate + sparkline + per-category medians +
    anomalies + review queue + the category list for the Tag/Ubah picker."""
    return BelanjaResponse.from_view(reader.belanja(household_id))
