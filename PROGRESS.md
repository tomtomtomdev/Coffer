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
- **S1 remaining parsers.** Samples received (in `~/Downloads`, gitignored). None encrypted.
  - ✅ `bca_kartu_kredit` — commit `f202fb4` (see Done).
  - 🚧 `ajaib_portfolio` + `stockbit_soa` — anonymized fixtures **captured** (commit `5dec9e5`);
    parsers **blocked on a contract-shape decision** (see Blockers). Both are holdings
    snapshots with printed Total rows (Σ market value == Total — a real structural check);
    NO opening/closing balance and NO balance-continuity reconcile (soft lot continuity, §3.2).
    Stockbit also carries a cash SOA (dividends) alongside its PORTFOLIO STATEMENT.
  - ⛔ `bca_tapres` — **still no sample** (not in this batch). Same contract as `bca_tahapan`.

## Done (this session, added to S1) ✅
- **`bca_kartu_kredit` (BCA credit card)** — commit `f202fb4`. Multi-card statement (VISA +
  BCA Everyday under one NOMOR CUSTOMER); merges line items; reconciles Σ SALDO SEBELUMNYA +
  Σcharges − Σcredits == TAGIHAN BARU. Dot-thousand money; DD-MMM dates w/ year inference.
  NOMOR CUSTOMER links the savings-side KARTU KREDIT/PL payment (§3.3). 10 tests green.
- **`bca_tahapan` (BCA savings)** — commit `973a1f9`. Multi-line mutasi across 6 pages;
  statement-level reconcile (SALDO AWAL + ΣCR − ΣDB == SALDO AKHIR) + MUTASI CR/DB total+count
  gates; structured counterparty extraction by transfer sub-type. 14 tests green.
  - **Contract generalized:** `statement_balance`/`minimum_payment`/`overdue_minimum`/`due_date`
    are now `| None` (savings leaves them None); `opening/closing_balance` shared. CIMB unaffected.
  - **Cross-statement link found:** the `KARTU KREDIT/PL` debit (2,177,067.00) equals the BCA CC
    `TAGIHAN BARU` — the §3.3 intra-account payment link; `counterparty_acct` = the CC number.

## Next up (suggested order)
1. **S1 remaining parsers** — `bca_kartu_kredit` → `ajaib_portfolio` → `stockbit_soa` (samples in
   hand); `bca_tapres` still blocked on a sample.
2. **S2 — decryption stage** — build the `static` path; blocked on CIMB scheme for end-to-end.
3. **S4 — persistence layer** (no external blocker; depends only on S0).

## Live decisions
- Money is `Decimal` end-to-end; `id-ID` formatting only at the UI edge.
- Learned rules match structured fields (recipient acct / amount), never description regex.
- Intra-household (Tommy↔Priskila) transfers auto-`transfer` and net out at household level.
- Retention: encrypted original only; plaintext never on disk; reparse re-decrypts.

## Blockers (need Tommy)
- ⛔ **Portfolio contract shape** — `ParsedStatement` forces `opening_balance`/`closing_balance`
  + a balance reconcile, which portfolio snapshots (Ajaib/Stockbit) don't have. Decide: a
  separate `ParsedPortfolio` type (recommended) vs. extending `ParsedStatement` with an
  optional `holdings` list. Unblocks `ajaib_portfolio` + `stockbit_soa`.
- ⛔ **`bca_tapres` sample** — needed to build that parser (same contract as `bca_tahapan`).
- ⛔ **CIMB password scheme** (static/derived/per_statement) — unblocks S2 end-to-end.
- ⛔ **§3.4 bill-aggregator placement** — card on Ringkasan (recommended) vs. 5th tab — confirm before S11.
- ⛔ **Samples**: BCA CC, BCA savings, Ajaib, Stockbit — unblock remaining S1 parsers.
- ⚠️ **CIMB edge cases**: no cash-advance / multi-card / multi-page statement seen yet.
