---
name: fastapi-clean
description: Build Coffer's FastAPI ingestion API and Telegram webhook as humble adapters over domain use-cases. Use when writing or reviewing S9 (upload endpoint orchestrating decrypt→parse→validate→dedup→persist→recompute) or S10 (Telegram webhook). Covers dependency injection to use-cases, Pydantic only at the edge, webhook secret-token verification, server-side allowlist, and keeping business logic out of routers.
---

# FastAPI — Coffer ingestion API & Telegram bot (S9/S10)

The api layer **orchestrates use-cases**; it holds no business logic. Routers are Humble
Objects: parse the request, call a use-case, shape the response. Money/categorization/
reconciliation all live in domain/ingestion (see [[clean-architecture]]).

## Pydantic at the edge only

Pydantic models validate/serialize HTTP; they are **not** domain entities. Convert at the
boundary. Money crosses the wire as string/int, becomes `Decimal` in the domain, and is
formatted `id-ID` only in the web layer — never in api/domain.

## Dependency injection to use-cases

```python
from fastapi import APIRouter, Depends, UploadFile

router = APIRouter()

def get_ingest_uc() -> IngestStatement:            # wire concrete repos/stages here
    return IngestStatement(decryptor=..., parsers=..., repo=..., recompute=...)

@router.post("/statements")
async def upload(file: UploadFile, uc: IngestStatement = Depends(get_ingest_uc)) -> IngestResult:
    data = await file.read()
    outcome = uc.execute(data)        # decrypt→parse→validate→dedup→persist→recompute
    return IngestResult(new=outcome.new, duplicate=outcome.dup,
                        needs_account=outcome.needs_account, needs_password=outcome.needs_password)
```

The endpoint does no parsing itself. Response surfaces new/dup/needs-account/needs-password
counts (S9). Recompute is **serialized per household** — the use-case takes the lock, not the
router.

## Telegram webhook (S10) — security is server-side

```python
from fastapi import Header, HTTPException, Request

@router.post("/tg/webhook")
async def telegram(req: Request,
                   x_telegram_bot_api_secret_token: str = Header(default="")):
    if not hmac.compare_digest(x_telegram_bot_api_secret_token, settings.tg_secret):
        raise HTTPException(403)                     # verify the secret token first
    update = await req.json()
    user_id = update.get("message", {}).get("from", {}).get("id")
    if user_id not in settings.tg_allowlist:         # allowlist enforced HERE, server-side
        raise HTTPException(403)
    ...
    # after successful ingest: delete the source message (it holds statement + maybe password)
```

- **Verify the secret token** (`X-Telegram-Bot-Api-Secret-Token`) with `hmac.compare_digest`.
- **Enforce the `telegram_user_id` allowlist server-side** — never trust client-side.
- **Delete the source message after successful ingest** — it may contain the PDF/password.
- **Never log** the message content or password.
- Public surface is the **webhook only** (via tunnel); the dashboard/API stays LAN/VPN.

## Config & secrets
- Settings from env (`pydantic-settings`), never hardcoded. DB URL, TG secret, allowlist,
  institution credentials all come from the environment / secret store.

## Testing
- Test the use-case directly (fast, no HTTP). Test routers with `TestClient` for wiring:
  a valid upload returns the right counts; a bad secret token → 403; a non-allowlisted
  `user_id` → 403; a duplicate upload reports `duplicate`, not an error.
- Keep networking behind an owned client for the Telegram send/delete calls
  (see [[urlsession-networking]] analogue: own the boundary), and pair with [[tdd]].
```
