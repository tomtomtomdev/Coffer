"""S10 — concrete Telegram adapters (``coffer.api.telegram_adapters``).

Exercises the real ``HttpxTelegramClient`` code path — URL construction, the two-step
file download, and the JSON/inline-keyboard payload shaping — against an in-process
``httpx.MockTransport`` (no network, no bot token spent). The bot token must ride only in
the URL to Telegram, never in a logged payload.
"""

from __future__ import annotations

import json

import httpx

from coffer.api.telegram_adapters import HttpxTelegramClient, InMemoryPendingUploadStore
from coffer.ingestion.telegram import InlineButton, PendingUpload

_TOKEN = "12345:ABC"


def _client(handler: object) -> HttpxTelegramClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return HttpxTelegramClient(_TOKEN, api_base="https://tg.test", transport=transport)


def test_download_file_resolves_path_then_fetches_bytes() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/getFile"):
            assert request.url.params["file_id"] == "FILE123"
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "docs/x.pdf"}})
        return httpx.Response(200, content=b"%PDF-real-bytes")

    data = _client(handler).download_file("FILE123")
    assert data == b"%PDF-real-bytes"
    # getFile carries the bot token, then the file is fetched from the /file/ path.
    assert seen[0] == "https://tg.test/bot12345:ABC/getFile?file_id=FILE123"
    assert seen[1] == "https://tg.test/file/bot12345:ABC/docs/x.pdf"


def test_send_message_with_buttons_shapes_inline_keyboard() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bot12345:ABC/sendMessage"
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    _client(handler).send_message(
        chat_id=900,
        text="pilih rekening",
        buttons=[
            InlineButton("BCA · ****1", "acct:900:42:1"),
            InlineButton("BCA · ****2", "acct:900:42:2"),
        ],
    )
    assert captured["chat_id"] == 900
    assert captured["text"] == "pilih rekening"
    assert captured["reply_markup"] == {
        "inline_keyboard": [
            [{"text": "BCA · ****1", "callback_data": "acct:900:42:1"}],
            [{"text": "BCA · ****2", "callback_data": "acct:900:42:2"}],
        ]
    }


def test_send_message_without_buttons_omits_reply_markup() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    _client(handler).send_message(chat_id=900, text="halo")
    assert "reply_markup" not in captured


def test_delete_message_and_answer_callback_post_expected_methods() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    client.delete_message(chat_id=900, message_id=42)
    client.answer_callback_query("CB1")
    assert calls[0] == ("/bot12345:ABC/deleteMessage", {"chat_id": 900, "message_id": 42})
    assert calls[1] == ("/bot12345:ABC/answerCallbackQuery", {"callback_query_id": "CB1"})


def test_pending_store_put_pop_roundtrip_and_single_use() -> None:
    store = InMemoryPendingUploadStore()
    upload = PendingUpload(file_id="F1", chat_id=900, message_id=42, telegram_user_id=111)
    store.put("900:42", upload)
    assert store.pop("900:42") == upload
    assert store.pop("900:42") is None  # consumed — not replayable
