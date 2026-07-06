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
- **S1 essentially complete** — 5 of 6 remaining parsers built this session (see Done).
  Only ⛔ `bca_tapres` is left, **blocked on a sample** (not in the batch; same contract as
  `bca_tahapan` once provided).
- **Deferred (not blocking):** Stockbit cash-SOA dividend rows → `transactions` (feeds §3.5
  income). Portfolio parsers currently extract holdings + cash only.
- **Contract decision taken (portfolio shape):** chose a **separate `ParsedPortfolio`** type
  (not extending `ParsedStatement`) — snapshot with `as_of`, `holdings`, `cash_balance`,
  optional `transactions`; no balance reconcile. Downstream (ingestion/persistence/api) will
  branch on statement-vs-portfolio family. Revisit if a single-type model is preferred.

## Done (this session, added to S1) ✅
- **`ajaib_portfolio` + `stockbit_soa`** — commit `b9d1bb0`. New `ParsedHolding`/`ParsedPortfolio`
  contract. Structural gate = Σ market_value == printed Total (NOT lot continuity, which is
  soft §3.2). Ajaib's real fixture exposed a broker off-by-1 in the printed cost/unrealized
  totals → gate on market value only. Name-wrap handling. 16 tests.
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
1. **S4 — persistence layer** (no external blocker; depends only on S0) — good next slice while
   samples/scheme are gathered. Postgres schema for SPEC §2 incl. `holding`; repo interfaces in
   `domain`, impls in `persistence`; ParsedStatement + ParsedPortfolio both persist.
2. **S2 — decryption stage** — build the `static` path; blocked on CIMB scheme for end-to-end.
3. **S1 tail** — `bca_tapres` (needs sample); Stockbit cash-SOA dividend rows (deferred).

## Live decisions
- Money is `Decimal` end-to-end; `id-ID` formatting only at the UI edge.
- Learned rules match structured fields (recipient acct / amount), never description regex.
- Intra-household (Tommy↔Priskila) transfers auto-`transfer` and net out at household level.
- Retention: encrypted original only; plaintext never on disk; reparse re-decrypts.

## Blockers (need Tommy)
- ⛔ **`bca_tapres` sample** — needed to build that parser (same contract as `bca_tahapan`).
- ⛔ **CIMB password scheme** (static/derived/per_statement) — unblocks S2 end-to-end.
- ℹ️ **Portfolio contract shape** — RESOLVED by best-judgment while away: separate
  `ParsedPortfolio` type (see In progress). Flag if you'd prefer a single-type model.
- ⛔ **§3.4 bill-aggregator placement** — card on Ringkasan (recommended) vs. 5th tab — confirm before S11.
- ⛔ **Samples**: BCA CC, BCA savings, Ajaib, Stockbit — unblock remaining S1 parsers.
- ⚠️ **CIMB edge cases**: no cash-advance / multi-card / multi-page statement seen yet.
