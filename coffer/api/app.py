"""FastAPI application factory (SPEC §5).

The dashboard/API stays on LAN/VPN; only the Telegram webhook (S10) will be publicly
exposed. Importing this module reads no environment — config is resolved lazily inside
the request dependencies — so it is safe to import in tests.
"""

from __future__ import annotations

from fastapi import FastAPI

from coffer.api.dashboard_routes import router as dashboard_router
from coffer.api.routes import router
from coffer.api.telegram_routes import router as telegram_router


def create_app() -> FastAPI:
    app = FastAPI(title="Coffer Ingestion API")
    app.include_router(router)
    app.include_router(telegram_router)
    app.include_router(dashboard_router)
    return app


app = create_app()
