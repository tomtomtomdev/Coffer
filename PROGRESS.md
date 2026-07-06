# Coffer — PROGRESS

> Persistent memory across cold sessions. Read this first. Update it last.
> Format: what's done, what's in progress, what's next, and any live decisions/blockers.

_Last updated: 2026-07-06_

## Where things stand
- `SPEC.md` — stable. All §8 decisions resolved except the CIMB password scheme.
- Visual target — **frozen** (Claude Design hi-fi handoff, 4 views + tokens + `id-ID` locale).
- Naming — app is **Coffer**; Python package is `coffer/`.
- Repo — Coffer is now its **own git repo** (not the `~/Documents` monorepo). CI = **GitHub
  Actions**; target **Python 3.12**; deps managed by **uv** (`uv.lock` committed).

## Done ✅
- **S0 — scaffold + layer enforcement.** Clean Architecture package layout
  (`coffer/{domain,parsers,ingestion,persistence,api,web}`), `pyproject.toml` (uv),
  ruff + `mypy --strict` + pytest + `import-linter`, GitHub Actions CI (`.github/workflows/ci.yml`),
  `.gitignore` (blocks `*.pdf`, `.env`, secrets). Layer contract (`[tool.importlinter]`) enforces
  outer→inner `web→api→ingestion→persistence→parsers→domain` and is **KEPT**.
  Existing parser moved into `coffer/parsers/`, fixture into `tests/fixtures/`.
  **Full gate green:** ruff · ruff-format · mypy --strict · lint-imports · 7 pytest.
  Commit `584de75`.
- **S1 (partial):** parser contract `coffer/parsers/statement_types.py` (`ParsedStatement`,
  `ParsedTransaction`, error types; `Decimal` money).
- **S1:** `coffer/parsers/cimb_kartu_kredit.py` — built against the real MC GOLD sample.
  - 7 fixture tests green; reconciles `4,247,403.83 + 838,900 − 4,248,000 = 838,303.83`.
  - Accepts path / bytes / stream (so in-memory decryption can hand it a `BytesIO`).
  - Fixture: `tests/fixtures/cimb_mc_gold_2026-03.txt` (anonymized; amounts/dates real).

## In progress 🚧
- None active. Pick the next slice from `PLAN.md`.

## Next up (suggested order)
1. **S1 remaining parsers** — needs real samples: BCA CC, BCA savings, Ajaib, Stockbit.
2. **S2 — decryption stage** — build the `static` path; blocked on CIMB scheme for end-to-end.
3. **S4 — persistence layer** (no external blocker; depends only on S0).

## Live decisions
- Money is `Decimal` end-to-end; `id-ID` formatting only at the UI edge.
- Learned rules match structured fields (recipient acct / amount), never description regex.
- Intra-household (Tommy↔Priskila) transfers auto-`transfer` and net out at household level.
- Retention: encrypted original only; plaintext never on disk; reparse re-decrypts.

## Blockers (need Tommy)
- ⛔ **CIMB password scheme** (static/derived/per_statement) — unblocks S2 end-to-end.
- ⛔ **§3.4 bill-aggregator placement** — card on Ringkasan (recommended) vs. 5th tab — confirm before S11.
- ⛔ **Samples**: BCA CC, BCA savings, Ajaib, Stockbit — unblock remaining S1 parsers.
- ⚠️ **CIMB edge cases**: no cash-advance / multi-card / multi-page statement seen yet.
