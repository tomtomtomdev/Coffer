"""FastAPI application factory (SPEC §5).

The dashboard/API stays on LAN/VPN; only the Telegram webhook (S10) is publicly exposed.
Importing this module requires no environment — the DB/secret config is resolved lazily
inside the request dependencies — so it is safe to import in tests. The one optional read
is ``COFFER_WEB_DIST_DIR``: set to a built ``web/dist`` it serves the SPA in production
(S15); unset (dev + tests) the app is API-only, unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from coffer.api.dashboard_routes import router as dashboard_router
from coffer.api.routes import router
from coffer.api.static import mount_spa
from coffer.api.telegram_routes import router as telegram_router
from coffer.api.transactions_routes import router as transactions_router

WEB_DIST_DIR_ENV = "COFFER_WEB_DIST_DIR"


def create_app() -> FastAPI:
    app = FastAPI(title="Coffer Ingestion API")
    app.include_router(router)
    app.include_router(telegram_router)
    app.include_router(dashboard_router)
    app.include_router(transactions_router)

    # Serve the built SPA only when a real build is configured (production). Mounted
    # last so the catch-all fallback never shadows the API routers above.
    dist = os.environ.get(WEB_DIST_DIR_ENV)
    if dist and (Path(dist) / "index.html").is_file():
        mount_spa(app, Path(dist))
    return app


app = create_app()
