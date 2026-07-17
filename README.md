# Coffer

Private, self-hosted household finance consolidator for a two-person household.
Coffer parses Indonesian bank and broker statements (CIMB, BCA, Ajaib, Stockbit) and
surfaces **net worth, portfolio, routine spend, and cash flow** — all in one place, on
your own hardware.

Real financial data lives here, so **security and correctness are non-negotiable**:
statement passwords are never logged, plaintext PDFs never touch disk, and every parser
raises rather than emitting partial data.

> **Status:** feature-complete — all planned slices **S0–S15** are done: six statement
> parsers, the full ingestion pipeline, web + Telegram upload, all four Bahasa dashboards,
> and the backup/ops pipeline. What remains is operator setup, not code (see
> [`docs/OPERATIONS.md`](docs/OPERATIONS.md)). [`PROGRESS.md`](PROGRESS.md) has the live
> state of every slice.

---

## Why

Statements arrive monthly as password-protected PDFs across several institutions. Coffer
ingests them (via web upload or a Telegram bot), reconciles balances, categorizes
transactions, nets out intra-household transfers, and recomputes a month-end net-worth
grid — then presents four Bahasa Indonesia dashboards: Ringkasan, Portofolio, Belanja,
and Arus Kas.

## Architecture

Clean Architecture — **dependencies point inward only**. The rule is enforced in CI by
`import-linter`; a violating import fails the build.

```
web  →  api  →  ingestion  →  persistence  →  parsers  →  domain
(UI)   (FastAPI +   (decrypt,      (Postgres     (pure        (entities,
        Telegram)    validate,      repos)         statement    use-cases;
                     dedup,                        parsers)     depends on
                     categorize,                                nothing)
                     recompute)
```

| Layer | Responsibility |
|-------|----------------|
| `coffer/domain` | Entities, value objects, repository *interfaces*, use-case logic. Imports no other layer. |
| `coffer/parsers` | Pure functions: decrypted text/stream → `ParsedStatement` / `ParsedPortfolio`. Import only `domain` types. |
| `coffer/persistence` | Postgres repos implementing domain interfaces. |
| `coffer/ingestion` | Pipeline stages: decrypt → validate → dedup → categorize → recompute. |
| `coffer/api` | FastAPI endpoints + Telegram bot. Orchestrates use-cases. |
| `coffer/web` | Dashboard UI (frozen design). Depends on API contracts only. |

Business logic lives in `domain` / `ingestion` — never in parsers, repos, or UI.

## Non-negotiable invariants

- **Money is `Decimal` end-to-end.** Never float. `id-ID` currency formatting happens only
  at the UI edge.
- **Parsers are pure and raise, never return partial data.** Structural mismatch →
  `StatementParseError`; balance mismatch → `BalanceReconciliationError`.
- **Balance continuity is a hard gate.** Cash: `saldo_awal + Σmutasi == saldo_akhir`.
  Credit card: `opening + Σcharges − Σcredits == closing == Tagihan Baru`. Portfolio lot
  continuity is soft (corporate actions are legitimate discontinuities).
- **Plaintext PDFs never touch disk.** Decrypt in memory (`pikepdf` → `BytesIO`); persist
  only the encrypted original + parsed data + hashes.
- **Never log** statement passwords or raw statement content.
- **Never commit** real PII, account numbers, or PDFs. Fixtures are anonymized — amounts
  and dates are kept real so reconciliation is genuine; PII is stripped.

## Parsers

All six statement/portfolio parsers are built and reconcile against real (anonymized) samples:

| Parser | Institution / product | Gate |
|--------|-----------------------|------|
| `cimb_kartu_kredit` | CIMB Niaga credit card | opening + charges − credits == Tagihan Baru |
| `bca_kartu_kredit` | BCA credit card (multi-card) | same, merged across cards |
| `bca_tahapan` | BCA Tahapan savings | saldo_awal + ΣCR − ΣDB == saldo_akhir |
| `bca_tapres` | BCA Tapres (used as broker RDN) | same (shares `_bca_rekening_koran` engine) |
| `ajaib_portfolio` | Ajaib portfolio | Σ market_value == printed Total |
| `stockbit_soa` | Stockbit statement of account | Σ market_value == printed Total |

`bca_tahapan` and `bca_tapres` are thin adapters over a shared BCA Rekening Koran engine.

## Getting started

### One command — install + run

```bash
scripts/dev.sh
```

Installs every dependency (Python via `uv`, the SPA via `npm`), runs the database
migrations, then starts the API (`:8000`) and the Vite dev server (`:5173`, which proxies
`/api`). Ctrl-C stops both. Needs [`uv`](https://docs.astral.sh/uv/), Node.js, and a
reachable Postgres — the script prints a Docker one-liner if `COFFER_DATABASE_URL` is
unset, and auto-generates a dev `COFFER_ENCRYPTION_KEY` into a gitignored `.env`. LAN/VPN
only (SPEC §5). Re-run with `--no-install` for a faster restart.

### Manual setup

Requires **Python 3.12** and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                 # install deps from uv.lock (incl. dev group)
uv run pytest           # run the test suite
```

### The full gate (Definition of Done for every slice)

```bash
uv run ruff check .         # lint
uv run ruff format --check  # format
uv run mypy                 # strict type checking
uv run lint-imports         # Clean Architecture layer contract
uv run pytest               # tests
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs all of the above on every push.

### Frontend (`web/` — dashboard UI)

The dashboard is a React + Vite + TypeScript SPA (Recharts, Vitest) that consumes the
read API. It lives at top-level `web/` (a JS SPA is not a Python import layer).

```bash
cd web
npm install
npm run test        # vitest
npm run typecheck   # tsc --noEmit
npm run build       # production bundle → web/dist
npm run dev         # dev server on :5173, proxies /api → http://localhost:8000
```

Run the API alongside it: `uv run uvicorn coffer.api.app:app --reload` (LAN/VPN only, SPEC §5).
In **production** there is no Vite: `npm run build`, then point the API at the bundle with
`COFFER_WEB_DIST_DIR=web/dist` and it serves the SPA on the same origin (SPA deep-link
fallback; `/api` never shadowed — `coffer/api/static.py`). See [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Development workflow

Coffer is built in **vertical slices** (TDD: red → green → refactor), one at a time, in
dependency order. Before touching code:

1. Read [`PROGRESS.md`](PROGRESS.md) — persistent memory across sessions (what's done,
   in progress, next).
2. Read [`spec.md`](spec.md) for the behavior of your slice, and [`PLAN.md`](PLAN.md) for order.
3. Work exactly one slice; write the failing test first.
4. Run the full gate; update `PROGRESS.md`.

See [`CLAUDE.md`](CLAUDE.md) for the complete operating rules.

## Project layout

```
coffer/          Application package (the six Clean Architecture layers above)
web/             React + Vite + TypeScript dashboard SPA (consumes the read API)
tests/           Pytest suite + anonymized fixtures (tests/fixtures/)
scripts/         dev.sh (install + run), backup.sh, restore-verify.sh
migrations/      Alembic migrations
docs/            OPERATIONS.md — deployment runbook
spec.md          Source of truth for behavior
PLAN.md          Execution order (slices S0–S15)
PROGRESS.md      Live state — read first, update last
CLAUDE.md        Operating rules
pyproject.toml   uv deps, ruff, mypy, pytest, import-linter config
design_handoff_coffer_dashboard/   Frozen hi-fi design + tokens
```

## Deployment & operations

See [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the full runbook (env reference,
systemd units, backup/restore, spot check).

- Public surface is the Telegram webhook only (via tunnel, secret-token verified,
  server-side `telegram_user_id` allowlist).
- Dashboard/API stay on LAN/VPN; the API serves the built SPA (`COFFER_WEB_DIST_DIR`).
- Backups (`scripts/backup.sh`): DB (streamed `pg_dump`) + **encrypted** statement
  originals into the existing TrueNAS SCALE + restic pipeline, with an encrypted-only
  preflight audit — the backup never contains a plaintext PDF. Monthly restore drill
  (`scripts/restore-verify.sh`) + reconciliation spot-check reminder.

---

Private project — not licensed for redistribution.
