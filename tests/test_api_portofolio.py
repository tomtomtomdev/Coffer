"""S12 — Portofolio read endpoint (FastAPI ``TestClient``).

The route is a Humble Object over the injected reader (faked here);
``portfolio_consolidation`` is covered in ``test_portofolio.py``. Asserts the money-as-
strings edge contract and the per-broker breakdown shape.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from coffer.api.app import create_app
from coffer.api.dependencies import get_dashboard_reader
from coffer.domain.read_models import BrokerHolding, ConsolidatedHolding, PortfolioView


class _FakeReader:
    def __init__(self, view: PortfolioView) -> None:
        self.view = view
        self.calls: list[int] = []

    def portofolio(self, household_id: int) -> PortfolioView:
        self.calls.append(household_id)
        return self.view


def _client(view: PortfolioView) -> tuple[TestClient, _FakeReader]:
    fake = _FakeReader(view)
    app = create_app()
    app.dependency_overrides[get_dashboard_reader] = lambda: fake
    return TestClient(app), fake


def _populated() -> PortfolioView:
    return PortfolioView(
        total_market_value=Decimal("4750000"),
        total_unrealized_pl=Decimal("190000"),
        total_cost_basis=Decimal("4560000"),
        holdings=[
            ConsolidatedHolding(
                ticker="BBCA",
                name="BBCA Tbk",
                lots=Decimal("5"),
                avg_price=Decimal("9120"),
                market_value=Decimal("4750000"),
                unrealized_pl=Decimal("190000"),
                cost_basis=Decimal("4560000"),
                brokers=[
                    BrokerHolding(
                        institution="ajaib",
                        account_id=10,
                        lots=Decimal("2"),
                        avg_price=Decimal("9000"),
                        market_price=Decimal("9500"),
                        market_value=Decimal("1900000"),
                        unrealized_pl=Decimal("100000"),
                        as_of=date(2026, 6, 30),
                    ),
                    BrokerHolding(
                        institution="stockbit",
                        account_id=11,
                        lots=Decimal("3"),
                        avg_price=Decimal("9200"),
                        market_price=Decimal("9500"),
                        market_value=Decimal("2850000"),
                        unrealized_pl=Decimal("90000"),
                        as_of=date(2026, 6, 30),
                    ),
                ],
            )
        ],
        as_of_dates=[date(2026, 6, 30)],
        mixed_as_of=False,
    )


def test_portofolio_endpoint_shapes_the_view() -> None:
    client, fake = _client(_populated())
    response = client.get("/api/dashboard/portofolio/1")

    assert response.status_code == 200
    assert fake.calls == [1]
    body = response.json()

    assert body["total_market_value"] == "4750000"
    assert isinstance(body["total_market_value"], str)
    assert body["mixed_as_of"] is False
    assert body["as_of_dates"] == ["2026-06-30"]

    holding = body["holdings"][0]
    assert holding["ticker"] == "BBCA"
    assert holding["avg_price"] == "9120"
    assert holding["cost_basis"] == "4560000"
    assert [b["institution"] for b in holding["brokers"]] == ["ajaib", "stockbit"]
    assert holding["brokers"][0]["as_of"] == "2026-06-30"


def test_portofolio_endpoint_empty() -> None:
    empty = PortfolioView(
        total_market_value=Decimal("0"),
        total_unrealized_pl=Decimal("0"),
        total_cost_basis=Decimal("0"),
        holdings=[],
        as_of_dates=[],
        mixed_as_of=False,
    )
    client, _ = _client(empty)
    response = client.get("/api/dashboard/portofolio/1")

    assert response.status_code == 200
    body = response.json()
    assert body["holdings"] == []
    assert body["as_of_dates"] == []
    assert body["total_market_value"] == "0"
