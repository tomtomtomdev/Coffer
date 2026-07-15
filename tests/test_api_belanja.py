"""S13 — Belanja read endpoint + the Tag/Ubah write endpoint (FastAPI ``TestClient``).

The routes are Humble Objects over the injected reader / categorizer (faked here). Pins
the money-as-strings edge contract on the read side, and the error→status mapping +
argument forwarding on the write side.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from coffer.api.app import create_app
from coffer.api.dependencies import get_dashboard_reader, get_transaction_categorizer
from coffer.domain.enums import Cadence, CategorySource, CategoryType
from coffer.domain.read_models import (
    BelanjaView,
    CategoryMedian,
    CategoryOption,
    MonthlyRoutinePoint,
    ReviewItem,
    SpendAnomaly,
)
from coffer.ingestion.categorize import RuleKey
from coffer.ingestion.recategorize import (
    CategoryNotFoundError,
    RecategorizeResult,
    TransactionNotFoundError,
)

# ── read side ─────────────────────────────────────────────────────────────────────---


class _FakeReader:
    def __init__(self, view: BelanjaView) -> None:
        self.view = view
        self.calls: list[int] = []

    def belanja(self, household_id: int) -> BelanjaView:
        self.calls.append(household_id)
        return self.view


def _populated() -> BelanjaView:
    return BelanjaView(
        estimate=Decimal("600000"),
        insufficient_data=False,
        months_observed=6,
        window_months=6,
        base_median_monthly=Decimal("500000"),
        annual_amortized_monthly=Decimal("100000"),
        monthly_series=[
            MonthlyRoutinePoint(datetime.date(2026, m, 1), Decimal("500000")) for m in range(1, 7)
        ],
        category_breakdown=[
            CategoryMedian(1, "Belanja Harian", Decimal("500000"), 6, Cadence.MONTHLY),
            CategoryMedian(2, "STNK", Decimal("100000"), 1, Cadence.ANNUAL),
        ],
        anomalies=[
            SpendAnomaly(
                99,
                1,
                "Belanja Harian",
                "GRAB SURGE",
                Decimal("2000000"),
                Decimal("500000"),
                "possibly non-routine",
            ),
        ],
        review_queue=[
            ReviewItem(
                transaction_id=77,
                date=datetime.date(2026, 3, 9),
                description="TOKO XYZ",
                debit=Decimal("250000"),
                credit=Decimal("0"),
                counterparty_name=None,
                counterparty_acct="123456",
                account_id=2,
                institution="bca",
                account_number_masked="****5678",
                category_id=None,
                category_label=None,
                category_source=None,
                is_anomaly=False,
            ),
            ReviewItem(
                transaction_id=88,
                date=datetime.date(2026, 2, 2),
                description="INDOMARET",
                debit=Decimal("90000"),
                credit=Decimal("0"),
                counterparty_name=None,
                counterparty_acct=None,
                account_id=1,
                institution="bca",
                account_number_masked="****1234",
                category_id=1,
                category_label="Belanja Harian",
                category_source=CategorySource.PARSER,
                is_anomaly=False,
            ),
        ],
        categories=[
            CategoryOption(1, "Belanja Harian", CategoryType.ROUTINE, Cadence.MONTHLY),
            CategoryOption(2, "STNK", CategoryType.ROUTINE, Cadence.ANNUAL),
        ],
    )


def _read_client(view: BelanjaView) -> tuple[TestClient, _FakeReader]:
    fake = _FakeReader(view)
    app = create_app()
    app.dependency_overrides[get_dashboard_reader] = lambda: fake
    return TestClient(app), fake


def test_belanja_endpoint_shapes_the_view() -> None:
    client, fake = _read_client(_populated())
    response = client.get("/api/dashboard/belanja/1")

    assert response.status_code == 200
    assert fake.calls == [1]
    body = response.json()

    assert body["estimate"] == "600000"
    assert isinstance(body["estimate"], str)
    assert body["base_median_monthly"] == "500000"
    assert len(body["monthly_series"]) == 6
    assert body["monthly_series"][0] == {"month": "2026-01-01", "total": "500000"}

    assert body["category_breakdown"][1]["cadence"] == "annual"
    assert body["anomalies"][0]["description"] == "GRAB SURGE"

    queue = body["review_queue"]
    assert queue[0]["transaction_id"] == 77
    assert queue[0]["category_source"] is None  # uncategorized ⇒ "Perlu tag"
    assert queue[0]["debit"] == "250000"
    assert queue[1]["category_source"] == "parser"
    assert [c["id"] for c in body["categories"]] == [1, 2]


def test_belanja_endpoint_cold_start_nulls_estimate() -> None:
    empty = BelanjaView(
        estimate=None,
        insufficient_data=True,
        months_observed=1,
        window_months=6,
        base_median_monthly=Decimal("0"),
        annual_amortized_monthly=Decimal("0"),
        monthly_series=[],
        category_breakdown=[],
        anomalies=[],
        review_queue=[],
        categories=[],
    )
    client, _ = _read_client(empty)
    body = client.get("/api/dashboard/belanja/1").json()
    assert body["estimate"] is None
    assert body["insufficient_data"] is True
    assert body["review_queue"] == []


# ── write side ────────────────────────────────────────────────────────────────────---


class _FakeCategorizer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None
        self.result = RecategorizeResult(
            transaction_id=100, category_id=7, deactivated_rule_id=None, created_rule_id=None
        )

    def recategorize(
        self,
        *,
        transaction_id: int,
        new_category_id: int,
        member_id: int | None,
        generalize: RuleKey | None,
        confirm_amount_only: bool,
        amount_tolerance: Decimal | None,
    ) -> RecategorizeResult:
        self.calls.append(
            {
                "transaction_id": transaction_id,
                "new_category_id": new_category_id,
                "member_id": member_id,
                "generalize": generalize,
                "confirm_amount_only": confirm_amount_only,
                "amount_tolerance": amount_tolerance,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


def _write_client(fake: _FakeCategorizer) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_transaction_categorizer] = lambda: fake
    return TestClient(app)


def test_recategorize_endpoint_forwards_and_shapes() -> None:
    fake = _FakeCategorizer()
    fake.result = RecategorizeResult(
        transaction_id=100, category_id=7, deactivated_rule_id=3, created_rule_id=42
    )
    client = _write_client(fake)
    response = client.post(
        "/api/transactions/100/category",
        json={
            "category_id": 7,
            "member_id": 5,
            "generalize": "counterparty_acct",
            "amount_tolerance": "1000",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["category_source"] == "manual"
    assert body["deactivated_rule_id"] == 3
    assert body["created_rule_id"] == 42

    call = fake.calls[0]
    assert call["transaction_id"] == 100
    assert call["new_category_id"] == 7
    assert call["generalize"] is RuleKey.COUNTERPARTY_ACCT
    assert call["amount_tolerance"] == Decimal("1000")


def test_recategorize_unknown_transaction_is_404() -> None:
    fake = _FakeCategorizer()
    fake.error = TransactionNotFoundError("nope")
    client = _write_client(fake)
    response = client.post("/api/transactions/999/category", json={"category_id": 7})
    assert response.status_code == 404


def test_recategorize_unknown_category_is_404() -> None:
    fake = _FakeCategorizer()
    fake.error = CategoryNotFoundError("nope")
    client = _write_client(fake)
    response = client.post("/api/transactions/100/category", json={"category_id": 999})
    assert response.status_code == 404


def test_recategorize_amount_only_without_confirm_is_400() -> None:
    fake = _FakeCategorizer()
    fake.error = ValueError("an amount-only rule … requires explicit confirmation")
    client = _write_client(fake)
    response = client.post(
        "/api/transactions/100/category",
        json={"category_id": 7, "generalize": "amount"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("bad", ["abc", "1,0"])
def test_recategorize_bad_tolerance_is_422(bad: str) -> None:
    client = _write_client(_FakeCategorizer())
    response = client.post(
        "/api/transactions/100/category",
        json={"category_id": 7, "amount_tolerance": bad},
    )
    assert response.status_code == 422
