"""Dashboard read routes — Humble Objects over the read-side reader (SPEC §3).

GET-only, LAN/VPN-facing (SPEC §5). Each route calls the injected ``DashboardReader`` and
shapes the response; no money math or formatting here (that is the domain read model's job
on one side and the web edge's ``id-ID`` formatting on the other).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from coffer.api.dashboard import DashboardReader
from coffer.api.dashboard_schemas import (
    ArusKasResponse,
    BelanjaResponse,
    PortofolioResponse,
    RingkasanResponse,
    TagihanResponse,
)
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


@router.get("/arus-kas/{household_id}", response_model=ArusKasResponse)
async def get_arus_kas(
    household_id: int,
    reader: DashboardReader = Depends(get_dashboard_reader),
) -> ArusKasResponse:
    """The §3.5 cash-flow screen: monthly income-vs-spend + savings-rate series, the
    headline savings rate + latest-month cash flow, and the latest month's income-source
    and spend-type breakdown lists."""
    return ArusKasResponse.from_view(reader.arus_kas(household_id))


@router.get("/tagihan/{household_id}", response_model=TagihanResponse)
async def get_tagihan(
    household_id: int,
    reader: DashboardReader = Depends(get_dashboard_reader),
) -> TagihanResponse:
    """The §3.4 bill due-date aggregator: each credit card's latest bill — holder, due date,
    days remaining (relative to today), minimum payment, full statement balance — soonest
    first. Feeds the Tagihan Jatuh Tempo card on Ringkasan (below the hero)."""
    return TagihanResponse.from_view(reader.tagihan(household_id, today=date.today()))
