# Coffer — PROGRESS

> Persistent memory across cold sessions. Read this first. Update it last.
> Format: what's done, what's in progress, what's next, and any live decisions/blockers.

_Last updated: 2026-07-14_

## Done (this session) ✅ — S8 spend + cash-flow read models
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
- Money is `Decimal` end-to-end; `id-ID` formatting only at the UI edge.
- Learned rules match structured fields (recipient acct / amount), never description regex.
- Intra-household (Tommy↔Priskila) transfers auto-`transfer` and net out at household level.
- Retention: encrypted original only; plaintext never on disk; reparse re-decrypts.

## Blockers (need Tommy)
- ℹ️ **`bca_tapres` sample** — RESOLVED: provided (the RDN/Tapres statement); parser built.
- ℹ️ **CIMB password scheme** — RESOLVED: **static** (same every month).
- ℹ️ **Password entry mechanism** — Tommy prefers runtime entry over storing it (env-file
  leak risk). S2 decrypt is already password-source-agnostic; finalize at S9: getpass prompt
  / in-memory-for-session / OS keychain vs. encrypted-at-rest. Note: unattended Telegram
  ingest (S10) needs the password available without a human prompt — reconcile then.
- ℹ️ **Portfolio contract shape** — RESOLVED by best-judgment while away: separate
  `ParsedPortfolio` type. Flag if you'd prefer a single-type model.
- ⛔ **§3.4 bill-aggregator placement** — card on Ringkasan (recommended) vs. 5th tab — confirm before S11.
- ⛔ **Samples**: BCA CC, BCA savings, Ajaib, Stockbit — unblock remaining S1 parsers.
- ⚠️ **CIMB edge cases**: no cash-advance / multi-card / multi-page statement seen yet.
