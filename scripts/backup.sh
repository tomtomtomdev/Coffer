#!/usr/bin/env bash
#
# Coffer backup — S15 (SPEC §7).
#
# Backs up the two things that hold the ledger onto the existing TrueNAS SCALE + restic
# repository: (1) the Postgres database, and (2) the retained *encrypted* statement
# originals. Reuse the household's restic pipeline — do not rebuild one.
#
# Security invariants enforced here (CLAUDE.md / SPEC §4, §7):
#   * The backup NEVER contains a plaintext PDF. A preflight audit
#     (`python -m coffer.api.ops audit`) aborts the run if any plaintext or unexpected
#     file is found in the archive.
#   * The Postgres dump is streamed straight into restic (`--stdin`); no plaintext dump
#     is ever written to local disk. restic encrypts the repository at rest.
#   * `institution_credential.password_enc` is already Fernet-encrypted in the DB, so the
#     dump carries ciphertext, not statement passwords.
#
# Configuration (all from the environment — nothing secret is hardcoded, SPEC §6):
#   COFFER_DATABASE_URL         SQLAlchemy URL, e.g. postgresql+psycopg://u:pw@host/coffer
#   COFFER_STATEMENT_ARCHIVE_DIR  archive of encrypted originals (default: statement_archive)
#   COFFER_SPOT_CHECK_MARKER    file holding the ISO date of the last manual spot check
#                               (default: <archive>/spot_check.last)
#   RESTIC_REPOSITORY           restic repo (e.g. /mnt/tank/backups/coffer or an rclone/sftp URL)
#   RESTIC_PASSWORD_FILE        file holding the restic repo password
#   Optional Telegram reminder ping (else the reminder is printed to stderr):
#     COFFER_TELEGRAM_BOT_TOKEN, COFFER_TELEGRAM_REMINDER_CHAT_ID
#
# Retention: keep 7 daily, 5 weekly, 12 monthly snapshots, then prune.
#
# Usage:   scripts/backup.sh
# Cron:    see docs/OPERATIONS.md (a nightly systemd timer / cron entry).

set -euo pipefail

log() { printf '[coffer-backup %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { printf '[coffer-backup] ERROR: %s\n' "$*" >&2; exit 1; }

# Run from the repo root so `python -m coffer.api.ops` resolves.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

: "${COFFER_DATABASE_URL:?set COFFER_DATABASE_URL}"
: "${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY}"
: "${RESTIC_PASSWORD_FILE:?set RESTIC_PASSWORD_FILE}"

ARCHIVE_DIR="${COFFER_STATEMENT_ARCHIVE_DIR:-statement_archive}"
SPOT_CHECK_MARKER="${COFFER_SPOT_CHECK_MARKER:-$ARCHIVE_DIR/spot_check.last}"

# `python` inside the project venv, falling back to `uv run python`.
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  PY="uv run python"
fi

# pg_dump wants a libpq URL — strip the SQLAlchemy "+psycopg" driver tag.
PG_URL="${COFFER_DATABASE_URL/+psycopg/}"

# 1) Preflight: refuse to back up if anything plaintext slipped into the archive.
log "auditing statement archive: $ARCHIVE_DIR"
$PY -m coffer.api.ops audit "$ARCHIVE_DIR" \
  || die "archive audit failed — plaintext/unexpected file present; NOT backing up"

# 2) Database → restic (streamed; no plaintext dump on local disk).
log "backing up database (pg_dump --format=custom | restic --stdin)"
pg_dump --format=custom --no-owner --no-privileges "$PG_URL" \
  | restic backup --stdin --stdin-filename coffer-db.dump --tag coffer --tag coffer-db

# 3) Encrypted statement originals → restic.
if [[ -d "$ARCHIVE_DIR" ]]; then
  log "backing up encrypted statement archive"
  restic backup "$ARCHIVE_DIR" --tag coffer --tag coffer-archive
else
  log "no statement archive yet at $ARCHIVE_DIR — skipping (nothing retained)"
fi

# 4) Retention.
log "applying retention (7 daily / 5 weekly / 12 monthly) + prune"
restic forget --tag coffer --keep-daily 7 --keep-weekly 5 --keep-monthly 12 --prune

# 5) Monthly manual bank-reconciliation spot-check reminder (SPEC §7).
if $PY -m coffer.api.ops spot-check-due "$SPOT_CHECK_MARKER" >/dev/null; then
  MSG="🔎 Coffer: monthly spot check due — reconcile the dashboard against BCA mobile / Ajaib / Stockbit, then run: date -u +%Y-%m-%d > '$SPOT_CHECK_MARKER'"
  if [[ -n "${COFFER_TELEGRAM_BOT_TOKEN:-}" && -n "${COFFER_TELEGRAM_REMINDER_CHAT_ID:-}" ]]; then
    curl -fsS -X POST \
      "https://api.telegram.org/bot${COFFER_TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${COFFER_TELEGRAM_REMINDER_CHAT_ID}" \
      --data-urlencode "text=${MSG}" >/dev/null && log "spot-check reminder sent via Telegram"
  else
    log "REMINDER: $MSG"
  fi
fi

log "done. Snapshots:"
restic snapshots --tag coffer --compact || true
