# Coffer

Private, self-hosted household finance consolidator for a two-person household.
Coffer parses Indonesian bank and broker statements (CIMB, BCA, Ajaib, Stockbit) and
surfaces **net worth, portfolio, routine spend, and cash flow** — all in one place, on
your own hardware.

Real financial data lives here, so **security and correctness are non-negotiable**:
statement passwords are never logged, plaintext PDFs never touch disk, and every parser
raises rather than emitting partial data.

> **Status:** backend foundations in progress. See [`PROGRESS.md`](PROGRESS.md) for the
> live state of every slice.

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
tests/           Pytest suite + anonymized fixtures (tests/fixtures/)
spec.md          Source of truth for behavior
PLAN.md          Execution order (slices S0–S15)
PROGRESS.md      Live state — read first, update last
CLAUDE.md        Operating rules
pyproject.toml   uv deps, ruff, mypy, pytest, import-linter config
design_handoff_coffer_dashboard/   Frozen hi-fi design + tokens
```

## Deployment (planned)

- Public surface is the Telegram webhook only (via tunnel, secret-token verified,
  server-side `telegram_user_id` allowlist).
- Dashboard/API stay on LAN/VPN.
- Backups: DB + encrypted originals into the existing TrueNAS SCALE + restic pipeline.

---

Private project — not licensed for redistribution.
