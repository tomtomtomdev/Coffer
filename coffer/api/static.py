"""Production static serving of the built SPA (S15, SPEC §5).

In development the frontend runs under Vite (its own dev server, proxying ``/api`` →
the API). In production there is no Vite: the API process serves the built
``web/dist`` bundle so the dashboard and API share one LAN/VPN origin.

:func:`mount_spa` adds, *after* the API routers:
  * a ``/assets`` mount for Vite's content-hashed bundles (long-cacheable), and
  * a catch-all that returns a real file when one exists (``/favicon.ico`` etc.) and
    otherwise ``index.html`` — so client-side deep links (``/portofolio``, …) resolve.

The ``/api`` (and ``/assets``) namespaces are never shadowed: they are matched by the
routers/mount registered first, and the catch-all explicitly declines them so an unknown
API path 404s instead of returning the SPA shell.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_spa(app: FastAPI, dist_dir: Path) -> None:
    """Serve the built SPA at ``dist_dir`` from ``app`` (call after ``include_router``)."""
    index = dist_dir / "index.html"
    assets = dist_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa(spa_path: str) -> FileResponse:
        # Never answer API/asset routes here — let them 404 on their own terms rather
        # than masquerade as the SPA shell.
        if spa_path == "api" or spa_path.startswith("api/"):
            raise HTTPException(status_code=404)
        if spa_path == "assets" or spa_path.startswith("assets/"):
            raise HTTPException(status_code=404)
        candidate = dist_dir / spa_path
        if spa_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
