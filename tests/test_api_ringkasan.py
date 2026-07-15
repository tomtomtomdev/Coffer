"""S11 — Ringkasan read endpoint (FastAPI ``TestClient``).

Proves the route is a Humble Object: it calls the injected read-side reader and shapes
the response. The reader is faked (no DB) — ``compute_ringkasan`` itself is covered in
``test_ringkasan.py``. The key edge contract asserted here: **money is serialized as
strings**, never floats (CLAUDE.md — the ``id-ID`` formatting happens on the web edge).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from coffer.api.app import create_app
from coffer.api.dependencies import get_ringkasan_reader
from coffer.domain.enums import AccountType
from coffer.domain.networth import Bucket
from coffer.domain.read_models import (
    AccountBalance,
    MemberNetworth,
    MemberSeriesPoint,
    NetworthDelta,
    NetworthGridPoint,
    RingkasanKpis,
    RingkasanView,
)


class _FakeReader:
    def __init__(self, view: RingkasanView) -> None:
        self.view = view
        self.calls: list[int] = []

    def ringkasan(self, household_id: int) -> RingkasanView:
        self.calls.append(household_id)
        return self.view


def _client(view: RingkasanView) -> tuple[TestClient, _FakeReader]:
    fake = _FakeReader(view)
    app = create_app()
    app.dependency_overrides[get_ringkasan_reader] = lambda: fake
    return TestClient(app), fake


def _populated_view() -> RingkasanView:
    return RingkasanView(
        as_of=date(2026, 6, 30),
        net_worth=Decimal("175"),
        delta=NetworthDelta(amount=Decimal("40"), pct=Decimal("0.5")),
        household_series=[
            NetworthGridPoint(
                grid_date=date(2026, 6, 30),
                cash=Decimal("205"),
                portfolio=Decimal("0"),
                liability=Decimal("30"),
                net_worth=Decimal("175"),
            )
        ],
        member_series=[
            MemberNetworth(
                member_id=1,
                member_name="Tommy",
                points=[MemberSeriesPoint(grid_date=date(2026, 6, 30), net_worth=Decimal("120"))],
            )
        ],
        accounts=[
            AccountBalance(
                account_id=1,
                member_id=1,
                institution="bca",
                account_type=AccountType.BCA_SAVINGS,
                account_number_masked="****0001",
                bucket=Bucket.CASH,
                balance=Decimal("150"),
                as_of=date(2026, 6, 30),
            )
        ],
        kpis=RingkasanKpis(
            routine_spend_monthly=Decimal("300000"),
            routine_annual_amortized=Decimal("0"),
            savings_rate=Decimal("0.7"),
            monthly_cash_flow=Decimal("700000"),
        ),
    )


def test_ringkasan_endpoint_shapes_the_view() -> None:
    client, fake = _client(_populated_view())
    response = client.get("/api/dashboard/ringkasan/1")

    assert response.status_code == 200
    assert fake.calls == [1]
    body = response.json()

    # Money is a string, never a float (the exactness invariant).
    assert body["net_worth"] == "175"
    assert isinstance(body["net_worth"], str)
    assert body["delta"] == {"amount": "40", "pct": "0.5"}
    assert body["household_series"][0]["cash"] == "205"
    assert body["household_series"][0]["net_worth"] == "175"
    assert body["member_series"][0] == {
        "member_id": 1,
        "member_name": "Tommy",
        "points": [{"grid_date": "2026-06-30", "net_worth": "120"}],
    }
    acct = body["accounts"][0]
    assert acct["bucket"] == "cash"
    assert acct["account_type"] == "bca_savings"
    assert acct["balance"] == "150"
    assert acct["as_of"] == "2026-06-30"
    assert body["kpis"]["savings_rate"] == "0.7"
    assert body["kpis"]["monthly_cash_flow"] == "700000"
    assert body["as_of"] == "2026-06-30"


def test_ringkasan_endpoint_empty_household() -> None:
    empty = RingkasanView(
        as_of=None,
        net_worth=Decimal("0"),
        delta=None,
        household_series=[],
        member_series=[],
        accounts=[],
        kpis=RingkasanKpis(
            routine_spend_monthly=None,
            routine_annual_amortized=Decimal("0"),
            savings_rate=None,
            monthly_cash_flow=None,
        ),
    )
    client, _ = _client(empty)
    response = client.get("/api/dashboard/ringkasan/1")

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] is None
    assert body["delta"] is None
    assert body["net_worth"] == "0"
    assert body["household_series"] == []
    assert body["kpis"]["routine_spend_monthly"] is None
    assert body["kpis"]["savings_rate"] is None
