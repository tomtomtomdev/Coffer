"""S14 — Arus Kas read endpoint (FastAPI ``TestClient``).

The route is a Humble Object over the injected reader (faked here). Pins the
money-as-strings edge contract, the ``savings_rate``/``latest_cash_flow`` nullability, and
the ``spend_by_type`` enum-as-value shaping.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from coffer.api.app import create_app
from coffer.api.dependencies import get_dashboard_reader
from coffer.domain.enums import CategoryType
from coffer.domain.read_models import (
    ArusKasView,
    IncomeSource,
    MonthlyCashFlow,
    SpendTypeTotal,
)


class _FakeReader:
    def __init__(self, view: ArusKasView) -> None:
        self.view = view
        self.calls: list[int] = []

    def arus_kas(self, household_id: int) -> ArusKasView:
        self.calls.append(household_id)
        return self.view


def _client(view: ArusKasView) -> tuple[TestClient, _FakeReader]:
    fake = _FakeReader(view)
    app = create_app()
    app.dependency_overrides[get_dashboard_reader] = lambda: fake
    return TestClient(app), fake


def _populated() -> ArusKasView:
    return ArusKasView(
        months=[
            MonthlyCashFlow(
                month=datetime.date(2026, 5, 1),
                income=Decimal("60000000"),
                spend=Decimal("34000000"),
                cash_flow=Decimal("26000000"),
                savings_rate=Decimal("0.4333333"),
            ),
            MonthlyCashFlow(
                month=datetime.date(2026, 6, 1),
                income=Decimal("66000000"),
                spend=Decimal("34000000"),
                cash_flow=Decimal("32000000"),
                savings_rate=Decimal("0.4848484"),
            ),
        ],
        headline_savings_rate=Decimal("0.46"),
        window_months=6,
        latest_month=datetime.date(2026, 6, 1),
        latest_cash_flow=Decimal("32000000"),
        income_sources=[
            IncomeSource(1, "Gaji · Tommy", Decimal("38000000")),
            IncomeSource(2, "Gaji · Priskila", Decimal("22000000")),
        ],
        spend_by_type=[
            SpendTypeTotal(CategoryType.ROUTINE, Decimal("23800000")),
            SpendTypeTotal(CategoryType.ONE_OFF, Decimal("2300000")),
        ],
    )


def test_arus_kas_endpoint_shapes_the_view() -> None:
    client, fake = _client(_populated())
    response = client.get("/api/dashboard/arus-kas/1")

    assert response.status_code == 200
    assert fake.calls == [1]
    body = response.json()

    assert body["headline_savings_rate"] == "0.46"
    assert isinstance(body["headline_savings_rate"], str)
    assert body["latest_month"] == "2026-06-01"
    assert body["latest_cash_flow"] == "32000000"

    assert len(body["months"]) == 2
    assert body["months"][1] == {
        "month": "2026-06-01",
        "income": "66000000",
        "spend": "34000000",
        "cash_flow": "32000000",
        "savings_rate": "0.4848484",
    }

    assert body["income_sources"][0] == {
        "category_id": 1,
        "label": "Gaji · Tommy",
        "amount": "38000000",
    }
    assert body["spend_by_type"][0] == {"type": "routine", "amount": "23800000"}
    assert body["spend_by_type"][1]["type"] == "one_off"


def test_arus_kas_endpoint_empty_household() -> None:
    empty = ArusKasView(
        months=[],
        headline_savings_rate=None,
        window_months=6,
        latest_month=None,
        latest_cash_flow=None,
        income_sources=[],
        spend_by_type=[],
    )
    client, _ = _client(empty)
    body = client.get("/api/dashboard/arus-kas/1").json()
    assert body["months"] == []
    assert body["headline_savings_rate"] is None
    assert body["latest_month"] is None
    assert body["latest_cash_flow"] is None
    assert body["income_sources"] == []
    assert body["spend_by_type"] == []


def test_arus_kas_endpoint_nulls_savings_rate_when_income_zero() -> None:
    view = ArusKasView(
        months=[
            MonthlyCashFlow(
                month=datetime.date(2026, 6, 1),
                income=Decimal("0"),
                spend=Decimal("500000"),
                cash_flow=Decimal("-500000"),
                savings_rate=None,
            ),
        ],
        headline_savings_rate=None,
        window_months=6,
        latest_month=datetime.date(2026, 6, 1),
        latest_cash_flow=Decimal("-500000"),
        income_sources=[],
        spend_by_type=[SpendTypeTotal(CategoryType.ROUTINE, Decimal("500000"))],
    )
    client, _ = _client(view)
    body = client.get("/api/dashboard/arus-kas/1").json()
    assert body["months"][0]["savings_rate"] is None
    assert body["latest_cash_flow"] == "-500000"
