# Coffer — Operations (S15)

Runbook for self-hosting Coffer on the home server / TrueNAS SCALE box. Covers the
production service (API + built SPA on one origin), the restic backup pipeline, disaster
recovery, and the monthly reconciliation spot check. Public surface is the Telegram
webhook only; everything else stays on LAN/VPN (SPEC §5).

---

## 1. Environment

Nothing secret is hardcoded (SPEC §6) — everything is read from the environment. Keep
these in a root-only file (e.g. `/etc/coffer/coffer.env`, `chmod 600`), sourced by the
systemd units / cron below. **Do not commit it** (`.env*` is gitignored).

| Variable | Purpose |
|---|---|
| `COFFER_DATABASE_URL` | `postgresql+psycopg://user:pw@host/coffer` |
| `COFFER_ENCRYPTION_KEY` | Fernet key (urlsafe-base64, 32 bytes) for at-rest field encryption |
| `COFFER_STATEMENT_ARCHIVE_DIR` | Where encrypted statement originals are retained (default `statement_archive`) |
| `COFFER_WEB_DIST_DIR` | Built SPA dir to serve in prod (see §2). Unset ⇒ API-only |
| `COFFER_TELEGRAM_BOT_TOKEN` | Telegram bot token (ingestion + optional reminder ping) |
| `COFFER_TELEGRAM_WEBHOOK_SECRET` | Secret token verified on every webhook request |
| `RESTIC_REPOSITORY`, `RESTIC_PASSWORD_FILE` | The household restic repo + its password file |
| `COFFER_SPOT_CHECK_MARKER` | ISO-date file of the last manual spot check (default `<archive>/spot_check.last`) |
| `COFFER_TELEGRAM_REMINDER_CHAT_ID` | *(optional)* chat to ping for the spot-check reminder |
| `COFFER_RESTORE_TEST_DB_URL` | *(optional)* scratch DB for the restore drill (§4) |

---

## 2. Production service (API + SPA on one origin)

In development the SPA runs under Vite (`npm run dev`, proxying `/api` → `:8000`). In
production there is no Vite: build the bundle once and let the API process serve it, so
the dashboard and API share one LAN origin.

> The ASGI server is `uvicorn`, a pinned project dependency — `uv sync` installs it; no
> extra step in the deployment environment.

```bash
# Build the SPA (produces web/dist)
cd web && npm ci && npm run build

# Point the API at the build and run it (LAN/VPN bind only — never 0.0.0.0 on WAN)
export COFFER_WEB_DIST_DIR="$PWD/dist"
cd .. && uv run uvicorn coffer.api.app:app --host 127.0.0.1 --port 8000
```

With `COFFER_WEB_DIST_DIR` set to a real build, `create_app()` mounts the SPA
(`coffer/api/static.py`): `/` and unknown deep links return `index.html`, `/assets/*`
serve content-hashed bundles, and the `/api` namespace is never shadowed. Unset (dev +
tests), the app is API-only and unchanged.

Put it behind the LAN reverse proxy / VPN; only the Telegram webhook path is exposed
publicly (via the tunnel, secret-token verified). A minimal systemd unit:

```ini
# /etc/systemd/system/coffer-api.service
[Service]
EnvironmentFile=/etc/coffer/coffer.env
WorkingDirectory=/opt/coffer
ExecStart=/opt/coffer/.venv/bin/uvicorn coffer.api.app:app --host 127.0.0.1 --port 8000
Restart=on-failure
[Install]
WantedBy=multi-user.target
```

---

## 3. Backup — `scripts/backup.sh`

Adds the two things that hold the ledger to a **restic** repo — a local disk (e.g. a
TrueNAS SCALE box) **or a cloud bucket** (see §3a; the script is backend-agnostic, so the
target is pure config). Either way the two items backed up are:

1. **Preflight audit** — `python -m coffer.api.ops audit "$ARCHIVE_DIR"`. Aborts the run
   if any plaintext PDF or unexpected file is in the archive. The backup **never**
   contains a plaintext PDF (CLAUDE.md; SPEC §4/§7).
2. **Database** — `pg_dump --format=custom | restic backup --stdin`. Streamed, so no
   plaintext dump is ever written to local disk; restic encrypts the repo at rest.
   `institution_credential.password_enc` is already Fernet ciphertext in the DB.
3. **Encrypted statement originals** — `restic backup "$ARCHIVE_DIR"`.
4. **Retention** — `restic forget --keep-daily 7 --keep-weekly 5 --keep-monthly 12 --prune`.
5. **Spot-check reminder** — see §5.

Run nightly. A systemd timer (or a cron line):

```ini
# /etc/systemd/system/coffer-backup.service
[Service]
Type=oneshot
EnvironmentFile=/etc/coffer/coffer.env
ExecStart=/opt/coffer/scripts/backup.sh
```
```ini
# /etc/systemd/system/coffer-backup.timer
[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
[Install]
WantedBy=timers.target
```

```cron
# …or plain cron:
30 2 * * *  root  . /etc/coffer/coffer.env; /opt/coffer/scripts/backup.sh >> /var/log/coffer-backup.log 2>&1
```

### 3a. Cloud backup target (no local NAS)

`backup.sh` / `restore-verify.sh` only ever call `restic backup|forget|check|restore` — all
**backend-agnostic**. Moving the repo to the cloud is therefore a **config change, not a code
change**: point `RESTIC_REPOSITORY` at a cloud URL and add that backend's credentials to the
`EnvironmentFile` (`/etc/coffer/coffer.env`, mode `600` — never the repo). Nothing in the
pipeline changes.

Why this is safe for real financial data: **restic encrypts client-side.** The repo is
encrypted with `RESTIC_PASSWORD_FILE` *before* a byte leaves the box, so the provider only
ever stores ciphertext — this satisfies Coffer's encrypted-only invariant (SPEC §4/§7) by
construction, and makes cloud **data residency largely moot** (no provider can read the ledger
regardless of region). At a two-person household's scale (statements + a Postgres dump — well
under 1 GB even with history), storage cost is pennies-to-zero on any option below.

**One-time, for any backend:** create the bucket/remote, export the vars, then
`restic init` once to create the encrypted repo. Use the **same** `RESTIC_PASSWORD_FILE` you
already use — and see the resilience note at the end.

**Option A — Backblaze B2** (recommended: simplest restic-native path; 10 GB free tier):
```bash
# coffer.env (mode 600)
export RESTIC_REPOSITORY="b2:coffer-backup:"      # your B2 bucket name
export B2_ACCOUNT_ID="<application keyID>"
export B2_ACCOUNT_KEY="<application key>"
export RESTIC_PASSWORD_FILE=/etc/coffer/restic.pass
# one-time: restic init
```

**Option B — Cloudflare R2** (S3-compatible; 10 GB free; **zero egress fees** → cheapest restores):
```bash
export RESTIC_REPOSITORY="s3:https://<accountid>.r2.cloudflarestorage.com/coffer-backup"
export AWS_ACCESS_KEY_ID="<R2 access key id>"
export AWS_SECRET_ACCESS_KEY="<R2 secret access key>"
export AWS_DEFAULT_REGION="auto"                  # R2 ignores region; restic's S3 client wants one set
export RESTIC_PASSWORD_FILE=/etc/coffer/restic.pass
# one-time: restic init
```

**Option C — reuse an account you already pay for** (Google Drive / Dropbox / OneDrive, via rclone):
```bash
rclone config                                     # one-time: create a remote, e.g. "gdrive" (OAuth)
export RESTIC_REPOSITORY="rclone:gdrive:coffer-backup"
export RESTIC_PASSWORD_FILE=/etc/coffer/restic.pass
# one-time: restic init   (restic shells out to rclone; the rclone token lives in ~/.config/rclone)
```

**Verify** the same way regardless of backend: `scripts/restore-verify.sh` (§4) runs
`restic check` + a real restore against whatever `RESTIC_REPOSITORY` points at.

> **Resilience (read this).** Dropping the NAS makes the cloud repo your **only** copy, so:
> 1. **Back up the restic repo password** (the contents of `RESTIC_PASSWORD_FILE`) in a
>    password manager. Lose it and the backup is unrecoverable — there is no reset.
> 2. Prefer keeping **one more copy** occasionally (an external drive, or a second
>    `restic backup` to a different repo) so a single provider outage/lockout isn't total loss
>    — the 3-2-1 rule. `backup.sh` can be run a second time against a second `RESTIC_REPOSITORY`.

---

## 4. Disaster recovery — `scripts/restore-verify.sh`

A backup you have never restored is a hope. This drill (run monthly, and after any
pipeline change) proves the repo is intact and the dump is restorable **without touching
the live DB**: `restic check` → restore the latest DB-dump snapshot → `pg_restore --list`
it. Set `COFFER_RESTORE_TEST_DB_URL` (a scratch DB — **never** production) for a full
restore-into-DB + row-count check.

```bash
. /etc/coffer/coffer.env
scripts/restore-verify.sh
```

Full real recovery: restore `coffer-db.dump` from restic, `pg_restore` into a fresh
Postgres, restore `statement_archive/` from restic, set `COFFER_ENCRYPTION_KEY` to the
**same** Fernet key (without it the at-rest `.pdf.enc` originals and `password_enc`
cannot be decrypted — back the key up separately, offline).

---

## 5. Monthly reconciliation spot check (SPEC §7)

Statements lag reality, so Coffer must not present stale numbers as current truth. The
backup emits a reminder when a spot check is due (`spot_check_due`, default 30 days):
reconcile the dashboard against BCA mobile / Ajaib / Stockbit, then record the date:

```bash
date -u +%Y-%m-%d > "$COFFER_STATEMENT_ARCHIVE_DIR/spot_check.last"
```

If `COFFER_TELEGRAM_BOT_TOKEN` + `COFFER_TELEGRAM_REMINDER_CHAT_ID` are set the reminder
is sent to Telegram; otherwise it is logged by the backup run.

---

## 6. Telegram webhook (recap, SPEC §5)

The only public surface. Register it behind the tunnel with the secret token:

```bash
curl -fsS "https://api.telegram.org/bot${COFFER_TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=https://<public-tunnel-host>/api/telegram/webhook" \
  --data-urlencode "secret_token=${COFFER_TELEGRAM_WEBHOOK_SECRET}"
```
