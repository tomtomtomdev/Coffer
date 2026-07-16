# Coffer — PLAN

Vertical slices in dependency order. Each slice is TDD (red → green → refactor),
ends green and committable, and updates `PROGRESS.md`. Work **one slice at a time**.
`SPEC.md` is the source of truth for behavior; this file is the execution order.

Status legend: ✅ done · 🚧 in progress · ⛔ blocked (needs input) · ⬜ todo

**MVP scope (SPEC §7 "definition of done"):** features 3.1, 3.2, 3.3, 3.5, 3.4 +
Telegram ingestion + dedup. Deferred to v2: LLM-assisted categorization (SPEC §6),
budgets/goals, notifications, multi-currency.

---

## Phase A — Backend foundations

### S0 · Scaffold + layer enforcement ✅
- Repo layout for the Clean Architecture layers (see `CLAUDE.md`): `coffer/domain`,
  `coffer/parsers`, `coffer/ingestion`, `coffer/persistence`, `coffer/api`, `coffer/web`.
- Tooling: uv (or poetry), `ruff`, `mypy --strict`, `pytest`, `import-linter` for the
  dependency-direction contract, GitHub Actions CI running lint + types + tests.
- Move existing `parsers/` + `tests/` under the layout; add the four docs.
- **Done when:** `pytest`, `ruff`, `mypy`, and `lint-imports` all pass in CI on an empty-ish tree.

### S1 · Parser layer + statement contract 🚧
- `ParsedStatement` / `ParsedTransaction` / error types — ✅ (`parsers/statement_types.py`).
- `cimb_kartu_kredit.py` — ✅ built, 7 fixture tests green, reconciles on the real sample.
- ⬜ `bca_kartu_kredit.py` (line items + summary, same contract; needs a real BCA CC sample).
- ⬜ `bca_tahapan.py`, `bca_tapres.py` (savings; extract `counterparty_name`/`counterparty_acct`
  from transfer descriptions; continuity `saldo_awal + Σmutasi == saldo_akhir`).
- ⬜ `ajaib_portfolio.py`, `stockbit_soa.py` (holdings; **soft** lot-continuity — corp actions).
- **Test (red first):** per parser, a fixture-based test asserting summary fields, txn
  split, date/year inference, Decimal amounts, and a *tampered-amount → reconciliation raises* case.
- **Done when:** every provided format parses + reconciles; no real PII/PDF committed.
- **Blocked items** need real samples (BCA CC, BCA savings, Ajaib, Stockbit).

### S2 · Decryption stage ⛔ (needs CIMB password scheme)
- `pikepdf` in-memory decrypt → `BytesIO` → parser. Plaintext never on disk.
- `institution_credential (password_enc, password_scheme[static|derived|per_statement])`.
- Detect encryption, resolve password by scheme, on failure surface "🔒 needs password".
- **Test:** encrypt a fixture PDF locally with a known password → assert decrypt→parse round-trips;
  wrong password raises and is not logged.
- **Blocker:** which scheme CIMB uses (SPEC §8). Build the `static` path now; wire `derived`/
  `per_statement` once Tommy confirms. Verify end-to-end against one *still-locked* CIMB PDF.

### S3 · Validation gate ✅
- Generalize the parser-level reconcile into a pipeline stage: schema check, balance
  continuity (hard-fail cash/CC), near-empty extraction → OCR/manual route, soft portfolio
  lot continuity.
- **Done:** `coffer/ingestion/validate.py` returns a routing decision (`OK` /
  `NEEDS_MANUAL_REVIEW` / `REJECTED`, `alert` only on REJECTED). Tampered cash/CC statements
  rejected + alert; near-empty text → manual review; portfolio lot continuity soft. 16 tests.

---

## Phase B — Data + logic

### S4 · Persistence layer ✅
- Postgres schema + migration for the full SPEC §2 model (all 11 tables:
  `household`, `member`, `account`, `institution_credential`, `statement`, `transaction`,
  `category`, `override`, `learned_rule`, `holding`, `networth_snapshot`). SQLAlchemy 2.0
  ORM (`Numeric`, never `Float`); one Alembic migration, up/down tested; `alembic check`
  confirms no model↔schema drift.
- **Encryption at rest:** `institution_credential` secret is Fernet-encrypted into
  `password_enc` by the persistence mapper (domain holds plaintext, DB holds ciphertext).
- Repository interfaces (Protocols) in `domain/repositories.py`; SQLAlchemy impls in
  `persistence/repositories.py` (dependency points inward — import-linter still KEPT).
- **Done:** repo round-trip test per aggregate + Decimal-exactness + encryption-at-rest +
  snapshot upsert idempotency + migration up/down/up, all against a real Postgres. Full gate
  green (ruff · format · mypy --strict · lint-imports · **92 pytest**). CI gained a Postgres service.
- **Depends on:** S0.

### S5 · Dedup ✅
- Three layers: file hash (reject), content hash (`content_hash_fields()`), txn `dedup_key`
  (skip-and-log per row). Pure repo-driven stage (`coffer/ingestion/dedup.py`) returning a
  `DedupResult`; also dedups within a batch (unique `dedup_key`). `account_id` is an argument
  (resolution is S9). Works for `ParsedStatement` and `ParsedPortfolio`.
- **Done:** exact re-upload rejected; non-byte-identical re-export caught by content hash;
  overlapping-period statements dedup at row level without failing the batch; intra-batch
  identical rows deduped; portfolio path. 12 tests; full gate green (**104 pytest**).
- **Depends on:** S1, S4.

### S6 · Categorization + learned rules ✅
- `coffer/ingestion/categorize.py`: pure `classify` (precedence structural/intra-household →
  learned_rule → regex → uncategorized) + repo-driven `categorize` wrapper; `build_learned_rule`
  (acct-key safe, amount-key needs explicit confirm); `retag` (manual override deactivates the
  learned rule that mis-fired — refinement, not fighting); `seed_categories` (§3.3 + Q4 set).
- **Done:** learned rule by recipient acct auto-classifies; amount-only rule requires
  confirmation; intra-household transfer → seeded transfer category (beats learned rule); retag
  refines rather than duplicating. 23 tests; full gate green (**127 pytest**).
- **Decisions:** regex + structural assignments both stamp `category_source=parser` (kept §2's
  4-value enum; §3.3's regex tier has no distinct source); intra-household acct match is exact
  (mask normalization deferred to S9 seeding). `category_source` stamped; hit_count bump is the
  caller's (S9) job via `matched_rule_id`.
- **Depends on:** S4, S5.

### S7 · Net-worth snapshot recompute ⬜
- Carry-forward month-end grid (SPEC §3.1); event-driven recompute on ingest; handle out-of-order/
  backfill; **serialized per household** (single-writer/lock).
- **Test:** async period ends align to grid; backfilled Feb-after-Mar updates only Feb; two
  concurrent ingests don't corrupt the snapshot.
- **Depends on:** S4.

### S8 · Spend + cash-flow read models ✅
- `coffer/domain/read_models.py` (pure, query-side use-cases — read on-demand, NOT
  materialized/on-ingest, so they live in `domain`, not `ingestion`). `routine_spend_estimate`
  (median-of-monthly-totals + amortized annual on top; per-category median breakdown; anomaly
  flags guarded by ≥3 obs + median floor; cold-start <3 months → estimate `None`) and
  `cash_flow_summary` (monthly income − spend, savings rate with div-by-zero guard, headline
  aggregate over the window). Repo-driven wrappers `compute_routine_spend` / `compute_cash_flow`
  gather household transactions per account (mirrors recompute's load).
- **Done:** median-of-totals ≠ sum-of-category-medians (both correct); annual amortizes; sparse
  category → no div-by-zero + not flagged; <3 months → no estimate; transfers/investment_moves/
  income/uncategorized excluded from spend; attributed by txn date. 15 tests; full gate green
  (**164 pytest**; alembic check no drift — no schema change).
- **Depends on:** S4, S6.

---

## Phase C — Interfaces

### S9 · Ingestion API (FastAPI) ✅
- `coffer/ingestion/pipeline.py` — the `IngestStatement` use-case orchestrates
  Decrypt → Parse → Validate → Dedup → Persist → Recompute (pure + repo-driven, injected
  infra ports; recompute serialized per household). `coffer/api/` is a Humble Object: router
  (`POST /api/statements`), `IngestResponse`, composition-root DI, `PdfPlumberReader` +
  `FilesystemStatementArchive` adapters, parser registry.
- **Done:** outcomes `INGESTED`/`DUPLICATE`/`NEEDS_PASSWORD`/`NEEDS_ACCOUNT`/`NEEDS_REVIEW`/
  `REJECTED`(alert) with per-row new/dup/holdings counts; `closing_balance` populated per
  family; `hit_count` bumped (new `LearnedRuleRepo.bump_hit_count`); encrypted original
  retained (unencrypted → encrypted at rest). 18 tests (unit + `TestClient` + Postgres
  integration + archive security); full gate green (**182 pytest**; alembic no drift). Password
  is a runtime arg (not stored — Tommy's preference). Known limitation: in-process recompute
  lock released before commit (idempotent recompute self-heals; pg advisory lock is the robust
  fix). See PROGRESS for decisions.
- **Depends on:** S2, S3, S4, S5, S7.

### S10 · Telegram bot ✅
- `coffer/ingestion/telegram.py` — the `TelegramIngest` use-case (a Humble Object over
  `IngestStatement.execute` with `uploaded_via=TELEGRAM`): server-side `telegram_user_id`
  allowlist (unknown user → silent ignore), account auto-detect via `detect.py` sniffer →
  resolve to a household account, inline keyboard on ambiguity + callback completion,
  stored-`static`-credential decryption for encrypted statements (never prompt in chat),
  **delete source message after a successful ingest**. `coffer/api/telegram_routes.py` is
  the webhook (secret-token verify via `hmac.compare_digest`, `Update` parsing, dispatch);
  `coffer/api/telegram_adapters.py` has `HttpxTelegramClient` + `InMemoryPendingUploadStore`.
- **Done:** unknown-user silent ignore; detect→single-account auto-ingest+delete;
  ambiguous/undetected→keyboard, callback completes+deletes; encrypted→stored static
  credential (no chat password); 403 on bad secret token; rejected/duplicate keep the
  source. 33 tests (sniffer + use-case + webhook `TestClient` + httpx `MockTransport`
  adapter); full gate green (**215 pytest**; alembic no drift — no schema change). Password
  reconciliation: web = runtime prompt, Telegram = stored `static` credential (unattended).
- Public webhook via tunnel; dashboard/API stays on LAN/VPN (SPEC §5).
- **Depends on:** S9.

### S11 · Dashboard — Ringkasan (§3.1) ✅ (bill-card §3.4 deferred)
- **Backend read API** (framework-agnostic): `coffer/domain/read_models.py` gained
  `compute_ringkasan` (household series from the materialized `networth_snapshot`; **per-member
  series computed on read** via the shared carry-forward engine; delta; Rincian Akun; KPI row
  reusing the S8 read models). Preparatory refactor: pure §3.1 primitives extracted to
  `coffer/domain/networth.py`, `recompute.py` imports + re-exports them (no duplication, S7
  tests unchanged). Route `GET /api/dashboard/ringkasan/{household_id}` (`coffer/api/dashboard*.py`)
  — **money serialized as strings**, never floats.
- **Frontend** (`web/` — React + Vite + TS + Recharts, Vitest): app shell (header, top/bottom
  nav, month chip), Ringkasan view = net-worth hero + tide chart (Gabungan/Per-Anggota toggle) +
  KPI row (deep-links) + Rincian Akun; other tabs stubbed. Frozen design tokens; Bahasa Indonesia;
  `id-ID` formatting at the edge only. New CI `web` job (tsc + vitest + build).
- **Done:** 227 pytest (unit + `TestClient` + Postgres integration) + 21 vitest, full gate green,
  alembic no drift (no schema change).
- **Deferred:** the **§3.4 bill due-date card** — its placement (Ringkasan card vs. 5th tab) is
  Tommy's call and was unconfirmed; a clean insertion point is left in the Ringkasan view.
- **Depends on:** S7, S8; design handoff.

### S12 · Dashboard — Portofolio (§3.2) ✅ (corp-action tags deferred)
- **Backend:** `portfolio_consolidation` read model (`coffer/domain/read_models.py`) merges the
  latest broker holdings by ticker — combined lots, **lots-weighted avg price**, market value,
  unrealized P/L, per-broker breakdown, household totals — and flags **mixed-as-of dates** (SPEC
  §3.2). `GET /api/dashboard/portofolio/{household_id}` (money as strings). Reader generalized:
  `RingkasanReader` → `DashboardReader` (`.ringkasan` + `.portofolio`), DI `get_dashboard_reader`.
- **Frontend:** `web/src/views/Portofolio.tsx` — rose mixed-date caveat banner, two summary cards
  (Nilai Pasar Gabungan + Unrealized P/L with %), holdings table (Emiten / Broker / Lot / Avg-Harga
  / Nilai-P&L) with an expandable per-broker breakdown + Total Rumah Tangga row. Self-fetches via a
  generic `useApi` hook; wired into the shell's Portofolio tab.
- **Done:** 236 pytest (read model + `TestClient` + Postgres integration) + 22 vitest; full gate
  green; alembic no drift (no schema change).
- **Deferred:** **CORP ACTION tags / lot-discontinuity detection** — no storage for it yet
  (`holding` has no corp-action field) and it needs cross-statement comparison; not faked (CLAUDE.md
  "don't invent"). Follow-up: add detection + a `holding.corp_action` note.
- **Depends on:** S4 (holdings), S1 (portfolio parsers).

### S13 · Dashboard — Belanja (§3.3) ✅
- **Backend read:** `build_belanja`/`compute_belanja` (`coffer/domain/read_models.py`) assemble
  the routine estimate (headline base median + amortized annual + per-category medians), a
  `monthly_series` sparkline (added to the S8 `RoutineSpendEstimate`), enriched anomalies, the
  review queue (all uncategorized first, then recent categorized, capped 40) and the category
  list for the picker. `GET /api/dashboard/belanja/{household_id}` (money as strings).
- **Backend write (Tag/Ubah):** `recategorize_transaction` (`coffer/ingestion/recategorize.py`)
  over the S6 pure fns — records an override, stamps the txn `manual`, deactivates a mis-fired
  learned rule, optionally generalizes on `counterparty_acct`. Public `match_learned_rule`
  extracted from S6. Widened Protocols `TransactionRepo.set_category` + `LearnedRuleRepo.set_active`.
  `POST /api/transactions/{id}/category` (404/400/422 mapping; commit-on-success). No recompute.
- **Frontend:** `web/src/views/Belanja.tsx` — routine hero + CSS bar sparkline (rose when a month
  exceeds the estimate) + per-category median bars (cadence-coloured) + anomaly card + review
  queue with source badges and an inline Tag/Ubah editor. First SPA mutation (`postJson`,
  `useBelanja` reload key, retain-prior-data-during-reload). New `lib/spend.ts` + spend CSS.
- **Done:** 262 pytest (read model + write use-case + `TestClient` + Postgres integration) + 31
  vitest; full gate green; alembic no drift (no schema change — all columns pre-existed).
- **Deferred:** amount-only generalization in the review UI (backend supports it); review-queue
  pagination; a machine-readable anomaly reason (UI renders Bahasa from `category_median`).
- **Depends on:** S6, S8.

### S14 · Dashboard — Arus Kas (§3.5) ✅
- **Backend read:** `build_arus_kas`/`compute_arus_kas` (`coffer/domain/read_models.py`) wrap the
  S8 `cash_flow_summary` — the monthly income/spend/cash-flow/savings-rate series + window
  headline — and add the **latest month's** income-by-category (`IncomeSource`) + spend-by-type
  (`SpendTypeTotal`) breakdown lists. `GET /api/dashboard/arus-kas/{household_id}` (money as
  strings; `DashboardReader.arus_kas`). Read-only; no write path.
- **Frontend:** `web/src/views/ArusKas.tsx` — savings-rate + latest-month cash-flow summary cards,
  `CashFlowChart.tsx` (Recharts `ComposedChart`: grouped income/spend bars + dashed savings-rate
  line on a secondary axis), and the two breakdown list cards (Sumber Pendapatan / Belanja per
  Tipe). New pure `lib/cashflow.ts` (+ test). Wired into the `cashflow` tab; the last placeholder
  is gone (all four tabs now live) so `views/Placeholder.tsx` was removed.
- **Done:** 274 pytest (read model + `TestClient` + Postgres integration) + 37 vitest; full gate
  green; alembic no drift (no schema change — read-only over existing tables).
- **Depends on:** S8.

### S15 · Backup + ops ✅
- **Prod static serving** (`coffer/api/static.py` `mount_spa`): the API serves the built
  `web/dist` on one LAN origin — `/assets` via `StaticFiles`, catch-all SPA deep-link fallback,
  `/api` never shadowed. Env-gated on `COFFER_WEB_DIST_DIR` (unset → API-only, unchanged).
  Resolves the standing S11 follow-up.
- **Backup safety core** (`coffer/api/ops.py`, pure + gate-covered): `audit_archive` (encrypted-only
  guard — plaintext/unexpected file aborts the backup, reusing `ingestion.decrypt.is_encrypted`),
  `spot_check_due` (30-day reconciliation cadence), and a `main` CLI the shell calls.
- **`scripts/backup.sh`**: preflight audit → `pg_dump --format=custom | restic backup --stdin`
  (no plaintext dump on disk) → restic backup of the encrypted originals → forget/prune retention
  → spot-check reminder. **`scripts/restore-verify.sh`**: restic check + restore + `pg_restore --list`
  (+ optional scratch-DB restore). **`docs/OPERATIONS.md`**: full runbook (env, systemd, backup/restore,
  spot check, webhook). Reuses the existing TrueNAS SCALE + restic pipeline; never backs up plaintext.
- **Done:** 296 pytest (+22: `test_ops.py`, `test_static.py`) + full gate green; alembic no drift
  (no schema change). **Follow-up:** add `uvicorn` to `pyproject.toml` deps (couldn't lock offline);
  run the scripts against the real restic repo on the box.
- **Depends on:** S4.

---

## Open items blocking specific slices (need Tommy)
- **CIMB password scheme** → unblocks S2 end-to-end (SPEC §8). You unlocked the sample; the password + whether it changes monthly is all that's needed.
- **§3.4 bill-aggregator placement** (card on Ringkasan vs. 5th tab) → S11 shipped without it
  (insertion point left on Ringkasan); confirm placement to add the bill due-date card.
- **Frontend framework** — chosen by best-judgment while Tommy was away: **React + Vite + TS +
  Recharts** (SPEC-recommended). Flag if SvelteKit is preferred (backend API is unaffected).
- **Real samples**: BCA CC, BCA savings, Ajaib, Stockbit → unblock the remaining S1 parsers.
- **CIMB edge cases**: a statement with cash advance / multi-card / multi-page → parser follow-up on S1.
