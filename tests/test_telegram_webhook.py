"""S10 — Telegram webhook endpoint (FastAPI ``TestClient``).

Proves the router is a Humble Object: it verifies the secret token (SPEC §5), parses the
Telegram ``Update``, and dispatches to the injected use-case. The use-case is faked (its
behaviour is covered in ``test_telegram.py``); here we pin the edge — secret-token
rejection and update routing.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

from coffer.api.app import create_app
from coffer.api.dependencies import get_telegram_use_case, get_webhook_secret
from coffer.ingestion.telegram import TelegramOutcome, TelegramResult

_SECRET = "top-secret-token"
_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class _FakeUseCase:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.callbacks: list[dict[str, Any]] = []

    def handle_document(
        self, *, telegram_user_id: int, chat_id: int, message_id: int, file_id: str
    ) -> TelegramResult:
        self.documents.append(
            {
                "telegram_user_id": telegram_user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "file_id": file_id,
            }
        )
        return TelegramResult(TelegramOutcome.INGESTED)

    def handle_callback(
        self, *, telegram_user_id: int, callback_query_id: str, callback_data: str, chat_id: int
    ) -> TelegramResult:
        self.callbacks.append(
            {
                "telegram_user_id": telegram_user_id,
                "callback_query_id": callback_query_id,
                "callback_data": callback_data,
                "chat_id": chat_id,
            }
        )
        return TelegramResult(TelegramOutcome.INGESTED)


def _client() -> tuple[TestClient, _FakeUseCase]:
    fake = _FakeUseCase()
    app = create_app()
    app.dependency_overrides[get_telegram_use_case] = lambda: fake
    app.dependency_overrides[get_webhook_secret] = lambda: _SECRET
    return TestClient(app), fake


def _post(client: TestClient, body: dict[str, Any], *, secret: str | None = _SECRET) -> Response:
    headers = {_HEADER: secret} if secret is not None else {}
    response: Response = client.post("/api/telegram/webhook", json=body, headers=headers)
    return response


def _document_update() -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 42,
            "chat": {"id": 900},
            "from": {"id": 111},
            "document": {"file_id": "FILE123", "mime_type": "application/pdf"},
        },
    }


def test_missing_secret_is_rejected() -> None:
    client, fake = _client()
    response = _post(client, _document_update(), secret=None)
    assert response.status_code == 403
    assert fake.documents == []  # never dispatched


def test_wrong_secret_is_rejected() -> None:
    client, fake = _client()
    response = _post(client, _document_update(), secret="not-the-secret")
    assert response.status_code == 403
    assert fake.documents == []


def test_document_is_dispatched_with_correct_secret() -> None:
    client, fake = _client()
    response = _post(client, _document_update())
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake.documents == [
        {"telegram_user_id": 111, "chat_id": 900, "message_id": 42, "file_id": "FILE123"}
    ]


def test_callback_query_is_dispatched() -> None:
    client, fake = _client()
    body = {
        "update_id": 2,
        "callback_query": {
            "id": "CB1",
            "from": {"id": 111},
            "data": "acct:900:42:7",
            "message": {"message_id": 43, "chat": {"id": 900}},
        },
    }
    response = _post(client, body)
    assert response.status_code == 200
    assert fake.callbacks == [
        {
            "telegram_user_id": 111,
            "callback_query_id": "CB1",
            "callback_data": "acct:900:42:7",
            "chat_id": 900,
        }
    ]


def test_non_pdf_document_is_ignored() -> None:
    client, fake = _client()
    body = _document_update()
    body["message"]["document"] = {"file_id": "IMG9", "mime_type": "image/png"}
    response = _post(client, body)
    assert response.status_code == 200
    assert fake.documents == []  # not a statement → not dispatched


def test_plain_text_message_is_ignored() -> None:
    client, fake = _client()
    body = {
        "update_id": 3,
        "message": {"message_id": 5, "chat": {"id": 900}, "from": {"id": 111}, "text": "halo"},
    }
    response = _post(client, body)
    assert response.status_code == 200
    assert fake.documents == [] and fake.callbacks == []
