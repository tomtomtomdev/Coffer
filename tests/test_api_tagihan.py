"""§3.4 — Tagihan (bill due-date) read endpoint (FastAPI ``TestClient``).

Proves the route is a Humble Object: it calls the injected reader (passing today) and
shapes the response. The reader is faked (no DB) — ``compute_tagihan`` / ``bill_due_dates``
are covered in ``test_tagihan.py``. The edge contract asserted here: **money is serialized
as strings** (the exactness invariant), a ``None`` minimum stays ``null``, and ``due_date``
serializes as an ISO date.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from coffer.api.app import create_app
from coffer.api.dependencies import get_dashboard_reader
from coffer.domain.enums import AccountType
from coffer.domain.read_models import BillDue, TagihanView


class _FakeReader:
    def __init__(self, view: TagihanView) -> None:
        self.view = view
        self.calls: list[tuple[int, date]] = []

    def tagihan(self, household_id: int, *, today: date) -> TagihanView:
        self.calls.append((household_id, today))
        return self.view


def _client(view: TagihanView) -> tuple[TestClient, _FakeReader]:
    fake = _FakeReader(view)
    app = create_app()
    app.dependency_overrides[get_dashboard_reader] = lambda: fake
    return TestClient(app), fake


def _populated_view() -> TagihanView:
    return TagihanView(
        as_of=date(2026, 7, 19),
        bills=[
            BillDue(
                account_id=3,
                member_id=2,
                member_name="Priskila",
                institution="cimb",
                account_type=AccountType.CIMB_CREDIT_CARD,
                account_number_masked="****0003",
                due_date=date(2026, 7, 22),
                days_remaining=3,
                minimum_payment=Decimal("150000"),
                statement_balance=Decimal("838303.83"),
            ),
            BillDue(
                account_id=2,
                member_id=1,
                member_name="Tommy",
                institution="bca",
                account_type=AccountType.BCA_CREDIT_CARD,
                account_number_masked="****0002",
                due_date=date(2026, 7, 28),
                days_remaining=9,
                minimum_payment=None,
                statement_balance=Decimal("2177067"),
            ),
        ],
    )


def test_tagihan_endpoint_shapes_the_view() -> None:
    client, fake = _client(_populated_view())
    response = client.get("/api/dashboard/tagihan/1")

    assert response.status_code == 200
    assert fake.calls[0][0] == 1  # household forwarded; today supplied by the route
    body = response.json()

    assert body["as_of"] == "2026-07-19"
    first, second = body["bills"]

    # Sort order (soonest first) is preserved by the edge; money is a string, never a float.
    assert [b["account_id"] for b in body["bills"]] == [3, 2]
    assert first["account_type"] == "cimb_credit_card"
    assert first["member_name"] == "Priskila"
    assert first["due_date"] == "2026-07-22"
    assert first["days_remaining"] == 3
    assert first["minimum_payment"] == "150000"
    assert isinstance(first["statement_balance"], str)
    assert first["statement_balance"] == "838303.83"

    # A statement with no reported minimum stays null on the wire.
    assert second["minimum_payment"] is None
    assert second["statement_balance"] == "2177067"


def test_tagihan_endpoint_empty_household() -> None:
    client, _ = _client(TagihanView(as_of=date(2026, 7, 19), bills=[]))
    response = client.get("/api/dashboard/tagihan/1")

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-07-19"
    assert body["bills"] == []
