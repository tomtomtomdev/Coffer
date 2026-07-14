"""Telegram webhook — a Humble Object over ``TelegramIngest`` (SPEC §4/§5).

The only publicly-exposed surface (via a tunnel); the dashboard/API stays on LAN/VPN.
So this endpoint's first job is authenticity: it verifies Telegram's secret token
(``X-Telegram-Bot-Api-Secret-Token``) with a constant-time compare before doing anything
else. It then parses the ``Update`` and dispatches to the use-case. No allowlist,
detection, decryption or ingest logic here — that all lives behind the injected use-case
(the allowlist is enforced server-side inside it).

The handler always answers ``200 {"ok": true}`` for an authentic request so Telegram does
not retry; unauthenticated requests get ``403``.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from coffer.api.dependencies import get_telegram_use_case, get_webhook_secret
from coffer.ingestion.telegram import TelegramIngest

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

_PDF_MIME = "application/pdf"


# ── edge models (a minimal slice of the Telegram ``Update`` schema) ──────────────────
class _TgUser(BaseModel):
    id: int


class _TgChat(BaseModel):
    id: int


class _TgDocument(BaseModel):
    file_id: str
    file_name: str | None = None
    mime_type: str | None = None


class _TgMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: int
    chat: _TgChat
    # ``from`` is a Python keyword — read it via an alias.
    from_: _TgUser | None = Field(default=None, alias="from")
    document: _TgDocument | None = None


class _TgCallbackQuery(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_: _TgUser = Field(alias="from")
    data: str | None = None
    message: _TgMessage | None = None


class TelegramUpdate(BaseModel):
    update_id: int
    message: _TgMessage | None = None
    callback_query: _TgCallbackQuery | None = None


def verify_telegram_secret(
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    expected: str = Depends(get_webhook_secret),
) -> None:
    """Reject anything without the exact secret token (constant-time compare, SPEC §5)."""
    if (
        not expected
        or x_telegram_bot_api_secret_token is None
        or not hmac.compare_digest(x_telegram_bot_api_secret_token, expected)
    ):
        raise HTTPException(status_code=403, detail="invalid secret token")


def _is_pdf(document: _TgDocument) -> bool:
    if document.mime_type == _PDF_MIME:
        return True
    return (document.file_name or "").lower().endswith(".pdf")


@router.post("/webhook")
def telegram_webhook(
    update: TelegramUpdate,
    _: None = Depends(verify_telegram_secret),
    use_case: TelegramIngest = Depends(get_telegram_use_case),
) -> dict[str, bool]:
    message = update.message
    if (
        message is not None
        and message.from_ is not None
        and message.document is not None
        and _is_pdf(message.document)
    ):
        use_case.handle_document(
            telegram_user_id=message.from_.id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            file_id=message.document.file_id,
        )
        return {"ok": True}

    callback = update.callback_query
    if callback is not None and callback.data is not None and callback.message is not None:
        use_case.handle_callback(
            telegram_user_id=callback.from_.id,
            callback_query_id=callback.id,
            callback_data=callback.data,
            chat_id=callback.message.chat.id,
        )
        return {"ok": True}

    # A non-PDF document, a plain text message, an edited message, etc. — ack and ignore.
    return {"ok": True}
