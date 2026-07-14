"""S9 — ingestion endpoint wiring (FastAPI ``TestClient``).

Proves the router is a Humble Object: it parses the multipart request, calls the
injected use-case, and shapes the response. The use-case is faked (no DB/PDF) — its own
behaviour is covered in ``test_pipeline.py`` / ``test_pipeline_integration.py``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from httpx import Response

from coffer.api.app import create_app
from coffer.api.dependencies import get_ingest_use_case
from coffer.domain.enums import UploadedVia
from coffer.ingestion.pipeline import IngestOutcome, IngestResult


class _FakeUseCase:
    def __init__(self, result: IngestResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def execute(
        self,
        *,
        raw_bytes: bytes,
        account_id: int,
        uploaded_via: UploadedVia,
        password: str | None = None,
        uploaded_by_member_id: int | None = None,
    ) -> IngestResult:
        self.calls.append(
            {
                "raw_bytes": raw_bytes,
                "account_id": account_id,
                "uploaded_via": uploaded_via,
                "password": password,
                "uploaded_by_member_id": uploaded_by_member_id,
            }
        )
        return self.result


def _client(result: IngestResult) -> tuple[TestClient, _FakeUseCase]:
    fake = _FakeUseCase(result)
    app = create_app()
    app.dependency_overrides[get_ingest_use_case] = lambda: fake
    return TestClient(app), fake


def _upload(client: TestClient, **fields: object) -> Response:
    response: Response = client.post(
        "/api/statements",
        data={key: str(value) for key, value in fields.items()},
        files={"file": ("statement.pdf", b"%PDF-fake-bytes", "application/pdf")},
    )
    return response


def test_ingested_returns_counts() -> None:
    result = IngestResult(
        IngestOutcome.INGESTED, new_transactions=42, duplicate_transactions=3, statement_id=7
    )
    client, fake = _client(result)
    response = _upload(client, account_id=5, password="hunter2")

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "ingested"
    assert body["new_transactions"] == 42
    assert body["duplicate_transactions"] == 3
    assert body["statement_id"] == 7
    assert body["alert"] is False

    # the router forwarded the parsed request to the use-case verbatim.
    call = fake.calls[0]
    assert call["account_id"] == 5
    assert call["password"] == "hunter2"
    assert call["uploaded_via"] is UploadedVia.WEB
    assert call["raw_bytes"] == b"%PDF-fake-bytes"


def test_needs_password_is_surfaced() -> None:
    client, _ = _client(IngestResult(IngestOutcome.NEEDS_PASSWORD, reason="encrypted"))
    response = _upload(client, account_id=5)
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "needs_password"
    assert body["alert"] is False


def test_rejected_sets_alert() -> None:
    client, _ = _client(IngestResult(IngestOutcome.REJECTED, reason="balance discontinuity"))
    response = _upload(client, account_id=5)
    body = response.json()
    assert body["outcome"] == "rejected"
    assert body["alert"] is True


def test_missing_file_is_422() -> None:
    client, _ = _client(IngestResult(IngestOutcome.INGESTED))
    response = client.post("/api/statements", data={"account_id": "5"})
    assert response.status_code == 422


def test_missing_account_id_is_422() -> None:
    client, _ = _client(IngestResult(IngestOutcome.INGESTED))
    response = client.post(
        "/api/statements",
        files={"file": ("s.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 422


def test_optional_uploaded_by_member_forwarded() -> None:
    client, fake = _client(IngestResult(IngestOutcome.INGESTED))
    _upload(client, account_id=5, uploaded_by_member_id=9)
    assert fake.calls[0]["uploaded_by_member_id"] == 9
