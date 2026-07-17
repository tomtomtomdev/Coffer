#!/usr/bin/env bash
#
# Coffer — one-step local install + run (development).
#
# Installs every dependency (Python via uv, the SPA via npm), runs the database
# migrations, then starts the API and the web dev server together and streams both
# logs. Ctrl-C stops both.
#
#   * API  → uvicorn on 127.0.0.1:8000  (--reload)
#   * UI   → Vite    on localhost:5173  (proxies /api → :8000, per web/vite.config.ts)
#
# LAN/VPN only — never expose this to the WAN (SPEC §5). Once a real
# COFFER_DATABASE_URL is configured it serves and reads REAL financial data.
#
# Prerequisites (install once, yourself):
#   * uv             https://docs.astral.sh/uv/   (manages Python 3.12 + deps)
#   * Node.js + npm  https://nodejs.org            (for the web/ SPA)
#   * A reachable Postgres — the script prints a Docker one-liner if none is configured.
#
# Configuration — read from the environment, or a gitignored `.env` at the repo root:
#   COFFER_DATABASE_URL    postgresql+psycopg://user:pw@host:5432/coffer
#                          (falls back to a local dev URL if unset)
#   COFFER_ENCRYPTION_KEY  Fernet key; a dev key is auto-generated into `.env` if unset
#   COFFER_API_PORT        API port (default 8000)
#
# Usage:
#   scripts/dev.sh                install (idempotent) + migrate + run
#   scripts/dev.sh --no-install   skip dependency install (fast restart)
#   scripts/dev.sh --help

set -euo pipefail

log() { printf '[coffer-dev %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { printf '[coffer-dev] ERROR: %s\n' "$*" >&2; exit 1; }

DEFAULT_DB_URL="postgresql+psycopg://coffer:coffer@localhost:5432/coffer"
DOCKER_PG="docker run --name coffer-pg -e POSTGRES_USER=coffer -e POSTGRES_PASSWORD=coffer -e POSTGRES_DB=coffer -p 5432:5432 -d postgres:16"

DO_INSTALL=1
for arg in "$@"; do
  case "$arg" in
    --no-install) DO_INSTALL=0 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; s/^#$//; /^set -euo/d'; exit 0 ;;
    *) die "unknown argument '$arg' (try --help)" ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Prerequisites ───────────────────────────────────────────────────────────────
need() { command -v "$1" >/dev/null 2>&1 || die "missing '$1' — $2"; }
need uv   "install from https://docs.astral.sh/uv/"
need node "install Node.js from https://nodejs.org"
need npm  "install Node.js (npm ships with it)"

# ── Config (env, then optional .env) ─────────────────────────────────────────────
if [[ -f "$REPO_ROOT/.env" ]]; then
  log "loading .env"
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

# ── Install (idempotent) ─────────────────────────────────────────────────────────
if [[ "$DO_INSTALL" -eq 1 ]]; then
  log "installing Python dependencies (uv sync)"
  uv sync

  log "installing web dependencies (npm install)"
  ( cd "$REPO_ROOT/web" && npm install )
else
  log "skipping dependency install (--no-install)"
fi

# ── Encryption key — generate a dev key if none is set ───────────────────────────
# cryptography (a project dep) is available after `uv sync`. The key is only written
# to the gitignored .env, and for dev it protects only synthetic data.
if [[ -z "${COFFER_ENCRYPTION_KEY:-}" ]]; then
  log "COFFER_ENCRYPTION_KEY unset — generating a dev key into .env"
  KEY="$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  printf 'COFFER_ENCRYPTION_KEY=%s\n' "$KEY" >> "$REPO_ROOT/.env"
  export COFFER_ENCRYPTION_KEY="$KEY"
fi

# ── Database URL — fall back to a local dev default ──────────────────────────────
if [[ -z "${COFFER_DATABASE_URL:-}" ]]; then
  export COFFER_DATABASE_URL="$DEFAULT_DB_URL"
  log "COFFER_DATABASE_URL unset — using dev default: $DEFAULT_DB_URL"
  log "  need a Postgres? run:  $DOCKER_PG"
fi

# ── Migrate ──────────────────────────────────────────────────────────────────────
log "running database migrations (alembic upgrade head)"
if ! uv run alembic upgrade head; then
  die "migrations failed — is Postgres reachable at COFFER_DATABASE_URL?
       start one with:  $DOCKER_PG"
fi

# ── Run both servers ─────────────────────────────────────────────────────────────
API_PORT="${COFFER_API_PORT:-8000}"

cleanup() {
  trap - EXIT INT TERM
  log "shutting down"
  kill "${API_PID:-}" "${WEB_PID:-}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# uvicorn is not a pinned project dependency yet (see docs/OPERATIONS.md); `uv run
# --with uvicorn` provides it ephemerally without mutating the locked environment.
log "starting API on http://127.0.0.1:$API_PORT (uvicorn --reload)"
uv run --with uvicorn uvicorn coffer.api.app:app --host 127.0.0.1 --port "$API_PORT" --reload &
API_PID=$!

log "starting web dev server (vite → http://localhost:5173, proxies /api → :$API_PORT)"
( cd "$REPO_ROOT/web" && npm run dev ) &
WEB_PID=$!

log "Coffer is up → UI http://localhost:5173 · API http://127.0.0.1:$API_PORT   (Ctrl-C to stop)"
wait
