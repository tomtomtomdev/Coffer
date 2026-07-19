# Coffer — PROGRESS

> Persistent memory across cold sessions. Read this first. Update it last.
> Format: what's done, what's in progress, what's next, and any live decisions/blockers.

_Last updated: 2026-07-19_

## Done (this session) ✅ — S1/S2 reality-check: parsers re-validated on fresh real statements + stale docs corrected
Tommy provided real statements to "unblock the S1 parsers" and the CIMB password. Investigating
first (per CLAUDE.md — surface contradictions before acting) revealed a **doc/reality mismatch**:
S1 is *already complete*. Git history (`973a1f9`…`c63c11a`, all `S1:`) + the PROGRESS tail
("**S1 COMPLETE — all 6 parsers built**", line ~805) + **57 green parser tests** all confirm the
BCA/Ajaib/Stockbit parsers were built long ago against real→anonymized fixtures. Yet PLAN.md and
every recent entry (S9–S16) kept repeating "blocked on samples / provide samples to unblock S1" —
**stale and wrong** (it misled last turn's summary). So the fresh files aren't unblockers; they're
newer months of the same accounts → a genuine **re-validation** pass.

- **Re-validated the existing parsers against fresh REAL statements** (in-memory decrypt/extract via
  a scratchpad script; nothing plaintext written on success; scratchpad cleaned; passwords via env,
  never logged/committed):
  - ✅ `bca_kartu_kredit` — BCA CC (May-26, encrypted w/ static pw): 3p, 37 txns, due-date + Tagihan
    Baru extracted, **reconciled**.
  - ✅ `bca_tahapan` — BCA savings `0160…` (Jun-26): 6p, 61 txns, **reconciled**.
  - ✅ `bca_tapres` — Ajaib RDN `4958…` (Jun-26): 7 txns, **reconciled**.
  - ✅ `bca_tapres` — Stockbit RDN `4996…` (Apr-26): empty month (0 txns), **reconciled** (the
    empty-statement edge from `c63c11a`).
  - ✅ `ajaib_portfolio` — `106FXF` (2026-06-30): 12 holdings + cash, structural gate passed.
  - ⚠️ `stockbit_soa` — **not re-validated**: the path given for "stockbit" (`~/Desktop/spec.md`)
    is an unrelated document (a "Driftline" interview-demo spec), not a Stockbit statement. Need a
    correct fresh Stockbit SOA to re-validate.
- **CIMB scheme confirmed (Tommy): `static`, does not rotate.** → **S2 marked ✅** in PLAN
  (static path done, scheme resolved, end-to-end decrypt+parse re-proven this session via the BCA CC
  PDF which is also static). Operational remainder: seed the CIMB `institution_credential` row on the
  box (password entered at runtime, **never committed**). Web ingest already prompts at runtime.
- **Backup direction changed (Tommy): no TrueNAS/restic-on-NAS for now → explore cloud backup.**
  Delivered as **`docs/OPERATIONS.md` §3a "Cloud backup target"**: the S15 scripts are already
  backend-agnostic (restic `backup|forget|check|restore`), so cloud is a **config change, not code** —
  and restic's **client-side encryption** means the provider only holds ciphertext (satisfies the
  encrypted-only invariant; residency moot). Documented three concrete backends — **Backblaze B2
  (recommended)**, Cloudflare R2 (zero-egress), rclone→Google Drive/Dropbox/OneDrive — with exact env
  config + a 3-2-1 / protect-the-restic-password resilience note. (I asked which backend; Tommy was
  away, so best-judgment = document all three and leave the pick to him — no account setup forced.)
- **Docs corrected (the actual deliverable):** PLAN.md S1 `🚧`→`✅` (all 6 parsers, accurate status +
  fresh-validation note), S2 `⛔`→`✅` (scheme resolved), and the "Open items" section rewritten
  (CIMB scheme / §3.4 placement / framework / S1 samples all marked RESOLVED; only a correct Stockbit
  sample + the operational/cloud-backup items remain).
- **No code changed** in this entry (parsers already green) → gate unaffected: 57 parser tests green;
  full suite/ruff/mypy/lint-imports/alembic untouched. Committed to `main` (docs only), not pushed.
- **Next:** (1) get a correct fresh **Stockbit** statement to re-validate `stockbit_soa` (the only
  parser not re-checked this round); (2) **cloud backup** — Tommy picks a backend (B2 recommended) +
  creates the bucket/keys, then `restic init`; runbook is written (`OPERATIONS.md` §3a), scripts need
  no change; (3) optionally seed the CIMB `institution_credential` (needs the box + Fernet key —
  password entered at runtime, never committed). Could also commit the fresh months as **regression
  fixtures** (anonymized) if wanted.

## Done (this session) ✅ — S14 follow-up: savings-rate per-point `%` labels (Arus Kas)
Plan is complete (S0–S16); with no todo slice left and no new samples/password/infra input
available, this session closed the one **design-completion** follow-up that needs no external
input and touches no financial-correctness path — the frozen design (MEASUREMENTS §Cash Flow,
line 87) shows a `%` label above each savings-rate dot, which the S14 chart was missing.

- **Pure helper — `web/src/lib/cashflow.ts` `savingsPointLabel(savings)`**: a fraction → integer
  `%` via the id-ID `fmtPct` (e.g. `0.4285714 → "43%"`); **`null` at a line gap** (a zero-income
  month, where the savings line already breaks) so no stray label is drawn on the break. Kept in
  `lib/` (tested, Bahasa/`Intl` at the edge) like `spendTypeLabel`, not inline in the component.
- **Chart wiring — `web/src/components/CashFlowChart.tsx`**: a `<LabelList content={SavingsRateLabel}>`
  child on the savings `<Line>`. `SavingsRateLabel` renders a `<text>` at the dot's `x` / `y − 9`,
  `textAnchor=middle`, ink (`#1c1d26`), **10.5px / weight 600**, IBM Plex Mono (matching the charts'
  other numeric labels) — exactly the MEASUREMENTS spec. Coerces Recharts' `string | number` `x`/`y`
  and returns `null` for a null/gap point (double-guarded via the pure helper). The 1.25× headroom in
  `savingsAxisMax` leaves room above the top dot for its label. **Presentation only** — no backend,
  no schema, no axis-scale change (the design's fixed 0–80% axis is a separate, deliberately-unchanged
  decision; the axis stays data-driven-with-headroom as shipped in S14).
- **Tests (+2 ts):** `cashflow.test.ts` `savingsPointLabel` (integer-percent format + null-at-gap).
  Red-first confirmed (`savingsPointLabel is not a function`) → green. The chart label itself isn't
  asserted in vitest (Recharts renders 0-dim in jsdom — same as the tide/cashflow charts already);
  correctness rests on the unit-tested pure helper + tsc + build.
- **Web gate green:** tsc --noEmit · **43 vitest** (+2) · vite build (bundle unchanged — no new dep;
  the ~163 kB Recharts gzip is pre-existing). **No Python touched** → ruff/mypy/lint-imports/309
  pytest unaffected; alembic unchanged (no schema change).
- **Decision — best-judgment pick while Tommy was away.** The direction question (code follow-ups /
  unblock parsers / deployment / start v2) went unanswered; chose the lowest-risk, fully-verifiable,
  design-mandated item and deliberately avoided anything needing a UX decision (review-queue
  pagination, amount-only generalization UI), real samples (S1 parsers), the CIMB password (S2 /
  `derived`/`per_statement` decrypt), or a schema add (corp-action detection).
- **Committed to `main`** (`S14 follow-up: …`), not pushed.
- **Next (unchanged — all needs Tommy):** seed the CIMB `institution_credential` (password +
  whether it rotates); set the real Telegram `setWebhook` (secret token) behind the tunnel; run
  `backup.sh` + `restore-verify.sh` once against the real restic/TrueNAS repo; provide anonymized
  samples to unblock the remaining S1 parsers (BCA CC / savings / Ajaib / Stockbit). Other code-only
  follow-ups still open (no input needed): review-queue pagination, amount-only generalization UI,
  machine-readable Bahasa anomaly reason, masked-account auto-disambiguation. v2 backlog (SPEC §6):
  LLM categorizer, budgets/goals, notifications, multi-currency, portfolio corp-action tags.

## Done (prev session) ✅ — S16 Bill due-date card (§3.4) — the deferred aggregator, now built
Resolved the long-deferred §3.4 "no home" feature end-to-end. Placement was locked 2026-07-18
(**Tagihan Jatuh Tempo card on Ringkasan, below the hero / above the KPI row**); this session built
the full vertical slice so the data the CC parsers already extract (due date + minimum) now flows
all the way to the card.

- **Domain — `Statement.due_date` / `.minimum_payment`** (both nullable). §2's model stored only
  `closing_balance`; §3.4 needs the bill's Tgl. Jatuh Tempo + Pembayaran Minimum. Added to the entity
  + `StatementRow` + both statement mappers + **new Alembic migration `79a1b0e9dc7c`** (chained off
  S7's `741f49a1c0c3`; autogenerated → two nullable columns; down→up reversible; full-chain-from-zero
  `alembic check` → **no drift**).
- **Read model — `bill_due_dates` / `compute_tagihan`** (`domain/read_models.py`), pure + repo-driven
  like the other dashboards. Each **liability-bucket (credit-card)** account's **latest statement
  carrying a `due_date`** → a `BillDue` (holder, due date, signed **`days_remaining`** vs. an injected
  `today`, minimum payment, full balance = the statement's `closing_balance`). Sorted ascending by days
  remaining (soonest first). A non-CC account, or a CC with no due-dated statement, contributes nothing
  — never a bill card without a real due date. `today` is injected so the countdown stays pure/
  deterministic (the api edge passes `date.today()`).
- **Pipeline — populate at persist.** New `pipeline._bill_summary(parsed)` threads `due_date` +
  `minimum_payment` from the `ParsedStatement` into the persisted `Statement` (portfolio/savings → None).
  No recompute change — bill fields don't touch net worth.
- **Read endpoint** — `GET /api/dashboard/tagihan/{household_id}` (`dashboard_routes.py` +
  `TagihanResponse`/`BillDueSchema` in `dashboard_schemas.py` + `DashboardReader.tagihan(household_id,
  today=date.today())`). Money as strings (the invariant), `due_date` ISO, `days_remaining` int, a null
  minimum stays null. No DI change (the reader already carries accounts/members/statements repos).
- **Frontend — `web/src/components/Tagihan.tsx`** (self-fetching via a new `useTagihan`): renders at the
  locked anchor in `views/Ringkasan.tsx` (below `<HeroCard>`, above `<KpiRow>`). Rows show card name +
  holder + due date, full balance, a toned **days label** (red < 3 days / amber < 7 / muted — SPEC §3.4
  "red flag under 3 days") and the minimum. Renders **nothing** while loading / on error / when there
  are no bills, so a quiet month never disturbs the overview. New pure `lib/bill.ts`
  (label/countdown/tone) + `bill.test.ts`; new `.tagihan`/`.billrow` CSS on the frozen tokens.
- **Tests (+13 py, +4 ts):** `test_tagihan.py` (9 — all-fields / latest-billed-wins / sort /
  non-CC-excluded / no-due-date-excluded / overdue-negative / null-min+missing-closing / empty / repo
  wrapper), `test_api_tagihan.py` (2 — string-money shape + empty), `test_tagihan_integration.py` (1 —
  read path over Postgres), a persistence round-trip (`test_persistence_repos.py`), + 2 asserts on the
  CIMB pipeline-integration ingest (due 2026-04-06, min 50000.00 persisted). Web: `bill.test.ts` (3) +
  1 App test (card renders below the hero). **Live-smoked** the real uvicorn + Postgres endpoint →
  `200` with `days_remaining=3` + exact string money, then restored the clean schema.
- **Full gate green:** ruff · ruff-format · mypy --strict (51 files) · lint-imports KEPT · **309 pytest**
  · alembic no-drift (full chain rebuilt from zero) ‖ **web:** tsc · **41 vitest** · vite build.
- **⚠ Follow-ups:** (a) card-name copy lives in the web (`bill.ts` `CARD_LABELS`) — extend if BCA/CIMB
  want finer names. (b) `derived`/`per_statement` CC statements still need their Telegram password path
  to ingest (unchanged). (c) overdue bills render with the red flag but there's no separate escalation.
- **Committed to `main`** (`S16: …`), not pushed.
- **Next:** every plan slice (S0–S15) **and** the §3.4 bill card are now done. What remains is
  operational + needs Tommy: seed the CIMB `institution_credential` (password), set the real Telegram
  `setWebhook` (secret token) behind the tunnel, run backup + restore-verify on the TrueNAS box.

## Done (prev session) ✅ — post-plan cleanup: pin `uvicorn` runtime dep
Plan is complete (S0–S15). This session closed the one remaining Tommy-independent code
follow-up from S15: **`uvicorn` is now a pinned runtime dependency** (`uv add uvicorn` →
`uvicorn==0.51.0` in `pyproject.toml` + `uv.lock`). Verified the ASGI app loads under the
pinned server (`uvicorn.importer` resolves `coffer.api.app:app` → FastAPI). Cleared the now-stale
interim workarounds: `docs/OPERATIONS.md` ("not yet pinned / `uv pip install uvicorn`" note →
"pinned; `uv sync` installs it") and `scripts/dev.sh` (`uv run --with uvicorn …` → plain
`uv run uvicorn …`; `bash -n` clean). Dependency-only change (zero Python source touched), so
the 296-test suite is unaffected. Static gate re-run green: ruff · ruff-format · lint-imports
KEPT · mypy --strict (91 files). **Remaining follow-ups all need Tommy / his box** (below).

## Done (prev session) ✅ — S15 Backup + ops (§7) — **PLAN COMPLETE (S0–S15)**
The final slice: make the deployment real. Three deliverables — prod static serving of the
built SPA, the backup/restore pipeline, and the monthly reconciliation spot-check reminder —
with the security-relevant logic in gate-covered Python and the infra glue in thin shell.

- **Prod static serving — `coffer/api/static.py` (`mount_spa`).** In dev the SPA runs under
  Vite; in prod there's no Vite, so the API process serves the built `web/dist` on one LAN
  origin. Mounts `/assets` (Vite's content-hashed bundles) via `StaticFiles`, then a catch-all
  that returns a real file when one exists else `index.html` (SPA deep-link fallback). The
  `/api` and `/assets` namespaces are **never shadowed** — matched by the routers/mount
  registered first, and the catch-all explicitly declines them so an unknown API path 404s
  (never the SPA shell). Wired into `create_app()` behind an **optional** `COFFER_WEB_DIST_DIR`
  (guarded on `index.html` existing): unset (dev + every other test) → API-only, unchanged;
  importing the app still requires no env. **Resolves the standing S11/S15 "serve web/dist" follow-up.**
- **Backup safety core — `coffer/api/ops.py` (pure, testable).**
  - **`audit_archive(dir)` — the encrypted-only guard.** Classifies every archive entry:
    password-protected `.pdf` (reuses `ingestion.decrypt.is_encrypted`; api→ingestion is inward)
    and Fernet `.pdf.enc` are safe; a **plaintext `.pdf` or any unexpected file** ⇒ `ok=False`.
    The backup runs this as a preflight and **aborts** before restic sees a byte — the "backup
    never contains a plaintext PDF" invariant (SPEC §4/§7, CLAUDE.md) enforced in Python, not shell.
  - **`spot_check_due(last, now, interval=30d)`** — pure predicate for the monthly manual
    bank-reconciliation reminder (SPEC §7: prompt a spot check rather than present stale numbers).
  - **`main` CLI** (`python -m coffer.api.ops {audit DIR | spot-check-due MARKER}`) — the thin
    seam `scripts/backup.sh` calls; exit 0/1 drives the shell. Verified live end-to-end.
- **`scripts/backup.sh`** — preflight audit → **`pg_dump --format=custom | restic backup --stdin`**
  (streamed, so **no plaintext dump ever touches local disk**; `password_enc` is already Fernet
  ciphertext in the DB) → `restic backup "$ARCHIVE_DIR"` (encrypted originals) → `restic forget`
  retention (7 daily/5 weekly/12 monthly + prune) → spot-check reminder (optional Telegram ping,
  else logged). All config from env (strips `+psycopg` → libpq URL); refuses to run on a failed audit.
- **`scripts/restore-verify.sh`** — the DR drill: `restic check` → restore latest DB-dump →
  `pg_restore --list` (valid custom-format archive) → optional restore into a scratch DB
  (`COFFER_RESTORE_TEST_DB_URL`) + row count. Never touches the live DB.
- **`docs/OPERATIONS.md`** — full runbook: env-var reference, systemd service/timer + cron,
  the build+serve prod flow, backup/restore, the spot check, and the webhook recap. README
  Deployment section rewritten to point at it; the old "ops follow-up" line for static serving is gone.
- **Decisions:** (a) security-relevant logic (encrypted-only guard, reminder cadence) lives in
  gate-covered Python; shell is glue. (b) DB streamed to restic via `--stdin` — consistent with
  §4 "plaintext never on disk". (c) static mount is env-gated + `index.html`-guarded so tests/dev
  and app import are unchanged. (d) spot-check state is an ISO-date marker file the operator
  `date`-stamps after reconciling.
- **Tests (+22 py):** `test_ops.py` (14 — audit missing/empty/encrypted+at-rest/plaintext-flag/
  unexpected-file/subdir; spot_check none/within/past/boundary; CLI audit 0-vs-1, spot-check
  0-vs-1, unknown→2), `test_static.py` (8 — index at `/`, hashed-asset JS mime, root-level file,
  deep-link→index fallback, `/api` not shadowed→404, no-env→API-only, env-set→mounts, missing-build→no-crash).
- **Full gate green:** ruff · ruff-format · mypy --strict (91 files) · lint-imports KEPT ·
  **296 pytest** · alembic no drift (verified on a clean schema — **no schema change**; ops/read-only)
  ‖ **web** (unchanged this slice): tsc · 37 vitest · vite build. Static behavior verified through
  the real Starlette ASGI stack via `TestClient`.
- **⚠ Follow-ups:** (a) ~~`uvicorn` not a pinned dep~~ **DONE (2026-07-17):** pinned as
  `uvicorn>=0.51.0`; docs/dev.sh workarounds removed. (b) restic/TrueNAS is Tommy's
  infra — the scripts are `bash -n`-clean and their Python core is verified, but they're **unexercised
  against the real restic repo** here; run `scripts/restore-verify.sh` once on the box. (c) §3.4
  bill-due-date card still deferred (placement is Tommy's call). (d) CIMB password still needed to
  seed its `institution_credential` for encrypted Telegram ingest.
- **Committed to `main`** (`S15: …`), not pushed.
- **Next:** **All plan slices S0–S15 are done.** What remains is operational + needs Tommy, not code:
  seed the CIMB `institution_credential` (password), decide §3.4 bill-card placement, set the real
  Telegram `setWebhook` (secret token) behind the tunnel, and run the backup + restore-verify on
  the TrueNAS box. (`uvicorn` dependency — DONE 2026-07-17.) v2 backlog (SPEC §6): LLM-assisted
  categorizer, budgets/goals, notifications, multi-currency, portfolio corp-action tags.

## Done (prev session) ✅ — S14 Arus Kas dashboard (§3.5)
The cash-flow screen — the **fourth and final frozen tab**, and the last of Phase C's dashboards.
Read-only, same read-half pattern as S11/S12 (DashboardReader method + endpoint + self-fetching
view). The S8 `cash_flow_summary` already did the monthly income−spend + savings-rate math; S14
wraps it into an assembled view, adds the two latest-month breakdown lists, and draws the chart.

- **Read model — `build_arus_kas` / `compute_arus_kas`** (`coffer/domain/read_models.py`), pure +
  repo-driven like S8/S13. Wraps `cash_flow_summary` (the full monthly `MonthlyCashFlow` series +
  the window `headline_savings_rate`) and adds, for the **latest month** in the series:
  - **`income_sources: list[IncomeSource]`** — income totals by **category** (label + amount),
    sorted by amount desc. Matches the design's "Sumber Pendapatan · <bulan>".
  - **`spend_by_type: list[SpendTypeTotal]`** — spend totals by **CategoryType** in a fixed
    `routine → discretionary → one_off` order; the UI maps the type to its Bahasa label.
  - **`latest_month` / `latest_cash_flow`** — drives the "Arus Kas · <bulan>" summary card.
  - **Decision — breakdowns are scoped to the latest month** (not the window), matching the frozen
    design's "· <bulan>" labels and the latest-month cash-flow card. A zero-amount category/type is
    **dropped**, not shown as a `Rp 0` row (no fabricated rows — the read-model house style).
    Transfers / investment_moves / uncategorized are excluded from flow (via `cash_flow_summary`).
- **Read endpoint** — `GET /api/dashboard/arus-kas/{household_id}` (`dashboard_routes.py` +
  `ArusKasResponse`/nested `MonthlyCashFlowSchema`/`IncomeSourceSchema`/`SpendTypeSchema` in
  `dashboard_schemas.py` + `DashboardReader.arus_kas`). Money + savings-rate as strings (the
  invariant), `spend_by_type.type` as the enum `.value`; `savings_rate`/`headline_savings_rate`/
  `latest_*` null-safe. No DI change — the existing `get_dashboard_reader` already carries the repos.
- **Frontend — `web/src/views/ArusKas.tsx`** (self-fetching via a new `useArusKas`): two summary
  cards (Tingkat Menabung = window-avg savings rate; Arus Kas · <bulan> = latest cash flow, both
  sign-coloured green/rose), the **`CashFlowChart`** (Recharts `ComposedChart`: grouped income
  (green) / spend (rose) bars + a **dashed savings-rate line on a secondary right axis**,
  `connectNulls={false}` so a zero-income month breaks the line), and the two breakdown list cards.
  - New pure **`lib/cashflow.ts`** (`cashFlowChartData` windows to the last `window_months` +
    maps a null savings rate to a line gap; `incomeAxisMax` = 1.22× the largest bar; `savingsAxisMax`
    capped at 100%; `spendTypeLabel` = frozen "Rutin/Discretionary/One-off" copy) + `cashflow.test.ts`.
    New `monthName` in `lib/format.ts` (long month, no year) for the "· Juni" labels. New CSS for
    the summary figure size + list cards per MEASUREMENTS §Cash Flow.
  - **All four tabs are now live** → the `cashflow` placeholder is gone and `views/Placeholder.tsx`
    was deleted (`.placeholder` CSS stays — `Status.tsx`'s loading/error cards reuse it).
- **Tests (+12 py, +6 ts):** `test_arus_kas.py` (8 — series+headline / latest-month income sources
  sorted / spend-by-type fixed-order+zero-drop+transfer-excluded / savings-rate div0 guard /
  transfers+investment excluded / uncategorized excluded / empty / repo wrapper across accounts),
  `test_api_arus_kas.py` (3 — string-money shape + empty + savings-rate null), `test_arus_kas_integration.py`
  (1 — full read path over Postgres via `DashboardReader.arus_kas`). Web: `cashflow.test.ts` (5) +
  1 new `App.test.tsx` (Arus Kas render: savings rate + cash flow + breakdown lists); the old
  "placeholder tab" test became "switches to the Arus Kas tab and back".
- **Full gate green:** ruff · ruff-format · mypy --strict (87 files) · lint-imports KEPT ·
  **274 pytest** · alembic no-drift (verified on a fresh DB — **no schema change**; read-only over
  existing tables) ‖ **web:** tsc · **37 vitest** · vite build.
- **⚠ Follow-ups:** (a) §3.4 bill due-date card still deferred (S11 — placement is Tommy's call).
  (b) The savings-rate line has no per-point `%` text label (design shows one above each dot); the
  rate is pinned in the summary card + shown on hover — add a Recharts `LabelList` if wanted.
  (c) Prod static serving still unwired (S11/S15 ops). (d) Recharts bundle ~163 kB gzip (the chart
  is genuine Recharts, unlike S13's CSS sparkline).
- **Committed to `main`** (`S14: …`), not pushed.
- **Next:** **Phase C dashboards complete (S11–S14, all four frozen tabs live).** Remaining plan
  items: **S15 backup + ops** (DB + encrypted originals into the TrueNAS/restic pipeline; wire prod
  static serving of `web/dist` — the standing S11 follow-up; monthly spot-check reminder). Product
  open items still needing Tommy: §3.4 bill-card placement, the CIMB password (to seed its
  `institution_credential` for encrypted Telegram ingest), and the remaining S1 parser samples.

## Done (prev session) ✅ — S13 Belanja dashboard (§3.3)
The spend screen — the first slice with a **write path** (Tag/Ubah). Same read pattern as
S11/S12 (DashboardReader method + endpoint + view), plus a repo-driven re-tag use-case and
the SPA's first mutation. All spend math stays in Python; the web is presentation only.

- **Read model — `build_belanja` / `compute_belanja`** (`coffer/domain/read_models.py`), pure +
  repo-driven like S8/S11. Assembles the whole screen: the S8 `routine_spend_estimate`
  (headline base median + amortized annual + per-category `CategoryMedian` breakdown), a
  **`monthly_series`** sparkline, **enriched anomalies** (`SpendAnomaly` = `AnomalyFlag` + txn
  description + category label), the **review queue** (`ReviewItem`), and the **full category
  list** (`CategoryOption`) for the picker.
  - **Preparatory add to the S8 estimate:** `RoutineSpendEstimate.monthly_series:
    list[MonthlyRoutinePoint]` — the window months' non-annual routine totals, i.e. the exact
    bars the headline median is taken over. S8's 14 tests unaffected (they assert fields;
    cold-start returns `[]`).
  - **Review queue composition (decision):** **all** uncategorized rows float to the top (they
    need a tag), then the most-recent categorized rows fill up to `review_limit` (40) — so a
    wrong auto-assignment stays visible/correctable per §3.3 ("always visible"). Shows *all*
    sources (Parser / Auto·pelajaran / Manual / Perlu-tag badges), matching the frozen design,
    not just uncategorized. Pagination is a follow-up if it grows.
- **Read endpoint** — `GET /api/dashboard/belanja/{household_id}` (`dashboard_routes.py` +
  `BelanjaResponse`/nested schemas in `dashboard_schemas.py` + `DashboardReader.belanja`).
  Money as strings (the invariant), enums as `.value`.
- **Write path — the Tag/Ubah action.** `recategorize_transaction` use-case
  (`coffer/ingestion/recategorize.py`), a repo-driven orchestration over the **S6 pure
  functions** — mirrors `pipeline`/`telegram`. Records an `Override`, stamps the txn `manual`
  with the edit audit (`set_category`), **deactivates a mis-fired learned rule** ("refinement
  over fighting"), and optionally **generalizes** into a new rule. Resolves household via
  account→member; validates the category belongs to it.
  - **Refactor:** extracted a public **`match_learned_rule(*, counterparty_acct, amount,
    active_rules)`** from S6's private `_match_learned_rule` (behavior identical — S6's 23
    tests green) so the re-tag path can reconstruct which rule assigned a txn's current
    category and deactivate it.
  - **Widened domain repo Protocols** (like S9's `bump_hit_count`): `TransactionRepo.set_category`
    + `LearnedRuleRepo.set_active`, both concrete via `UPDATE …` in `SqlTransactionRepo`/
    `SqlLearnedRuleRepo`. Updated the 6 in-memory fakes typed to those Protocols
    (test_dedup/pipeline/categorize/ringkasan/read_models).
  - **No recompute:** a category change moves read-on-demand spend/flow figures (§3.3/§3.5),
    never balance-based net worth (§3.1) — so no snapshot rebuild is triggered.
  - **Endpoint** — `POST /api/transactions/{transaction_id}/category` (`transactions_routes.py`
    + `transactions.py` `TransactionCategorizer` adapter + `transactions_schemas.py` +
    `get_transaction_categorizer` DI, **commit-on-success** unit-of-work). Error mapping:
    not-found → 404, amount-only-without-confirm → 400, bad `amount_tolerance` → 422. B008
    per-file-ignored (FastAPI DI idiom).
- **Frontend — `web/src/views/Belanja.tsx`** (self-fetching like Portofolio): routine hero
  (base median as the big figure, `+ amortisasi = total/bln` explainer) + **bar sparkline**
  (rose when a month exceeds the headline estimate — the design's fixed 26 jt threshold made
  **data-driven**), per-category median rows (cadence tag + green/orange progress by cadence),
  anomaly card, and the **review queue** with source badges + inline **Tag/Ubah editor**
  (category `<select>` + a "terapkan ke akun ini" generalize checkbox shown only when a
  `counterparty_acct` is present → the safe key).
  - **First SPA mutation:** `postJson` + `recategorizeTransaction` in `api/client.ts`;
    `useBelanja(householdId, reloadKey)` re-fetches after a save; the view **retains prior data
    during reload** (no full-screen flash). New pure `lib/spend.ts` (sparkline shaping + badge/
    cadence label maps) + `spend.test.ts`. New CSS for sparkline/cadence-tags/source-badges/
    review rows/re-tag editor per MEASUREMENTS §Spend. Wired into the `spend` tab (`App.tsx`).
  - **Decision — amount-only generalization is backend-supported but not offered in the review
    UI** (it needs the guarded confirmation); the UI only offers the safe `counterparty_acct`
    rule. Follow-up if wanted.
- **Tests (+27 py, +9 ts):** `test_belanja.py` (10 — monthly series/assembly/queue ordering+limit/
  enriched anomalies/cold-start/empty/repo wrapper), `test_recategorize.py` (7 — override+manual/
  learned-rule deactivation/counterparty+amount generalize/confirm guard/not-found/foreign-cat),
  `test_api_belanja.py` (8 — read string-money shape + cold-start + write forward/404/404/400/422),
  `test_belanja_integration.py` (2 — read path + full re-tag persistence over Postgres). Web:
  `spend.test.ts` (7) + 2 new `App.test.tsx` (Belanja render + Tag→categorize endpoint).
- **Full gate green:** ruff · ruff-format · mypy --strict (84 files) · lint-imports KEPT ·
  **262 pytest** · alembic no-drift (verified on a fresh DB — **no schema change**, all columns
  pre-existed: txn `category_id`/`category_source`/`edited_by`/`edited_at`, `learned_rule.active`,
  `override` table) ‖ **web:** tsc · **31 vitest** · vite build.
- **⚠ Follow-ups:** (a) §3.4 bill due-date card still deferred (S11 note — placement is Tommy's
  call). (b) Anomaly `reason` on the wire is the S6 English placeholder ("possibly non-routine");
  the UI renders a Bahasa reason from `category_median` instead — fold a Bahasa reason into the
  read model if a machine-readable code is wanted. (c) Review-queue pagination + amount-only
  generalization UI. (d) Prod static serving still unwired (S11/S15 ops). (e) Recharts bundle
  unchanged (the sparkline is plain CSS, not Recharts).
- **Committed to `main`** (`S13: …`), not pushed.
- **Next:** **S14 Arus Kas (§3.5)** — income-vs-spend grouped bars + savings-rate line (SVG per
  MEASUREMENTS §Cash Flow) + source/type breakdown lists. Backend read model already exists
  (`cash_flow_summary` / `compute_cash_flow`, S8) — S14 needs a `DashboardReader.arus_kas` method
  + endpoint + `ArusKas.tsx` view, mirroring this slice's read half (no write path).

## Done (prev session) ✅ — S12 Portofolio dashboard (§3.2)
Same read-model + endpoint + view pattern as S11; second dashboard tab now live.
- **Reader generalized** — `RingkasanReader` → **`DashboardReader`** (`coffer/api/dashboard.py`)
  with `.ringkasan` + `.portofolio`; DI renamed `get_ringkasan_reader` → **`get_dashboard_reader`**
  (S11 route/tests updated). One reader per session, N view methods — the pattern S13/S14 extend.
- **`portfolio_consolidation` read model** (`coffer/domain/read_models.py`) — pure, repo-driven.
  Each broker account contributes its **latest** statement's holdings (carry-forward); merged by
  ticker into combined lots, **lots-weighted avg cost** (`Σ(avg·lots)/Σlots`), market value,
  unrealized P/L, cost basis (`mv − pl`), and a per-broker breakdown. **Mixed-as-of guard** (SPEC
  §3.2): distinct broker as-of dates → `mixed_as_of=True` so the UI shows the caveat + per-broker
  figures instead of a false single P/L. Broker cash is not a holding → never appears here (it's
  §3.1's concern, counted once bank-side). Sorted by market value desc.
- **Endpoint** — `GET /api/dashboard/portofolio/{household_id}` (`dashboard_routes.py` +
  `PortofolioResponse` in `dashboard_schemas.py`); money as strings, per-broker `brokers[]` nested.
- **Frontend** — `web/src/views/Portofolio.tsx`: rose mixed-date caveat banner, two summary cards
  (market value + P/L%, colored by sign), holdings table (Emiten/Broker/Lot/Avg-Harga/Nilai-P&L)
  with a click-to-expand per-broker breakdown and a Total Rumah Tangga row. Self-fetching via a new
  generic **`useApi<T>`** hook (`useRingkasan`/`usePortofolio` are thin wrappers); shared
  `Status.tsx` loading/error cards; wired into the Portofolio tab. `shares = lots × 100` and the
  blended current price (`mv/shares`) are UI-side derivations.
- **Tests (+9 py, +1 ts):** `test_portofolio.py` (6 — merge/weighted-avg/totals+ordering/
  same-as-of/mixed-as-of/latest-only/empty), `test_api_portofolio.py` (2 — string-money shape +
  empty), `test_portofolio_integration.py` (1 — full read path over Postgres via `DashboardReader`);
  vitest App test now also drives the Portofolio tab.
- **Full gate green:** ruff · ruff-format · mypy --strict (76 files) · lint-imports KEPT ·
  **236 pytest** · alembic no-drift (no schema change) ‖ **web:** tsc · **22 vitest** · vite build.
- **⚠ Follow-ups:** (a) **CORP ACTION tags deferred** — the frozen design shows them but there's no
  storage (`holding` has no corp-action field) and detection needs cross-statement lot-discontinuity
  comparison; not faked (CLAUDE.md "don't invent"). Add a `holding.corp_action` note + detection
  later. (b) Prod static serving still unwired (S11 note; S15 ops). (c) Recharts bundle unchanged.
- **Committed to `main`** (`S12: …`), not pushed.
- **Next:** S13 Belanja (§3.3 — routine hero + sparkline + per-category medians + review queue wired
  to S6 categorization) and S14 Arus Kas (§3.5 — income-vs-spend bars + savings-rate line). Both add
  a `DashboardReader` method + endpoint + view; S13 also needs a review-queue read (uncategorized +
  learned/regex-tagged rows) and Tag/Ubah actions (write path → S6 `retag`/`build_learned_rule`).

## Done (prev session) ✅ — S11 Ringkasan dashboard (§3.1)
First frontend slice + its read API. Split cleanly so the backend is framework-agnostic:
**all dashboard math stays in Python; the frontend is pure presentation** (id-ID formatting +
charts only), honoring CLAUDE.md ("business logic never in UI", "id-ID formatting only at the edge").

- **Preparatory refactor — `coffer/domain/networth.py`.** The pure §3.1 primitives (month-end
  grid, per-account carry-forward, `account_type`→bucket classification, `compute_snapshot`) were
  extracted from `ingestion/recompute.py` into the domain, since the dashboard's **per-member**
  series needs the same carry-forward and it's domain logic (like the S8 read models).
  `recompute.py` now imports + **re-exports** them (`__all__`), so S7's tests and call-sites are
  untouched — no duplication, one carry-forward implementation. Behavior-preserving (S7's 28 tests
  green through it).
- **`compute_ringkasan` read model** (`coffer/domain/read_models.py`) — repo-driven, pure,
  in-memory-fake-tested like S8. Assembles: **household series** straight from the materialized
  `networth_snapshot` (S7 — fast); **per-member series computed on read** (not materialized —
  `compute_snapshot` over each member's accounts, cheap for 2 people); **delta** vs. prior month
  (pct `None` when prior net worth is 0 — div-by-zero guard); **Rincian Akun** (each account's own
  latest non-null `closing_balance` + as-of + bucket — per-account as-of keeps the mixed-date
  reality honest); **KPI row** reusing S8 (`routine_spend_estimate` + `cash_flow_summary`), each
  `None` on cold start rather than a fake zero.
- **Read endpoint** — `GET /api/dashboard/ringkasan/{household_id}` (`coffer/api/dashboard_routes.py`
  + `dashboard_schemas.py` + `dashboard.py` reader adapter + `get_ringkasan_reader` DI, read-only
  session, no commit). **Decision — money is serialized as strings, never floats** (Pydantic/FastAPI
  jsonable_encoder would coerce Decimal→float; the "never float" invariant must survive the wire).
  The web edge parses + formats id-ID. B008 per-file-ignored (FastAPI DI idiom).
- **Frontend — `web/` (top-level, NOT `coffer/web/`).** Decision: a JS SPA isn't a Python import
  layer; placing it at repo top-level with `node_modules`/`dist` gitignored needs **zero** changes
  to the Python gate (ruff respects gitignore; mypy/import-linter/pytest are scoped to `coffer`/
  `tests`). The empty `coffer/web/__init__.py` stays as the import-linter layer placeholder. Stack:
  **React 18 + Vite 5 + TypeScript (strict) + Recharts + Vitest** (chosen by best-judgment while
  Tommy was away — SPEC-recommended; flag if SvelteKit preferred, backend unaffected).
  - App shell (sticky header w/ avatar stack + centered top-nav + month chip; fixed bottom-nav
    ≤860px; view switching + scroll-to-top), Ringkasan view = HeroCard (figure + delta pill +
    Gabungan/Per-Anggota toggle + tide chart + carry-forward footnote) + KpiRow (3 deep-link cards)
    + RincianAkun; Portofolio/Belanja/Arus Kas stubbed as placeholders.
  - **Tide chart** = Recharts `ComposedChart`: household = stacked portfolio+cash areas (violet/green
    gradients) + near-black net line; member = one line per member. Frozen design tokens in
    `src/index.css` (from `MEASUREMENTS.md`).
  - Pure, tested logic split out: `lib/format.ts` (id-ID `Intl` — `fmtIDR`/`fmtShort`/`fmtJuta`/
    `fmtPct` + month names; **NBSP normalized to plain space**) and `lib/chart.ts` (payload→Recharts
    rows). `api/{types,client}.ts` mirror the wire schema (money as strings). New CI `web` job.
- **Tests (+12 py, +21 ts):** `test_ringkasan.py` (9 — household series/delta/zero-prior guard/
  member carry-forward/Rincian latest-non-null+bucket/KPIs/cold-start/empty), `test_api_ringkasan.py`
  (2 — string-money shape + empty), `test_ringkasan_integration.py` (1 — full read path over real
  Postgres via `RingkasanReader`); vitest `format.test.ts` (12) + `chart.test.ts` (6) + `App.test.tsx`
  (3 — renders headline/KPIs/accounts, tab switch, toggle; API mocked).
- **Full gate green:** ruff · ruff-format · mypy --strict (73 files) · lint-imports KEPT ·
  **227 pytest** · alembic check **no drift** (no schema change) ‖ **web:** tsc --noEmit · **21 vitest**
  · vite build.
- **⚠ Follow-ups:** (a) **§3.4 bill due-date card deferred** — placement is Tommy's call (Ringkasan
  card recommended vs. 5th tab); clean insertion point left in `views/Ringkasan.tsx`. (b) **Prod
  static serving not wired** — dev is `vite` (proxies `/api`→:8000) + `uvicorn`; prod needs FastAPI
  `StaticFiles(web/dist)` or a reverse proxy (fold into S15 ops). (c) Recharts bundle ~159 kB gzip
  (fine for a 2-user LAN tool; code-split if it ever matters). (d) `npm audit` shows dev-dep
  advisories (vite/vitest transitive) — not runtime.
- **Committed to `main`** (`S11: Ringkasan dashboard …`), not pushed. Frontend framework
  (React + Vite + TS + Recharts) confirmed by Tommy. The read API is framework-agnostic, so a
  future framework change would touch only `web/`.
- **Next:** confirm framework/§3.4 → commit S11. Then S12 Portofolio (§3.2), S13 Belanja (§3.3 +
  S6 review queue), S14 Arus Kas (§3.5) — each needs its own read endpoint mirroring this one.

## Done (prev session) ✅ — S10 Telegram bot
- **S10 — Telegram ingestion bot.** A second entry point into the S9 pipeline, built as a
  Humble Object over `IngestStatement.execute` (reused verbatim with `uploaded_via=TELEGRAM`).
  - **`coffer/ingestion/detect.py` — pure account-type sniffer.** `detect_account_type(text)
    -> AccountType | None`, grounded in the anonymized fixture headers (`REKENING TAHAPAN`/
    `TAPRES` → savings; `REKENING KARTU KREDIT` → BCA card; `CIMB`/`NIAGA` or `Tgl. Statement`+
    `Tgl. Jatuh Tempo` → CIMB; `AJAIB`/`STOCKBIT` brand → portfolio). **Decision — bank
    HEADERS are checked before brand names:** a BCA RDN/Tapres statement mentions the broker
    ("AJAIB") in its transaction lines, so the definitive `REKENING TAPRES` header must win
    (a naive brand match mis-classified the Tapres fixture — caught by the test). Matches the
    specific `REKENING KARTU KREDIT` phrase, not generic `kartu kredit` (which CIMB also
    contains). 11 tests over every real fixture + false-positive guards.
  - **`coffer/ingestion/telegram.py` — the `TelegramIngest` use-case.** Pure + repo/port-driven
    (mirrors `pipeline`): domain repo Protocols + injected ports (`TelegramClient`,
    `PendingUploadStore`, the shared `PdfReader`, and an `Ingestor` Protocol satisfied by
    `IngestStatement`). Owns only the Telegram-specific concerns:
    - **Server-side allowlist** (SPEC §5): `telegram_user_id` → `member` via
      `MemberRepo.by_telegram_user_id`; an unknown user is **silently ignored** — no download,
      no reply (don't confirm the bot exists to a stranger).
    - **Account auto-detection**: decrypt + extract text, sniff the type, resolve to the
      household's accounts of that type. Exactly one → ingest immediately; **0 (undetected /
      no match) or >1 (ambiguous) → inline keyboard** to pick, completed on the callback.
      `callback_data = acct:{chat}:{msg}:{account_id}` (no random token — deterministic); the
      `PendingUpload` (file_id + uploader) is stashed keyed `chat:message`. Only the original
      uploader may complete their own pending upload; the chosen account is re-checked to
      belong to the household.
    - **Delete after ingest** (SPEC §4): on `INGESTED` the source message is deleted (untrusted
      transport); a REJECTED / DUPLICATE / needs-* outcome keeps it.
  - **Decision — password reconciliation (the long-open "Password entry mechanism").** Web =
    runtime prompt (Tommy's preference). **Telegram = stored `static` credential**, because an
    unattended upload can't prompt and a password typed into a Telegram chat is exactly the
    plaintext-on-untrusted-transport we delete messages to avoid. For encrypted PDFs the
    use-case tries the household's stored `static` `InstitutionCredential` secrets in memory
    (bounded by the household's few institutions — enumerated via `accounts.list_by_household`
    → distinct institutions → `credentials.by_household_institution`; **no new repo method**);
    the one that opens the PDF is the password passed to `execute`. None opens it → reply
    "🔒 needs password", no ingest. The tried password is never logged (security invariant).
    `derived`/`per_statement` Telegram decryption is a documented follow-up.
  - **`coffer/api/telegram_routes.py` — the webhook** (`POST /api/telegram/webhook`), the only
    publicly-exposed surface (SPEC §5). **Verifies `X-Telegram-Bot-Api-Secret-Token` with
    `hmac.compare_digest`** (fail-closed: empty configured secret → 403 everything) via a
    `verify_telegram_secret` dependency, parses a minimal `Update` (edge-only Pydantic; `from`
    read via alias), and dispatches `handle_document` (PDF documents only) / `handle_callback`.
    Always answers `200 {"ok": true}` for authentic requests so Telegram doesn't retry; 403 for
    unauthenticated. B008 per-file-ignored (FastAPI DI idiom).
  - **`coffer/api/telegram_adapters.py`** — `HttpxTelegramClient` (Bot API over httpx: two-step
    getFile→download, `sendMessage` with `inline_keyboard`, `deleteMessage`,
    `answerCallbackQuery`; injectable `transport` as a test seam; bot token only ever in the URL,
    never logged) + `InMemoryPendingUploadStore` (process-local — fine for a 2-person household;
    a stale pending just asks for a re-send; Redis/PG if it ever scales out).
  - **Wiring** (`app.py` includes the telegram router; `dependencies.py`): env-lazy singletons
    `_telegram_client()` (`COFFER_TELEGRAM_BOT_TOKEN` / `COFFER_TELEGRAM_API_BASE`),
    `_pending_store()` (**one shared instance** so the callback request finds the document
    request's pending), `get_webhook_secret()` (`COFFER_TELEGRAM_WEBHOOK_SECRET`),
    `build_telegram_use_case`/`get_telegram_use_case` (same commit-on-success unit-of-work as
    web upload). `httpx` promoted from a dev dep to a **runtime** dep.
  - **Tests (33 new):** `test_detect.py` (11); `test_telegram.py` (11, in-memory fakes) —
    allowlist silent-ignore / detect→ingest+delete / rejected+duplicate keep source / encrypted
    uses stored credential / encrypted no-credential→needs-password / ambiguous→keyboard /
    undetected→keyboard-of-all / callback completes+deletes / callback-from-other-user ignored /
    expired-pending; `test_telegram_webhook.py` (6, `TestClient`) — missing/wrong secret→403,
    document + callback dispatch, non-PDF + plain-text ignored; `test_telegram_adapters.py` (5,
    httpx `MockTransport`) — two-step download URL/bytes, inline-keyboard payload shaping,
    reply-markup omitted without buttons, delete/answer methods, pending store round-trip+single-use.
  - Full gate green: ruff · ruff-format · mypy --strict (66 files) · lint-imports (KEPT) ·
    **215 pytest** (33 new) · alembic check **no drift** (no schema change — Telegram uses only
    existing tables/repos).
  - **⚠ Known limitations / follow-ups:** (a) the webhook processes ingest **synchronously** in
    the request (fine for small PDFs / 2 users; a background queue is the scaling fix — Telegram
    times out ~60s); (b) `HttpxTelegramClient` errors bubble as 500 → Telegram retries — a broad
    route-level guard returning 200 is a hardening follow-up; (c) `InMemoryPendingUploadStore` is
    process-local; (d) masked-account auto-disambiguation (so two same-type accounts don't always
    need a keyboard tap) still deferred (the S6/S9 mask-normalization item); (e) `derived`/
    `per_statement` Telegram decryption not wired.
  - **Next:** **Phase C dashboards.** S11 Ringkasan (§3.1 net-worth hero + tide chart + Rincian
    Akun + bill due-date card — **confirm §3.4 placement with Tommy first**), S12 Portofolio,
    S13 Belanja (S8 read models + S6 review queue), S14 Arus Kas (S8 cash-flow). All consume the
    now-populated `networth_snapshot` + read models. Also: set the real Telegram webhook with
    `secret_token` (`setWebhook`) behind the tunnel; **capture the CIMB password** to finalize
    its `password_scheme` + seed the `institution_credential` so encrypted CIMB ingests via
    Telegram (the S2/§8 open item — now the only thing between the bot and encrypted CIMB).

## Done (prev session) ✅ — S9 ingestion API (FastAPI)
- **S9 — ingestion orchestration + web upload endpoint.** The pipeline
  `Decrypt → Parse → Validate → Dedup → Persist → Recompute` (SPEC §4) is now wired.
  - **`coffer/ingestion/pipeline.py` — the `IngestStatement` use-case.** Pure + repo-driven
    like every other stage: reads/writes only through the domain repo Protocols + injected
    infra **ports**, never imports `persistence`, testable with in-memory fakes (mirrors
    dedup/categorize/recompute). **Decision — the orchestrator lives in `ingestion`, not
    `api`.** api stays a Humble Object (router + DI + adapters); the use-case is the pipeline,
    so it belongs with the other stages. import-linter KEPT.
  - **Outcomes** (one per file, → SPEC §4 response): `INGESTED` (+ new/dup/holdings counts),
    `DUPLICATE` (file/content hash), `NEEDS_PASSWORD`, `NEEDS_ACCOUNT`, `NEEDS_REVIEW`
    (near-empty extraction / empty portfolio — not an alert), `REJECTED` (parser raised or
    validate rejected — `alert=True`). `IngestResult.alert` is True only for REJECTED.
  - **Ports (declared in `pipeline.py`, à la `HouseholdRecomputeLock`):**
    - `PdfReader` — decrypt-in-memory + text-extract in one adapter, returning
      `DecryptedPdf(text, was_encrypted)`. Near-empty routing uses the **shared
      `validate.check_extraction`** on `pdf.text` *before* `parse_text`, so a scanned PDF →
      `NEEDS_REVIEW` (not a parser raise). Concrete `PdfPlumberReader` (pikepdf→pdfplumber)
      in `coffer/api/adapters.py`.
    - `StatementArchive` — retains only the **encrypted original** (SPEC §4). Concrete
      `FilesystemStatementArchive`: a password-protected PDF is stored as-is; an
      **unencrypted arrival is Fernet-encrypted at rest** before writing (plaintext never on
      disk). Added `FieldCipher.encrypt_bytes/decrypt_bytes`.
  - **Decision — password is a runtime argument only** (Tommy prefers runtime entry over
    storing it — see Blockers). The reader raises `StatementDecryptionError` on wrong/missing
    → `NEEDS_PASSWORD`; the password is never logged. Wiring the `static`-scheme
    stored-credential path (via `InstitutionCredentialRepo`) is a clean extension — inject a
    reader that consults it. S10's unattended Telegram ingest will force this decision.
  - **`closing_balance` populated per family** (the S7 wiring note): savings = SALDO AKHIR;
    CC = Tagihan Baru / ENDING BALANCE (validate already asserts them equal); portfolio =
    `ParsedPortfolio.total_market_value()` — **broker cash excluded** (counted once via the
    mirroring RDN savings balance, the S7 no-double-count-by-definition). Portfolio persists
    a statement with `period_start == period_end == as_of` + its `holding` rows.
  - **`hit_count` bump wired (the S6-deferred loose end).** Added
    `LearnedRuleRepo.bump_hit_count(rule_id, *, by)` (Protocol + atomic `UPDATE … hit_count +
    by` in `SqlLearnedRuleRepo`); the use-case accumulates per-rule hits over the batch and
    bumps once each. **No migration** (`hit_count` column existed since S4). Updated the
    `test_categorize` fake to the widened Protocol.
  - **Account & parser resolution.** Web sends the manually-selected `account_id`; an
    unknown id → `NEEDS_ACCOUNT`. Household resolved via account→member→household. Parser
    chosen by `account_type` (`coffer/api/parsing.py` registry over each parser's pure
    `parse_text`); an unregistered type raises (wiring error). Masked-number cross-check of
    the selected account vs the parsed statement is **deferred** (mask normalization still
    open — see S6); a wrong selection surfaces naturally as a parse `REJECTED`. Tahapan vs
    Tapres both `bca_savings` share one engine → registry uses `bca_tahapan.parse_text`
    (the `parser_version` distinction is a reparse-only follow-up).
  - **`coffer/api/`** — `app.py` (`create_app()` factory + `app`), `routes.py`
    (`POST /api/statements`, multipart: `file` + `account_id` + optional `password` /
    `uploaded_by_member_id`), `schemas.py` (`IngestResponse` — edge-only Pydantic),
    `dependencies.py` (composition root: env-lazy `lru_cache` singletons, per-request
    session with **commit-on-success / rollback-on-error**, one shared `InProcessRecomputeLock`),
    `adapters.py`, `parsing.py`. Deps added: `fastapi`, `python-multipart`, `httpx` (dev).
    `B008` per-file-ignored for `routes.py` (FastAPI DI idiom).
  - **⚠ Known limitation — recompute lock vs transaction scope.** The `InProcessRecomputeLock`
    is released when `recompute_for_statement` returns, but the endpoint commits *after* the
    use-case (unit-of-work is the session dependency's job). So two concurrent **same-household**
    uploads could each recompute before the other commits and write a stale snapshot. Recompute
    is idempotent (each grid rebuilt from full history), so the **next** ingest self-heals it;
    the robust fix is a transaction-scoped `pg_advisory_xact_lock` on household id (already
    flagged in `recompute.py` for multi-process). Fine for a 2-person household; revisit if it
    bites.
  - **Tests (18 new):** `test_pipeline.py` (8, in-memory fakes) — needs-password / needs-account
    / needs-review / rejected(parser raise + balance discontinuity) / duplicate / the happy path
    (persist + per-row categorize [regex, learned-rule, uncategorized] + intra-batch dedup skip +
    hit_count bump + snapshot recompute) / portfolio (holdings persisted, cash excluded from
    closing_balance + snapshot); `test_api_ingestion.py` (6, `TestClient` + faked use-case) —
    counts surfaced, needs-password, rejected→alert, 422s, member forwarded; `test_pipeline_integration.py`
    (2, real SQL repos + Postgres) — CIMB fixture end-to-end (8 txns, closing 838303.83,
    liability snapshot net −838303.83) + exact re-upload → DUPLICATE; `test_api_adapters.py` (2)
    — archive encrypts-at-rest (no plaintext on disk) + stores encrypted as-is + reload round-trip.
  - Full gate green: ruff · ruff-format · mypy --strict (58 files) · lint-imports (KEPT) ·
    **182 pytest** (18 new) · alembic check **no drift** (no schema change — `bump_hit_count` is
    a method; `hit_count`/`closing_balance`/`encrypted_file_path` all pre-existed).
  - **Next:** **S10 — Telegram bot** (depends S9). Reuse the same `IngestStatement.execute`
    with `uploaded_via=TELEGRAM`. Webhook: verify `X-Telegram-Bot-Api-Secret-Token`
    (`hmac.compare_digest`), enforce the `telegram_user_id` allowlist **server-side**,
    auto-detect account from header text (the S9 registry is by `account_type`; S10 needs a
    text→account_type sniffer + inline-keyboard on ambiguity → resolves to an `account_id`),
    prompt for password on `NEEDS_PASSWORD`, and **delete the source message after successful
    ingest**. This is also where the unattended-password decision (stored `static` vs prompt)
    must be reconciled. S11–S14 dashboards consume the now-populated snapshots + read models.

## Done (prev session) ✅ — S8 spend + cash-flow read models
- **S8 — spend + cash-flow read models** (`coffer/domain/read_models.py`). Pure, repo-driven
  **query-side** use-cases for SPEC §3.3 (routine spend) + §3.5 (income / cash flow / savings).
  - **Decision — placement is `domain`, NOT `ingestion`.** Unlike validate/dedup/categorize/
    recompute (ingest pipeline stages, materialized on write), these are computed **on read**
    for the dashboard — there is no spend snapshot table in §2 (cf. `networth_snapshot`, which
    recompute writes on ingest). CLAUDE.md defines `ingestion` as exactly those 5 stages and
    `domain` as "use-case logic … depends on nothing"; a read model that reads only domain
    entities through the domain repo Protocols is domain use-case logic. First domain module
    that takes repo Protocols as args (textbook interactor) — import-linter KEPT (intra-domain).
  - **`routine_spend_estimate(txns, cats, *, window_months=6)`** (§3.3):
    - **Headline** = median of monthly **totals** of non-annual routine debits over the last
      ≤6 months of routine data; **+ amortized annual** on top (annual item's monthly-equiv =
      Σ its debits in the **latest month it appears** ÷ 12 — models one payment/year, avoids
      window-scaling a once-a-year cost). `estimate = base_median + annual_amortized`.
    - **Per-category breakdown** (`CategoryMedian`): monthly cats = median of their monthly
      totals over **observation months** (months the cat appears); annual cats = the amortized
      monthly-equiv. Deliberately does **not** sum to the headline (SPEC §3.3 note).
    - **Anomaly flags** (`AnomalyFlag`): txn `> 2 ×` its category's trailing median, guarded by
      `≥3` observations **and** `median ≥ ANOMALY_MEDIAN_FLOOR` (Rp 50k) — annual cats fail the
      ≥3 guard so their big single payment is never flagged.
    - **Cold start**: `< 3` months of routine data → `estimate=None`, `insufficient_data=True`
      (no misleading number), empty breakdown/anomalies.
  - **`cash_flow_summary(txns, cats, *, window_months=6)`** (§3.5): per calendar month
    (attributed by **txn date**), `income` = credits typed `income`; `spend` = debits typed
    `routine|discretionary|one_off`; `cash_flow = income − spend`; `savings_rate =
    (income−spend)/income` or **`None` when income is 0** (div-by-zero guard). Headline savings
    rate = aggregate `(Σincome−Σspend)/Σincome` over the trailing window. `transfer` /
    `investment_move` excluded (intra-household nets out via its `transfer` type).
  - **Decision — spend excludes uncategorized.** Only the 3 spend types count; `category_id=None`
    rows are pending a one-time review tag and are **not guessed** into a number (§3.3 "always
    visible, always correctable") — figures firm up as the queue is worked. Documented so the
    numbers are auditable.
  - **`compute_routine_spend` / `compute_cash_flow`** — repo-driven wrappers: gather all
    household transactions per account (`TransactionRepo.list_by_account`, mirroring recompute's
    load — no new repo method / no migration), fetch categories once, delegate to the pure core.
  - **Money is `Decimal` throughout** — exact `_median` (averages the two middle values), `/12`
    and `/income` on `Decimal`, no float anywhere.
  - **Tests (15, `tests/test_read_models.py`):** median-vs-sum-of-medians; even-count median;
    annual amortization; cold start; uncategorized/non-routine excluded; anomaly positive +
    floor-guard + observations-guard + sparse-no-div0; cash-flow income−spend + savings rate;
    savings-rate div-by-zero; date-attribution + month sort; both repo wrappers aggregate across
    accounts; empty household. Pure in-memory fakes over the domain Protocols (no Postgres).
  - Full gate green: ruff · ruff-format · mypy --strict (47 files) · lint-imports (KEPT) ·
    **164 pytest** (15 new) · alembic check **no drift** (no schema change this slice).
  - **Next:** Phase C interfaces. **S9 (ingestion API)** is the critical-path unblocker now that
    S2–S7 are done; it orchestrates decrypt→parse→validate→dedup→persist→recompute and populates
    `statement.closing_balance` per family (see S7 note below). The S8 read models feed the
    **S13 Belanja** (routine estimate + breakdown + review queue) and **S14 Arus Kas** (cash-flow
    bars + savings-rate line) dashboards. **v1 tuning note:** `ANOMALY_MEDIAN_FLOOR` (Rp 50k) and
    the 3–6 month window are documented constants — revisit against real data once S9 lands.

## Done (prev session) ✅ — S7 net-worth snapshot recompute
- **S7 — recompute** (`coffer/ingestion/recompute.py`). Pure, repo-driven stage (mirrors
  S3/S5/S6): reads through the domain repo Protocols only, tested with in-memory fakes.
  - **`compute_snapshot(...)`** — one grid point's net worth by **carry-forward** (SPEC
    §3.1): per account, value = `closing_balance` of the most recent statement with
    `period_end <= grid` (else the account is absent). Buckets by `account_type`:
    `bca_savings→cash`, `*_credit_card→liability`, `*_portfolio→portfolio`;
    `net_worth = cash + portfolio − liability`. Unknown type → `ValueError` (refuse to
    silently drop an account, cf. `validate.py`); a completeness test pins every enum.
  - **`affected_grids(...)`** — the event-driven window: `grid(period_end)` up to (but
    not including) the account's **next** statement's grid, else through the household
    horizon. So a backfilled Feb (after Mar exists) updates **only** Feb; a lone
    statement carries forward to the horizon; a same-month superseding statement → `[]`.
  - **`recompute_for_statement(...)`** (hot path on ingest) + **`recompute_all(...)`**
    (onboarding / post-reparse rebuild). Both **serialized per household** via an injected
    `HouseholdRecomputeLock`; `InProcessRecomputeLock` (thread lock/household) is the
    single-process impl — multi-process must use a Postgres advisory lock
    (`pg_advisory_xact_lock` on household id). Idempotent: each grid recomputed from full
    history, so re-running converges (the "concurrent ingests don't corrupt" guarantee).
  - Grid helpers `month_end` / `iter_month_ends` (leap-Feb + year-boundary safe).
  - **Decision — added `statement.closing_balance` (nullable `Decimal`).** §2's model
    omitted any per-statement balance, but §3.1 needs "the most recent statement
    balance" to carry forward — recompute has no data source without it. Added to the
    `Statement` entity + `StatementRow` + statement mapper + **new Alembic migration**
    `741f49a1c0c3` (chained off S4's `1764a988dedb`; up/down + `alembic check` → **no
    drift**). Minimal (one nullable column, no data churn). **S9 must populate it per
    family at persist:** savings = SALDO AKHIR; CC = Tagihan Baru (liability magnitude);
    portfolio = **Σ holdings market value** (excludes broker cash — see next).
  - **Decision — RDN↔broker-cash double-count resolved BY DEFINITION** (the long-flagged
    S7 issue). §3.1 stacks "portfolio **market value**", not broker cash → `portfolio_total`
    = holdings market value only. The broker's cash (Ajaib "Saldo RDN" / Stockbit "Cash
    Investor") is the *same rupiah* as the mirroring BCA Tapres/RDN savings balance, so it
    is counted **once**, on the bank side, in `cash_total`. **No account-number matching
    needed** → this sidesteps the masked-acct normalization S6 deferred to S9 (for net
    worth at least). Trade-off: broker cash with no uploaded RDN bank statement is invisible
    to net worth — matches §3.1's literal definition and avoids the worse double-count.
  - **Tests (22):** 20 pure (`tests/test_recompute.py`) — grid/leap-Feb, async period-end
    alignment, carry-forward + most-recent-wins, RDN no-double-count, every-type-bucketed,
    None-balance, all `affected_grids` window cases (backfill / gap / horizon / first /
    same-month-superseded), repo-driven recompute + idempotency + empty-household, lock
    serialization (spy + real-thread same-household serialized / distinct-household
    concurrent); 1 `closing_balance` Decimal round-trip (`test_persistence_repos.py`);
    1 Postgres integration wiring the real Sql repos through `recompute_all`
    (`tests/test_recompute_integration.py`).
  - **Clean Architecture:** ingestion → domain only; import-linter KEPT.
  - Full gate green: ruff · ruff-format · mypy --strict · lint-imports · `alembic check`
    (no drift) · **149 pytest** (22 new).
  - **Next:** S8 (spend/cash-flow read models; depends S4+S6). **S9 wiring:** after persist,
    set `statement.closing_balance` per family (above), then call
    `recompute_for_statement(household_id, account_id, period_end, …)` under the
    household lock. For a portfolio, `closing_balance = ParsedPortfolio.total_market_value()`
    (NOT + `cash_balance`).

## Done (prev session) ✅ — S6 categorization + learned rules
- **S6 — categorization + learned-rule engine** (`coffer/ingestion/categorize.py`). Pure,
  repo-driven ingest-time classifier (mirrors S3/S5 shape) + the learned-rule lifecycle.
  - **`classify(txn, *, household_accounts, categories, active_rules) -> Categorization`** —
    SPEC §3.3 precedence, highest first:
    1. **structural / intra-household transfer** — `counterparty_acct` resolves to a household
       account → the seeded `transfer` category; `source=parser`. A hard fact, so it's the top
       tier and **beats a learned rule**. Missing seed transfer category → `ValueError` (setup
       error, refuse to guess — cf. `validate.py`).
    2. **learned rule** — active `LearnedRule` on **structured** fields: recipient acct (strong
       key) first, then amount (weak, within `match_amount_tolerance`). `source=learned_rule`;
       `matched_rule_id` returned so the caller bumps `hit_count`. Never matches on description.
    3. **regex** — first household `category.match_pattern` (case-insensitive `re.search`) that
       hits the description; `source=parser`. Sentinel `@…` patterns are skipped (identity
       markers, not regexes).
    4. **uncategorized** → `(None, None)`, queued for a one-time human tag.
  - **`categorize(...)`** — thin repo-driven wrapper (fetches accounts/categories/active rules
    once via the domain Protocols); S9 fetches once per batch.
  - **`build_learned_rule(...)`** — `RuleKey.COUNTERPARTY_ACCT` (safe, needs a recipient acct,
    no confirmation) vs `RuleKey.AMOUNT` (amount-only → **requires `confirm_amount_only=True`**,
    else `ValueError` — amounts collide across unrelated spend, SPEC §3.3).
  - **`retag(...)`** — a manual tag records an `Override`; if the prior assignment came from a
    learned rule, that rule is **deactivated** (refinement over fighting), else override only.
    Timestamps injected (`now=`) — no clock dependency, deterministic.
  - **`seed_categories(household_id)`** — the day-one regex rule set (SPEC §3.3 seed + Q4:
    transport/BBM/tol/groceries/food-delivery/utilities/BPJS/KPR/IPL/pharmacy/subscriptions +
    annual STNK/asuransi/sekolah), the `KARTU KREDIT/PL` transfer, and the intra-household
    sentinel category. Unpersisted (`id=None`); S9/onboarding persists → assigns ids.
  - **Decision — category_source §2↔§3.3 reconciliation:** §2's enum has 4 values
    (`parser|learned_rule|manual|onboarding`) but §3.3's precedence names a distinct *regex*
    tier with no source value. Kept the authoritative 4-value enum; **both** structural and
    regex assignments stamp `parser` (for UI/audit they're the same: "system-set on ingest,
    correctable" vs learned/manual). No enum/migration change. Flag if distinct regex
    provenance is wanted later (migration-free — sources stored as strings).
  - **Decision — intra-household acct match is exact** (whitespace-trimmed). Masked-vs-full
    account-number normalization needs the real seeded formats → deferred to S9 account seeding
    (didn't invent a masking scheme). Engine + precedence are what S6 owns.
  - **Clean Architecture:** ingestion → domain (entities/enums/repos) + parsers only; import
    linter KEPT.
  - **Tests (23, `tests/test_categorize.py`):** regex/case-insensitive/uncategorized/sentinel;
    learned-rule acct + amount(±tolerance) + acct-beats-amount + learned-beats-regex; intra-
    household detected + beats-learned + missing-seed-raises + non-member-not-intra; repo
    wrapper (active-only); rule build (acct no-confirm / amount needs-confirm / acct needs
    counterparty); retag deactivates-learned vs override-only; seed coverage. Pure in-memory
    fakes satisfy the repo Protocols (no Postgres).
  - Full gate green: ruff · ruff-format · mypy --strict · lint-imports · **127 pytest**
    (23 new; against a throwaway `postgres:16`).
  - **Next:** S7 (net-worth snapshot recompute; depends on S4 — carry-forward grid + RDN↔broker
    double-count) or S8 (spend/cash-flow read models; depends on S4+S6). S9 will call
    `categorize` per deduped row before persist, stamping `category_id`/`category_source`, and
    bump `hit_count` on `matched_rule_id`.

## Done (prev session) ✅ — S5 dedup
- **S5 — dedup stage** (`coffer/ingestion/dedup.py`). The three SPEC §4 layers as one pure,
  repo-driven stage returning a routing decision (mirrors S3's `validate` shape):
  - **Layer 1 — file hash** (`file_hash`, SHA-256 of raw bytes) → `DUPLICATE_FILE`: exact
    re-upload rejected outright, contributes no rows.
  - **Layer 2 — content hash** (`content_hash`, SHA-256 of the parsed object's own
    `content_hash_fields()`) → `DUPLICATE_CONTENT`: catches a non-byte-identical re-export.
    Works for both `ParsedStatement` and `ParsedPortfolio` (each supplies its own fields).
  - **Layer 3 — `transaction_dedup_key`** (SHA-256 of `account_id,date,description,debit,credit`;
    amounts as `str(Decimal)`, same canonical form as `content_hash_fields`) → per-row
    skip-and-log. Overlapping-period statements dedup at row level and the batch is **never**
    failed. Also dedups **within** one batch (the `dedup_key` column is UNIQUE, so identical
    intra-batch rows would break the persist).
  - Returns `DedupResult(outcome, file_hash, content_hash, new_transactions, duplicate_transaction_count)`;
    each `new_transactions` item is a `KeyedTransaction` carrying the `dedup_key` computed once
    here so the persist stage never recomputes it. `file_hash`/`content_hash` always returned
    (even on a dup) so S9 can stamp the `Statement` without recomputing.
  - **Clean Architecture:** depends only on the domain repo **Protocols** (`StatementRepo`/
    `TransactionRepo`) + `coffer.parsers` types — dependency points inward; import-linter KEPT.
  - **`account_id` is an argument** — account resolution (and the "needs account confirmation"
    outcome) is S9 orchestration, not dedup's job.
  - **Tests (12, `tests/test_dedup.py`):** hash stability/sensitivity; file-hash reject;
    content-hash re-export; file-hash precedence; new-statement all-rows-keyed; overlapping-period
    row dedup without failing the batch; intra-batch identical-row dedup; portfolio content-hash +
    dividend-row dedup. Pure in-memory fakes satisfy the repo Protocols (no Postgres needed).
  - Full gate green: ruff · ruff-format · mypy --strict · lint-imports · **104 pytest**
    (against a throwaway `postgres:16`).
  - **Next:** S6 (categorization + learned rules; depends on S4+S5) or S7 (recompute; depends
    on S4). S9 will map `DedupResult` → the upload-response counts (new / duplicates skipped),
    alongside the S3 `ValidationResult` → (rejected / needs manual review).

## Done (prev session) ✅ — S4 persistence
- **S4 — persistence layer** (SQLAlchemy 2.0 + Alembic + Postgres). All 11 SPEC §2 tables.
  - **Domain layer now non-empty:** `coffer/domain/{enums,entities,repositories}.py` — pure
    value objects + repository **Protocols**. Depends on nothing; import-linter still KEPT.
    Moved `PasswordScheme` into `domain.enums` (single source); `ingestion.decrypt` re-exports it.
  - **Persistence:** `models.py` (ORM, money = `Numeric` never `Float`; `Numeric(18,2)` for IDR
    balances, `Numeric(28,8)` for broker lots/prices), `mappers.py` (domain↔row at the boundary),
    `repositories.py` (11 `Sql*Repo`), `crypto.py` (Fernet `FieldCipher`), `config.py` (URL + key
    from env, never hardcoded), `db.py` (engine/session helpers).
  - **Encryption at rest (SPEC §6):** `institution_credential.secret` is encrypted into the
    `password_enc` column by the credential mapper — domain sees plaintext, DB stores ciphertext.
    Test asserts the raw column is NOT the plaintext and only the cipher recovers it.
  - **Migration:** `migrations/` at repo root (outside the `coffer` package, so mypy/ruff/
    import-linter don't scan generated files). One revision; `alembic check` shows no drift;
    up→down→up tested against a throwaway DB. URL/key read from env in `env.py`.
  - **Tests (13):** round-trip per aggregate against a **real Postgres** (per skill — not SQLite),
    Decimal exactness (`838303.83`, fractional avg_price), dedup lookups (file/content/dedup_key),
    telegram-id + account-number resolution, active-only learned rules, snapshot upsert idempotent
    on `(household_id, grid_date)`. `tests/conftest.py`: per-test transaction rollback isolation.
  - **CI:** added a `postgres:16` service + `COFFER_DATABASE_URL`/`COFFER_ENCRYPTION_KEY` env
    (throwaway key — protects only synthetic test data). Full gate green: ruff · ruff-format ·
    mypy --strict · lint-imports · **92 pytest**.
  - **RDN double-count note (In progress ⚠) NOT yet handled** — that's S7 recompute logic; S4 only
    provides the storage (multiple RDN accounts per member persist fine).
  - **Next:** S5 dedup (uses `by_file_hash`/`by_content_hash`/`by_dedup_key`), then S6/S7.


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
- **S1 COMPLETE** — all 6 parsers built (cimb_kartu_kredit, bca_tahapan, bca_tapres,
  bca_kartu_kredit, ajaib_portfolio, stockbit_soa). Ready to move to S3/S4.
- **Deferred (not blocking):** Stockbit cash-SOA dividend rows → `transactions` (feeds §3.5
  income). Portfolio parsers currently extract holdings + cash only.
- **✅ Net-worth RDN double-count — RESOLVED at S7 (by definition).** `portfolio_total` = holdings
  **market value only** (§3.1); broker cash counted once via the mirroring BCA Tapres/RDN savings
  balance in `cash_total`. Known RDN accounts (all Tommy's, still relevant to S4/S9 account seeding):
  `4958…` = **Ajaib RDN** (= "Saldo RDN"), `4996…` = **Stockbit RDN** (= "Cash Investor"), `4959…`
  = a dormant RDN (bal 1.33). No account-number matching needed for net worth (see the S7 decision).
- **Edge case handled:** empty statement (`* TIDAK ADA TRANSAKSI PADA BULAN INI *`, zero mutasi)
  parses + reconciles (commit `c63c11a`) — found via the dormant `4959…` sample.
- **Contract decision taken (portfolio shape):** chose a **separate `ParsedPortfolio`** type
  (not extending `ParsedStatement`) — snapshot with `as_of`, `holdings`, `cash_balance`,
  optional `transactions`; no balance reconcile. Downstream (ingestion/persistence/api) will
  branch on statement-vs-portfolio family. Revisit if a single-type model is preferred.

## Done (this session) ✅
- **S3 — validation gate** (`coffer/ingestion/validate.py`). Generalizes the per-parser
  reconcile into one pipeline gate returning a **routing decision** (not a raise):
  `OK` / `NEEDS_MANUAL_REVIEW` (near-empty extraction → OCR/manual, no alert) /
  `REJECTED` (schema mismatch or hard cash/CC balance discontinuity → `alert=True`, no ingest).
  - Continuity is re-derived independently of the parser (defense in depth, SPEC §6): asset
    (`bca_savings`: opening + Σcr − Σdb == closing) vs liability (`*_credit_card`: opening +
    Σdb − Σcr == closing, plus Tagihan Baru == closing). Unknown `account_type` → `ValueError`
    (refuse to guess a money sign convention) — programmer error, not bad data.
  - Portfolio lot continuity stays **soft** (SPEC §3.2): never REJECTED for lot movement; only
    a structurally empty snapshot (no holdings + no cash) routes to manual review.
  - `check_extraction(text)` is the near-empty gate (`MIN_EXTRACTED_CHARS = 50`), extracted from
    the BCA engine's inline check so the whole pipeline shares one threshold. Parsers keep their
    own internal raise as their contract ("raise, never return partial data").
  - 16 tests (`tests/test_validate.py`): tampered savings + CC rejected & alert; dormant savings
    OK; near-empty → manual; portfolio soft path; real CIMB + Ajaib fixtures round-trip → OK.
    Full gate green: ruff · ruff-format · mypy --strict · lint-imports · **79 pytest**.
- **`bca_tapres` + shared BCA Rekening Koran engine** — commit `a487365`. Tapres sample was a
  brokerage RDN held as a Tapres (same format as Tahapan; header + glued-`DB` differences).
  Extracted `_bca_rekening_koran.py` engine (both header/period variants); `bca_tahapan` +
  `bca_tapres` now thin adapters. 9 tests; Tahapan's 14 stayed green through the refactor.
  → **S1 now complete (6/6 parsers).**
- **`bca_tahapan` verified on a 2nd real statement** — the May-26 statement parsed + reconciled
  (88 txns, 8 pages); May's SALDO AKHIR (1,271,334.69) == June's SALDO AWAL exactly, validating
  cross-statement continuity (§3.1). Not committed as a fixture (offer stands).
- **S2 — decryption stage (static path)** — commit `8bb3269`. Ingestion-layer in-memory
  decrypt (`coffer/ingestion/decrypt.py`): `is_encrypted`, `decrypt_to_stream`,
  `to_plaintext_stream`; `PasswordScheme` enum; wrong password raises without leaking it.
  Password is a **runtime argument** — this layer never sources/stores it (so `static`
  doesn't force env/at-rest storage; entry mechanism decided at S4/S9). 6 tests.
  - **CIMB confirmed encrypted** (real `…559760447.pdf`); scheme = **static** (Tommy).
  - ⏳ End-to-end check on the real PDF pending: run the scratchpad `verify_cimb_real.py`
    (now uses a `getpass` no-echo prompt — no env var/file).
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
1. **S4 — persistence** (unblocked; depends only on S0). Postgres schema for SPEC §2 incl.
   `holding`; repo interfaces in `domain`, impls in `persistence`; ParsedStatement +
   ParsedPortfolio both persist; encryption at rest. (`sqlalchemy-2x` skill ready.)
   - Remember the RDN↔broker-cash double-count when seeding accounts (see In progress ⚠).
2. **S1 tail (deferred, not blocking):** Stockbit cash-SOA dividend rows → `transactions`.
3. **Optional:** commit the May-26 Tahapan as a 2nd regression fixture (cross-statement chain).
4. **S9 wiring note:** the pipeline (`decrypt → parse → validate → dedup → …`) now has its
   validate stage; S9 maps `ValidationResult` → the upload response counts (rejected / needs
   password / needs account / new / dup).

## Live decisions
- §3.4 bill card lives on Ringkasan, **below the hero / above the KPI row** (placement locked 2026-07-18).
- Money is `Decimal` end-to-end; `id-ID` formatting only at the UI edge.
- Learned rules match structured fields (recipient acct / amount), never description regex.
- Intra-household (Tommy↔Priskila) transfers auto-`transfer` and net out at household level.
- Retention: encrypted original only; plaintext never on disk; reparse re-decrypts.

## Blockers (need Tommy)
- ℹ️ **`bca_tapres` sample** — RESOLVED: provided (the RDN/Tapres statement); parser built.
- ℹ️ **CIMB password scheme** — RESOLVED: **static** (same every month).
- ✅ **Password entry mechanism** — RESOLVED at S10. **Web = runtime prompt** (Tommy's
  preference, S9); **Telegram = stored `static` `InstitutionCredential`** (unattended can't
  prompt; a chat-typed password defeats message-deletion). No env-file password storage. The
  only remaining runtime input is the **CIMB password itself** (below) to seed its credential.
- ℹ️ **Portfolio contract shape** — RESOLVED by best-judgment while away: separate
  `ParsedPortfolio` type. Flag if you'd prefer a single-type model.
- ✅ **§3.4 bill-aggregator placement** — RESOLVED (2026-07-18): a **Tagihan Jatuh Tempo card on
  Ringkasan, directly below the net-worth hero and above the KPI row** (honors "at top" while keeping
  the hero as the frozen opening moment; chosen over above-hero and the SPEC bottom/near-Rincian
  option). **Built in S16 (2026-07-19):** `Statement.due_date`/`.minimum_payment` + migration
  `79a1b0e9dc7c` + pipeline persist + `compute_tagihan` read model + `GET /api/dashboard/tagihan/{hh}`
  + the self-fetching `Tagihan.tsx` card at the locked anchor in `views/Ringkasan.tsx`. Done.
- ✅ **Frontend framework** — RESOLVED: **React + Vite + TS + Recharts** (confirmed; S11 merged to `main`).
- ⛔ **Samples**: BCA CC, BCA savings, Ajaib, Stockbit — unblock remaining S1 parsers.
- ⚠️ **CIMB edge cases**: no cash-advance / multi-card / multi-page statement seen yet.
