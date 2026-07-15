"""Pydantic response models for the dashboard read endpoints — HTTP edge only.

**Money is serialized as strings**, never floats: ``Decimal`` is exact and the "never
float, ever" invariant (CLAUDE.md) must survive the wire. The web edge parses these and
applies ``id-ID`` currency formatting — no formatting or money math happens here.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from coffer.domain.read_models import PortfolioView, RingkasanView


class GridPointSchema(BaseModel):
    grid_date: date
    cash: str
    portfolio: str
    liability: str
    net_worth: str


class MemberPointSchema(BaseModel):
    grid_date: date
    net_worth: str


class MemberSeriesSchema(BaseModel):
    member_id: int
    member_name: str
    points: list[MemberPointSchema]


class AccountBalanceSchema(BaseModel):
    account_id: int
    member_id: int
    institution: str
    account_type: str  # AccountType value, e.g. "bca_savings"
    account_number_masked: str
    bucket: str  # "cash" | "liability" | "portfolio" — drives the UI sign/colour
    balance: str
    as_of: date | None


class DeltaSchema(BaseModel):
    amount: str
    pct: str | None  # null when the prior month's net worth was zero


class KpiSchema(BaseModel):
    routine_spend_monthly: str | None  # null on cold start (<3 months)
    routine_annual_amortized: str
    savings_rate: str | None  # null when income is zero
    monthly_cash_flow: str | None  # null when there is no month of data


class RingkasanResponse(BaseModel):
    """The §3.1 overview payload for the Ringkasan screen."""

    as_of: date | None
    net_worth: str
    delta: DeltaSchema | None
    household_series: list[GridPointSchema]
    member_series: list[MemberSeriesSchema]
    accounts: list[AccountBalanceSchema]
    kpis: KpiSchema

    @classmethod
    def from_view(cls, view: RingkasanView) -> RingkasanResponse:
        return cls(
            as_of=view.as_of,
            net_worth=str(view.net_worth),
            delta=(
                None
                if view.delta is None
                else DeltaSchema(
                    amount=str(view.delta.amount),
                    pct=(None if view.delta.pct is None else str(view.delta.pct)),
                )
            ),
            household_series=[
                GridPointSchema(
                    grid_date=p.grid_date,
                    cash=str(p.cash),
                    portfolio=str(p.portfolio),
                    liability=str(p.liability),
                    net_worth=str(p.net_worth),
                )
                for p in view.household_series
            ],
            member_series=[
                MemberSeriesSchema(
                    member_id=m.member_id,
                    member_name=m.member_name,
                    points=[
                        MemberPointSchema(grid_date=pt.grid_date, net_worth=str(pt.net_worth))
                        for pt in m.points
                    ],
                )
                for m in view.member_series
            ],
            accounts=[
                AccountBalanceSchema(
                    account_id=a.account_id,
                    member_id=a.member_id,
                    institution=a.institution,
                    account_type=a.account_type.value,
                    account_number_masked=a.account_number_masked,
                    bucket=a.bucket.value,
                    balance=str(a.balance),
                    as_of=a.as_of,
                )
                for a in view.accounts
            ],
            kpis=KpiSchema(
                routine_spend_monthly=(
                    None
                    if view.kpis.routine_spend_monthly is None
                    else str(view.kpis.routine_spend_monthly)
                ),
                routine_annual_amortized=str(view.kpis.routine_annual_amortized),
                savings_rate=(
                    None if view.kpis.savings_rate is None else str(view.kpis.savings_rate)
                ),
                monthly_cash_flow=(
                    None
                    if view.kpis.monthly_cash_flow is None
                    else str(view.kpis.monthly_cash_flow)
                ),
            ),
        )


class BrokerHoldingSchema(BaseModel):
    institution: str
    account_id: int
    lots: str
    avg_price: str
    market_price: str
    market_value: str
    unrealized_pl: str
    as_of: date


class ConsolidatedHoldingSchema(BaseModel):
    ticker: str
    name: str
    lots: str
    avg_price: str
    market_value: str
    unrealized_pl: str
    cost_basis: str
    brokers: list[BrokerHoldingSchema]


class PortofolioResponse(BaseModel):
    """The §3.2 consolidated-holdings payload (money as strings; charts/format at the edge)."""

    total_market_value: str
    total_unrealized_pl: str
    total_cost_basis: str
    holdings: list[ConsolidatedHoldingSchema]
    as_of_dates: list[date]
    mixed_as_of: bool

    @classmethod
    def from_view(cls, view: PortfolioView) -> PortofolioResponse:
        return cls(
            total_market_value=str(view.total_market_value),
            total_unrealized_pl=str(view.total_unrealized_pl),
            total_cost_basis=str(view.total_cost_basis),
            as_of_dates=view.as_of_dates,
            mixed_as_of=view.mixed_as_of,
            holdings=[
                ConsolidatedHoldingSchema(
                    ticker=h.ticker,
                    name=h.name,
                    lots=str(h.lots),
                    avg_price=str(h.avg_price),
                    market_value=str(h.market_value),
                    unrealized_pl=str(h.unrealized_pl),
                    cost_basis=str(h.cost_basis),
                    brokers=[
                        BrokerHoldingSchema(
                            institution=b.institution,
                            account_id=b.account_id,
                            lots=str(b.lots),
                            avg_price=str(b.avg_price),
                            market_price=str(b.market_price),
                            market_value=str(b.market_value),
                            unrealized_pl=str(b.unrealized_pl),
                            as_of=b.as_of,
                        )
                        for b in h.brokers
                    ],
                )
                for h in view.holdings
            ],
        )
