"""Concrete Telegram infrastructure adapters for the ingestion use-case ports.

These implement the ``coffer.ingestion.telegram`` Protocols (``TelegramClient``,
``PendingUploadStore``) with the real Telegram Bot API over httpx + a process-local
pending-upload store. They live in the api (outermost) layer; the use-case depends only
on the Protocols, so the dependency points inward.

Security (CLAUDE.md / SPEC §5): the bot token is a secret and is never logged; raw
statement content is never logged. The token only ever travels in the request URL to
Telegram over HTTPS.
"""

from __future__ import annotations

from typing import Any

import httpx

from coffer.ingestion.telegram import InlineButton, PendingUpload

_TIMEOUT = httpx.Timeout(30.0)


class HttpxTelegramClient:
    """``TelegramClient``: the Telegram Bot API over HTTPS (httpx).

    ``transport`` is a testing seam (an ``httpx.MockTransport`` in unit tests); it is
    ``None`` in production, which uses httpx's default HTTPS transport.
    """

    def __init__(
        self,
        bot_token: str,
        *,
        api_base: str = "https://api.telegram.org",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = bot_token
        self._api = api_base.rstrip("/")
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=_TIMEOUT, transport=self._transport)

    def _method(self, method: str) -> str:
        return f"{self._api}/bot{self._token}/{method}"

    def download_file(self, file_id: str) -> bytes:
        """Two-step Telegram download: resolve ``file_path`` then fetch the bytes."""
        with self._client() as client:
            meta = client.get(self._method("getFile"), params={"file_id": file_id})
            meta.raise_for_status()
            file_path = meta.json()["result"]["file_path"]
            content = client.get(f"{self._api}/file/bot{self._token}/{file_path}")
            content.raise_for_status()
            return content.content

    def send_message(
        self, *, chat_id: int, text: str, buttons: list[InlineButton] | None = None
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": b.text, "callback_data": b.callback_data}] for b in buttons
                ]
            }
        self._post("sendMessage", payload)

    def delete_message(self, *, chat_id: int, message_id: int) -> None:
        self._post("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    def answer_callback_query(self, callback_query_id: str) -> None:
        self._post("answerCallbackQuery", {"callback_query_id": callback_query_id})

    def _post(self, method: str, payload: dict[str, Any]) -> None:
        with self._client() as client:
            client.post(self._method(method), json=payload).raise_for_status()


class InMemoryPendingUploadStore:
    """``PendingUploadStore``: uploads awaiting an account pick, keyed ``chat:message``.

    Process-local (lost on restart) — fine for a 2-person household; a stale pending
    simply asks the user to re-send. Move to Redis/Postgres if the bot ever scales out.
    """

    def __init__(self) -> None:
        self._by_token: dict[str, PendingUpload] = {}

    def put(self, token: str, upload: PendingUpload) -> None:
        self._by_token[token] = upload

    def pop(self, token: str) -> PendingUpload | None:
        return self._by_token.pop(token, None)
