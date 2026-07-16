"""S15 — production static serving of the built SPA (`coffer/api/static.py`).

In dev the frontend runs under Vite (proxying ``/api``); in production the API process
serves the built ``web/dist`` bundle so there is one origin on the LAN. This proves the
mount:

  * ``/`` and unknown deep links return ``index.html`` (client-side routing fallback),
  * hashed assets under ``/assets`` are served with the right content type,
  * the ``/api`` namespace is never shadowed by the SPA fallback,
  * ``create_app`` only mounts when ``COFFER_WEB_DIST_DIR`` points at a real build, so
    the API-only default (dev + every other test) is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coffer.api.app import create_app
from coffer.api.static import mount_spa


def _dist(root: Path) -> Path:
    (root / "assets").mkdir()
    (root / "index.html").write_text("<!doctype html><title>Coffer</title><div id=root></div>")
    (root / "assets" / "app-a1b2c3.js").write_text("console.log('coffer')")
    (root / "favicon.ico").write_bytes(b"\x00icon")
    return root


def _client(dist: Path) -> TestClient:
    app = create_app()
    mount_spa(app, dist)
    return TestClient(app)


def test_serves_index_at_root(tmp_path: Path) -> None:
    response = _client(_dist(tmp_path)).get("/")
    assert response.status_code == 200
    assert "Coffer" in response.text


def test_serves_hashed_asset_with_js_mime(tmp_path: Path) -> None:
    response = _client(_dist(tmp_path)).get("/assets/app-a1b2c3.js")
    assert response.status_code == 200
    assert "console.log('coffer')" in response.text
    assert "javascript" in response.headers["content-type"]


def test_serves_root_level_file(tmp_path: Path) -> None:
    response = _client(_dist(tmp_path)).get("/favicon.ico")
    assert response.status_code == 200


def test_spa_deep_link_falls_back_to_index(tmp_path: Path) -> None:
    # A client-side route (e.g. the Portofolio tab) that is not a real file → index.html.
    response = _client(_dist(tmp_path)).get("/portofolio")
    assert response.status_code == 200
    assert "Coffer" in response.text


def test_api_namespace_is_not_shadowed_by_the_spa(tmp_path: Path) -> None:
    response = _client(_dist(tmp_path)).get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert "Coffer" not in response.text  # a 404, not the SPA shell


def test_create_app_has_no_spa_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COFFER_WEB_DIST_DIR", raising=False)
    response = TestClient(create_app()).get("/")
    assert response.status_code == 404  # no SPA mounted; root is not an API route


def test_create_app_mounts_spa_when_env_points_at_a_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dist(tmp_path)
    monkeypatch.setenv("COFFER_WEB_DIST_DIR", str(tmp_path))
    response = TestClient(create_app()).get("/")
    assert response.status_code == 200
    assert "Coffer" in response.text


def test_create_app_ignores_env_pointing_at_a_missing_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Env set but no index.html built yet → API-only, no crash on import/create.
    monkeypatch.setenv("COFFER_WEB_DIST_DIR", str(tmp_path / "empty"))
    assert TestClient(create_app()).get("/").status_code == 404
