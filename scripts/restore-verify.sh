#!/usr/bin/env bash
#
# Coffer restore verification — S15 (SPEC §7 "disaster recovery").
#
# A backup you have never restored is a hope, not a backup. This drill proves the restic
# repository is intact and the DB dump is restorable, WITHOUT touching the live database:
#   1. `restic check` — verify repository integrity.
#   2. Restore the latest DB-dump snapshot to a temp dir.
#   3. `pg_restore --list` the dump — proves it is a valid, complete custom-format dump.
#   4. (Optional) if COFFER_RESTORE_TEST_DB_URL is set, actually restore into that scratch
#      database and count a few tables as an end-to-end check.
#
# Never point COFFER_RESTORE_TEST_DB_URL at the production database.
#
# Configuration:
#   RESTIC_REPOSITORY, RESTIC_PASSWORD_FILE   (as in backup.sh)
#   COFFER_RESTORE_TEST_DB_URL  optional scratch DB, e.g. postgresql://u:pw@host/coffer_restore_test
#
# Usage:  scripts/restore-verify.sh    (run monthly, or after any pipeline change)

set -euo pipefail

log() { printf '[coffer-restore %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { printf '[coffer-restore] ERROR: %s\n' "$*" >&2; exit 1; }

: "${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY}"
: "${RESTIC_PASSWORD_FILE:?set RESTIC_PASSWORD_FILE}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

log "1/4 verifying restic repository integrity"
restic check

log "2/4 restoring latest DB-dump snapshot"
restic restore latest --tag coffer-db --target "$WORK"
DUMP="$(find "$WORK" -name coffer-db.dump -type f | head -n1)"
[[ -n "$DUMP" ]] || die "restored snapshot did not contain coffer-db.dump"
log "restored: $DUMP ($(du -h "$DUMP" | cut -f1))"

log "3/4 validating the dump (pg_restore --list)"
pg_restore --list "$DUMP" >/dev/null || die "dump is not a valid custom-format archive"
TABLES="$(pg_restore --list "$DUMP" | grep -c ' TABLE ' || true)"
log "dump lists $TABLES tables"

if [[ -n "${COFFER_RESTORE_TEST_DB_URL:-}" ]]; then
  log "4/4 restoring into scratch DB $COFFER_RESTORE_TEST_DB_URL"
  SCRATCH="${COFFER_RESTORE_TEST_DB_URL/+psycopg/}"
  pg_restore --clean --if-exists --no-owner --no-privileges --dbname "$SCRATCH" "$DUMP"
  ACCT_COUNT="$(psql "$SCRATCH" -tAc 'select count(*) from account')"
  log "scratch DB restored — account rows: $ACCT_COUNT"
else
  log "4/4 skipped (set COFFER_RESTORE_TEST_DB_URL to a scratch DB for an end-to-end restore)"
fi

log "restore verification OK"
