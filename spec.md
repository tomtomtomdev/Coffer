# Coffer — Spec

*Household finance consolidator. A guarded strongbox for the family ledger: private, self-hosted, encrypted at rest, decrypted only in memory.*

> **Changelog (this revision)** — what changed vs. the previous spec, so you can review the diff fast:
> - **§2** — added `income` and `investment_move` to `category.type` enum (the latter was referenced in §3.3 but never defined); added `password_enc` to `account`; added `parser_version` + `edited_by`/`edited_at` to `transaction`; added `cadence` to `category`; added `override` table for per-transaction reclassification.
> - **§3.1** — replaced ambiguous "period_end as X-axis" with an explicit **point-in-time monthly-grid snapshot rule** (carry-forward), plus out-of-order / backfill recompute semantics and serialization.
> - **§3.2** — added IDX corporate-action handling (splits/bonus/rights) so lot discontinuities don't hard-fail.
> - **§3.3** — pinned down the estimand (median-of-monthly-totals for headline, per-category medians for breakdown), added non-monthly/amortized items, added divide-by-zero + cold-start guards, separated per-transaction override from rule creation.
> - **§3.5 (new)** — Income + Cash Flow + Savings Rate.
> - **§4** — added a **PDF decryption stage** (BCA/broker statements are frequently password-protected), made CC **line-item** extraction explicit, added Telegram message deletion after ingest, added recompute serialization.
> - **§5** — split public webhook from LAN/VPN dashboard.
> - **§6/§7** — new rows: encrypted PDFs, async-period alignment, CC line-item vs summary, income/flow, PDF retention, reparse-without-clobber.
>
> **Decisions locked (§8 resolved):** (1) single shared login → per-member access model dropped; `member` retained only for attribution + Telegram mapping. (2) CIMB format pending a sample — parser deferred. (3) self-host on existing TrueNAS/home server; webhook via tunnel. (4) routine category seed set expanded (see §3.3). (5) one shared password **per institution** → moved off `account` into `institution_credential`. (6) purge raw PDF after validated ingest.
>
> **This revision:** hardened the CIMB (and general) **decryption stage** — CIMB statements arrive password-protected (the sample was pre-`-unlock`ed). Added `password_scheme` (static/derived/per_statement) to `institution_credential`; decrypt **in memory** only (plaintext never on disk); persist the **encrypted original** so reparse can re-decrypt, reconciling the retention rule with the reparse requirement. Parser accepts a decrypted stream. CIMB's specific scheme is the one open item (§4, §8).
>
> **Design reconciliation (Claude Design hi-fi handoff):** named the frozen visual target + tokens + Bahasa Indonesia / `id-ID` IDR locale in §5. Two findings folded in: (a) **Priskila is a household member**, so `TRSF...PRISKILA` is an **intra-household transfer** — auto-typed `transfer` and netted at household level (§3.3); (b) the **bill due-date aggregator (§3.4) has no home** in the four-tab design — flagged, recommend a card on Ringkasan.

---

## 1. Purpose

Coffer consolidates BCA savings/credit card statements (multiple accounts, multiple household members) and stock portfolio statements (Ajaib, Stockbit) into one synchronized web dashboard. Ingestion happens via web upload or a Telegram bot. The system deduplicates uploads, tracks net worth over time, estimates routine monthly spending, tracks household cash flow / savings rate, and surfaces upcoming bill due dates.

**In scope (this phase):** Net worth dashboard + chart, portfolio consolidation, spend categorization + routine spend estimate, income + cash-flow / savings-rate view, bill due-date aggregator, multi-account/multi-member support, Telegram ingestion, dedup.

**Out of scope (this phase):** Bandarmologi cross-referencing, notifications beyond in-app, budgeting/goal-setting, mobile app, multi-tenant SaaS.

---

## 2. Data Model

```
household (id, name)
member (id, household_id, name, telegram_user_id)   -- attribution + Telegram mapping only; auth is a single shared login (§5)
account (id, member_id, institution, account_type, account_number_masked, currency)
institution_credential (id, household_id, institution,
                        password_enc, password_scheme[static|derived|per_statement])
          -- password_enc: the statement password (static scheme) OR the inputs to derive it
          --   (derived scheme, e.g. DOB / card digits). per_statement scheme stores nothing and
          --   prompts on each upload. See §4 for the CIMB decryption flow.
statement (id, account_id, period_start, period_end, file_hash, content_hash,
           uploaded_via, uploaded_by_member_id, uploaded_at,
           encrypted_file_path, is_encrypted, parser_version)
          -- encrypted_file_path: the ORIGINAL (still-encrypted) PDF is retained for reparse;
          --   plaintext is NEVER persisted (§4). parser_version enables targeted reparse.
transaction (id, statement_id, account_id, date, description, debit, credit,
             balance, category_id, category_source[parser|learned_rule|manual|onboarding],
             counterparty_name, counterparty_acct, dedup_key, raw_ref,
             edited_by, edited_at)                       -- counterparty_*: parsed from transfer descriptions; category_source: provenance so learned/auto assignments are visible & correctable
category (id, household_id, match_pattern, label,
          type[routine|discretionary|transfer|one_off|investment_move|income],
          cadence[monthly|annual|irregular])             -- cadence drives how it enters the routine estimate
override (id, transaction_id, category_id, member_id, created_at)
          -- per-transaction manual reclassification (audit record of a human tag)
learned_rule (id, household_id, category_id,
              match_counterparty_acct, match_amount, match_amount_tolerance,
              created_from_transaction_id, active, created_at, hit_count)
          -- created when a user tags a transaction and opts to generalize; matches on structured
          --   fields (recipient acct and/or amount), NOT on the noisy description string
holding (id, account_id, statement_id, ticker, name, lot_balance, avg_price,
         market_price, market_value, unrealized_pl, as_of_date)
networth_snapshot (id, household_id, grid_date, cash_total, credit_liability_total,
                    portfolio_total, net_worth)          -- grid_date is month-end (see §3.1), not period_end
```

`account_type` enum: `bca_savings`, `bca_credit_card`, `cimb_credit_card`, `ajaib_portfolio`, `stockbit_portfolio`.

`dedup_key` = hash of `(account_id, date, description, debit, credit)` — used for transaction-level dedup on overlapping statement periods.

**Category type semantics:**
- `routine` — recurring living spend, enters the routine estimate.
- `discretionary` — spend, but not counted as "routine."
- `transfer` — same-owner or intra-household money movement, **not** spend (includes CC bill payment `KARTU KREDIT/PL`).
- `one_off` — real spend but explicitly excluded from routine estimate (large irregular purchases).
- `investment_move` — funding/withdrawing brokerage (Ajaib/Stockbit); not spend, not a same-owner bank transfer.
- `income` — salary and other credits; drives cash flow / savings rate (§3.5).

---

## 3. Features

### 3.1 Net Worth Dashboard + Tide Chart

- Stacked area / line chart (Recharts or Chart.js) showing, **per monthly grid point**, per household:
  - Cash (savings balances, both members)
  - Portfolio market value (Ajaib + Stockbit combined)
  - Credit card liability (negative stack, from `tagihan baru`)
  - Net line overlay = cash + portfolio − liabilities
- Toggle: household total vs per-member breakdown.

**Point-in-time snapshot rule (resolves async statement periods).** Statement `period_end` dates are *not* aligned across accounts (savings ≈ calendar month-end; BCA/CIMB cards close on a billing-cycle day; broker SOAs at month-end). Summing values as-of different dates produces a subtly wrong net line. Therefore:

1. Define a fixed monthly **grid** at calendar month-end.
2. For each account and each grid date `G`, the account's value is its **most recent statement balance with `period_end <= G`** (carry-forward). If no statement exists yet at/before `G`, the account contributes nothing to that grid point.
3. `net_worth(G)` = Σ carried-forward account values at `G`.
4. `networth_snapshot.grid_date` is the grid month-end, **never** the upload date and **never** a single account's `period_end`.

**Recompute semantics (event-driven, handles out-of-order + backfill).** When a statement for account `A` with `period_end = D` is ingested:
- Recompute all grid points `>= grid(D)` up to (but not including) the next existing statement's grid for the **same account** — because carry-forward propagates a new balance forward until the next known statement.
- This means a **backfilled** statement (e.g., Feb arriving after Mar already exists) correctly updates only Feb's grid point, not Mar's.
- Recompute must be **serialized per household** (lock or single-writer queue) so two simultaneous uploads (Telegram + web) can't race the snapshot.

Backed by `networth_snapshot`, recomputed on ingest (not on-read) so the dashboard loads fast.

### 3.2 Portfolio Consolidator

- Merge `holding` rows from Ajaib + Stockbit by ticker.
- Table: ticker, combined lots, avg price (weighted), market value, unrealized P/L, broker breakdown on expand.
- Household-level total row.
- **Combined unrealized P/L is only valid when both brokers price as-of the same date.** If broker `as_of_date`s differ, show per-broker P/L and label the combined figure "as-of mixed dates" rather than presenting a false single number.
- **IDX corporate actions.** Splits, bonus shares, and rights issues make `lot_balance` discontinuous between consecutive statements. The portfolio parser must **not** hard-fail on lot discontinuity (unlike the balance-continuity check for cash accounts). Detect the discontinuity, and either flag it for the user to confirm the action or record a `corporate_action` note; adjust cost basis accordingly so avg-price math stays sane.

### 3.3 Spend Categorization + Routine Monthly Spending Estimate

- Rule-based categorizer: editable `category.match_pattern` (regex/substring) → `label` + `type` + `cadence`.
- Seed rules from observed patterns: `GRAB*` → Transport, `QR.*INDOMA` → Groceries, `SHOPEEFOOD|GRABFOOD` → Food Delivery, `KARTU KREDIT/PL` → CC Payment (`transfer`, excluded from spend).
- **Intra-household transfers (design reconciliation).** The design confirms the two members are **Tommy & Priskila**, so the earlier ambiguous `TRSF...PRISKILA` counterparty is now settled: a transfer between Tommy's and Priskila's own accounts is an **intra-household transfer** — not spend on one side, not income on the other. Detect it automatically: if a transfer's `counterparty_acct` (or name) resolves to another household member's account, auto-type it `transfer` and **net it out of household-level** spend/income/cash-flow so the same rupiah isn't counted twice. Remaining named counterparties that are *not* household members (`HADI NUR WAHID`, the `DANA` e-wallet, etc.) stay uncategorized on first sight and are tagged once via a learned rule keyed on `counterparty_acct` (see runtime tagging below).

**Seed routine categories (Q4).** Tracked from day one; `cadence` drives §3.3 step 4 amortization.
- *Monthly:* Utilities (PLN electricity, PDAM water, internet — IndiHome/Biznet, mobile data), BPJS / health premium, Transport (Grab/Gojek), Fuel (Pertamina/Shell), Toll & e-toll, Groceries (Indomaret/Alfamart + Superindo/Ranch/Hypermart), Food Delivery (GrabFood/ShopeeFood/GoFood), Mortgage (KPR installment), Estate / IPL maintenance fee, Childcare & baby supplies (formula/diapers), Pharmacy & clinic, Subscriptions (streaming, iCloud/Google).
- *Annual (`cadence = annual`, amortized):* STNK road tax, vehicle insurance, health/life insurance, school fees.
- Recurring named counterparties (rent/allowance vs. savings) are **not** guessable by the system — resolved via the one-time onboarding tag (§7 "Routine classification").

**What counts as spend.** Spend = savings-account debits **+** credit-card line-item charges, **minus** anything typed `transfer` / `investment_move` / `income`. This requires that CC parsers extract **individual line items** into `transaction` rows (see §4) — not just the summary block — otherwise all card-based discretionary spend is invisible to the estimate.

**Routine spending estimate algorithm:**
1. Filter transactions where `category.type = routine` (excludes `transfer`, `one_off`, `investment_move`, `income`, `discretionary`).
2. Group by month, sum debits per category.
3. **Headline number = median of monthly *totals*** across the last 3–6 months. (Note: this differs from the sum of per-category medians — categories rarely peak in the same month, so summing per-category medians understates a typical total month. Use median-of-monthly-totals for the pinned figure and per-category medians for the breakdown, and don't expect the breakdown to sum to the headline.)
4. **Non-monthly routine items** (`cadence = annual`, e.g. STNK/road tax, insurance, school fees, annual subscriptions) have a monthly median of zero and would drop out. Instead: annualize the observed amount and amortize to a monthly-equivalent, added on top of the median-of-monthly-totals.
5. **Anomaly flag with guards.** Flag any transaction `> 2 ×` the category's trailing median as "review — possibly non-routine." Guard against divide-by-zero / sparse categories: require **≥ 3 monthly observations** and apply a **minimum median floor** before the multiplier test fires; below that, flag nothing (insufficient data).
6. **Cold start.** With `< 3` months of data, show "insufficient data for estimate" rather than a misleading number.

**Runtime tagging + auto-generalization (learned rules).** Any transaction can be tagged with a category at runtime (one tap in the dashboard, or via the Telegram review flow). When tagging, the user can opt to **generalize**, which creates a `learned_rule` that auto-classifies future matches. Matching is on **structured fields only** — recipient account number (`counterparty_acct`) and/or amount — never on the raw `description` string:

- **Recipient account number is the strong, safe key.** Exact match. This is the intended path for the recurring named-counterparty problem (`TRSF...` to a person's account): tag it once, and every future transfer to that same account defaults to the chosen category. Preferred whenever a `counterparty_acct` is present.
- **Amount is a weak key and is guarded.** Amount alone is low-signal — a Rp 50,000 GrabFood order, a Rp 50,000 transfer, and a Rp 50,000 top-up collide. So amount is only used to *refine* a recipient match, or (for fixed-amount recurring bills with no recipient acct) as an exact match with an optional `match_amount_tolerance`. An **amount-only rule with no recipient acct requires explicit confirmation** at creation, because of the collision risk to the spend estimate.
- **Applied as a default, always visible, always correctable.** A learned-rule assignment sets `transaction.category_source = learned_rule` and is surfaced as "auto-categorized (learned)" so a wrong rule can't silently corrupt net worth / spend numbers. `category_source` also lets you audit and bulk-fix.
- **Refinement over fighting.** If the user re-tags a transaction that a learned rule had classified, offer to narrow or deactivate that rule (`active = false`) rather than repeatedly overriding the same pattern. `hit_count` surfaces which rules are doing work.
- **Precedence on ingest:** parser-assigned → learned_rule (recipient acct, then amount) → `category.match_pattern` regex → uncategorized (queued for review). A manual tag always wins and is recorded in `override`.

This refines the earlier stance (regex-on-description was rejected because merchant strings are noisy — dozens of distinct Grab IDs). Generalizing on **structured** fields is safe and is exactly what's wanted; regex rules remain available but stay an explicit, manual opt-in.

- Display: bar chart of routine spend by category, trended monthly, with the single estimate number pinned at top.

### 3.4 Bill Due-Date Aggregator

- Pull `tanggal jatuh tempo` + `pembayaran minimum` per credit card statement (BCA + CIMB, both members).
- Combined widget: card name, holder, due date, days remaining, minimum payment, full statement balance.
- Sort ascending by days remaining; red flag under 3 days.
- **Design gap (reconciliation).** The frozen design has four tabs — Ringkasan, Portofolio, Belanja, Arus Kas — and this feature is **not one of them**. It needs a home before build: either (a) a due-dates card on **Ringkasan** near "Rincian Akun" (recommended — it's glanceable and the liability data is already on that screen), or (b) a fifth tab. Pick one and get it into the design; right now it's specified but unplaced.

### 3.5 Income + Cash Flow + Savings Rate (new)

Net worth tracks the *stock*; this tracks the *flow*, which is nearly free once every credit is already being parsed.

- Categorize credits typed `income` (salary + other).
- **Monthly cash flow** = income − (routine + discretionary + one_off spend); transfers and investment_moves excluded.
- **Savings rate** = (income − spend) / income, trended monthly.
- Display: monthly income vs spend bars with a savings-rate line; savings rate pinned as a headline number alongside the routine-spend estimate.
- Handles the same async-period concern as §3.1 — attribute income/spend to the month of the transaction `date`, not upload date.

---

## 4. Ingestion Pipeline

```
Telegram Bot (webhook) ──┐
                          ├──> Ingestion API ──> Decrypt ──> Parser ──> Validate ──> Dedup ──> DB ──> Recompute snapshot (serialized)
Web Upload ───────────────┘
```

- **Decryption stage (runs before extraction).** BCA e-statements, **CIMB Niaga credit-card statements**, and some broker SOAs are delivered password-protected; `pdfplumber` raises on encrypted input before any parser runs. (The provided CIMB sample was pre-decrypted — its filename ends `-unlock` — so in the real Telegram/web flow the incoming file *is* encrypted and this stage is mandatory, not optional.)

  **Flow:**
  1. On upload, detect encryption (`pikepdf.open(..., password="")` raises `PasswordError`, or `is_encrypted`). Set `statement.is_encrypted`.
  2. Resolve the password by the institution's `password_scheme`:
     - `static` — decrypt with the stored `password_enc` (the common case: one owner-set password reused every month, fits the "one password per institution" decision).
     - `derived` — compute the password from stored inputs (e.g. cardholder DOB `DDMMYYYY`, or last-4 of the card) via a per-institution derivation function.
     - `per_statement` — the PDF carries a document-specific password (plausible here: the sample filename embeds a per-statement reference `559760447`). Nothing is stored; prompt on every upload.
  3. Decrypt **in memory** (`pikepdf` → `BytesIO`) and hand the decrypted stream to the parser. **Plaintext is never written to disk.**
  4. On wrong/missing password, reply "🔒 needs password" and wait — never hard-fail silently, never log the attempted password.
  5. Persist only the **encrypted original** (`encrypted_file_path`, access-restricted); the same stored password/scheme re-decrypts it for any future reparse. This reconciles the retention rule (no plaintext at rest) with the reparse requirement (§6).

  > **Open — which scheme does CIMB use?** Determinable only from a genuinely locked CIMB PDF (the uploaded one was already unlocked). If the password is the same across months → `static`. If it's the statement reference number or a DOB/card derivation → `derived`/`per_statement`. Tommy unlocked the sample, so he knows the actual password; capturing it (and whether it changes monthly) closes this. Until then the parser is complete but the CIMB decryption path is unverified end-to-end.
- **Telegram bot:** listens for PDF documents. Maps `telegram_user_id` → `member`. Auto-detects account type from header text (`REKENING TAHAPAN`, `REKENING KARTU KREDIT`, CIMB letterhead, `Stockbit` / `ajaib` branding). If ambiguous, replies with inline-keyboard buttons to pick the account. **After successful ingest, delete the source Telegram message** — bot chats are not E2E-encrypted, so the raw statement should not linger on Telegram's servers (treat Telegram strictly as untrusted transport).
- **Web upload:** same ingestion API, drag-and-drop, manual account selection available upfront.
- **Parser modules**, one per `(institution, account_type)`:
  - `parsers/bca_tahapan.py`  — extracts `counterparty_name` / `counterparty_acct` from transfer line descriptions (feeds learned rules, §3.3).
  - `parsers/bca_tapres.py`  — same counterparty extraction.
  - `parsers/bca_kartu_kredit.py`  — **extracts individual line items** into `transaction` rows *and* the summary block (`tagihan baru`, due date, minimum). Line items are required by §3.3.
  - `parsers/cimb_kartu_kredit.py`  — **built** against a real MC GOLD statement. Accepts an already-**decrypted** stream/bytes/path (decryption is the stage's job, §4 above). Extracts line items + summary (Tagihan Baru, due date, min payment); `CR` suffix = credit, else charge; DD/MM txn dates with statement-year inference; statement-level continuity check `opening + Σcharges − Σcredits == closing == Tagihan Baru`. Fixture-based tests pass; the encrypted-input path is exercised by the decryption stage, not the parser.
  - `parsers/ajaib_portfolio.py`
  - `parsers/stockbit_soa.py`
  - Use `pdfplumber` for text extraction (statements are text-based, not scanned).
  - Each parser stamps `statement.parser_version`.
- **Validation (before dedup):**
  - Schema check (expected column count / fields present).
  - Cash-account balance continuity: `saldo_awal + Σ(mutasi) == saldo_akhir` — hard-fail + alert on mismatch, do not ingest.
  - Near-empty extraction check → route to OCR / manual review (guards against scanned PDFs).
  - Portfolio lot continuity is *soft* (see §3.2 — corporate actions are legitimate discontinuities).
- **Dedup, three layers:**
  1. File hash (SHA-256 of raw bytes) — exact re-upload rejected outright.
  2. Content hash of `(account_number, period_start, period_end, opening_balance, closing_balance)` — catches re-exports that aren't byte-identical.
  3. Transaction-level `dedup_key` — catches overlapping statement periods; skip-and-log per row rather than failing the whole batch.
- **Retention.** Persist only the **encrypted original** (`encrypted_file_path`, access-restricted) plus parsed data + hashes. Decrypted plaintext exists only in memory during parse and is never written to disk. If a statement arrives unencrypted, encrypt it at rest before storing (so nothing plaintext-financial sits on disk). Reparse re-decrypts the stored original on demand (§4 step 5).
- **Response surfaces all outcomes:** "✅ 42 new, ⏭️ 3 duplicates skipped, ⚠️ 1 needs account confirmation, 🔒 1 needs password."

---

## 5. Tech Stack & Deployment

- **Frozen visual target:** `design_handoff_coffer_dashboard/` (Claude Design, hi-fi). Four views — Ringkasan (§3.1), Portofolio (§3.2), Belanja (§3.3), Arus Kas (§3.5) — with final tokens in `MEASUREMENTS.md`. Recreate faithfully in the chosen framework; the prototype's hand-drawn SVG is the *what-to-draw* spec, not production code.
- **Design tokens (authoritative):** paper `#eaecf6`, card `#fff`, ink `#1c1d26`; accents cash/green `#17b26a`, portfolio/primary violet `#7c5cff`, liability/rose `#f04766`, annual-cadence orange `#f59e0b`. Card radius 24/20, elevation `0 6px 22px rgba(28,29,60,.06)`. Type: Plus Jakarta Sans (display/UI, figures at weight 800) + IBM Plex Mono (tabular numerics, eyebrows, tx descriptions).
- **UI language & locale:** interface copy is **Bahasa Indonesia**; all money is IDR formatted with `Intl.NumberFormat('id-ID', {style:'currency', currency:'IDR', maximumFractionDigits:0})`, short form `jt` (juta) / `M` (miliar) on chart axes. This is now a fixed product decision (the schema's `account.currency` still exists for the deferred multi-currency case, §6).
- Frontend: SvelteKit or Next.js (design suggests React + Vite or SvelteKit); real charting lib (Recharts / visx / ECharts / Chart.js) rather than hand-drawn SVG.
- Backend/parsing: Python FastAPI + pdfplumber
- DB: Postgres (encryption at rest — see §6)
- Telegram: python-telegram-bot, webhook mode
- Hosting: self-hosted (home server / small VPS) given data sensitivity — no SaaS-grade infra needed for a 2-user household app.

**Network exposure (resolves the self-host contradiction).** The Telegram webhook requires a public HTTPS endpoint, but the dashboard/API should not be internet-exposed. Split them:
- Expose **only** the webhook publicly, ideally via a tunnel / reverse proxy, with Telegram secret-token verification and a server-side `telegram_user_id` allowlist.
- Keep the dashboard + full API on LAN / VPN.
**Auth (resolved).** Single shared household login — no per-member access control; both members see full detail. `member` exists only for attribution (which account, `uploaded_by_member_id`) and Telegram mapping. This simplifies §7's access-model concern away entirely.

---

## 6. Technical Gaps to Resolve

| Gap | Risk | Notes |
|---|---|---|
| **Encrypted / password-protected PDFs** | High | BCA e-statements (and some broker SOAs) are routinely password-protected; `pdfplumber` throws before any parser runs. Resolved by the §4 decryption stage + `account.password_enc`. Day-one blocker if omitted. |
| **Async statement-period alignment** | High | Each account's `period_end` differs; naive per-period summing mis-dates net worth. Resolved by §3.1 monthly-grid carry-forward + out-of-order recompute. Structural — expensive to retrofit after snapshots exist. |
| **CC line-item vs summary parsing** | High | If CC parsers extract only the summary, all card-based spend is invisible to §3.3. Resolved by making line-item extraction explicit in §4; savings-side `KARTU KREDIT/PL` stays `transfer` to avoid double-count. |
| **Parser brittleness** | High | Bank layouts change silently. Schema validation + balance continuity (`saldo_awal + Σmutasi == saldo_akhir`) hard-fail and alert rather than ingest bad data. |
| **Balance reconciliation** | High | Per-statement assertion that computed running balance matches stated `saldo_akhir`; mismatch blocks ingestion and flags for review. |
| **At-rest encryption** | High | Real financial data for two people. Postgres encryption at rest; encrypt/access-restrict PDF originals; never log raw statement content; `password_enc` encrypted. |
| **No OCR fallback** | Medium | "Text extraction near-empty" check routes to OCR / manual review instead of ingesting an empty scanned PDF. |
| **PDF retention policy** | Medium | New. Keeping decrypted financial PDFs indefinitely is pure liability. Define retention (e.g., keep encrypted original N months then purge, or purge after successful+validated ingest) and document it. |
| **Reparse without clobbering overrides** | Medium | New. Fixing a parser bug requires reingest, but must not wipe hand-set `category_id` / `override` rows. Use `statement.parser_version` for targeted reparse; reapply `override` rows after reparse. |
| **Telegram bot security & transport** | Medium | Verify Telegram secret token; enforce `telegram_user_id` allowlist server-side; delete source message after ingest; treat Telegram as untrusted transport. |
| **Category rule maintenance** | Medium | Regex rules drift as merchants appear (dozens of Grab merchant IDs already). Consider a local-LLM-assisted classifier (fits the RX 6800 XT / ROCm setup) for uncategorized transactions, with human confirmation before trusted. |
| **No test suite specified** | Medium | Parsers are highest-risk. Fixture-based unit tests using anonymized sample statements per format, run in CI before any parser change ships. Include corporate-action and encrypted-PDF fixtures. |
| **Timezone / period edge cases** | Low | Snapshot dates use the §3.1 grid (month-end), not upload date; transactions attributed by `date`. |
| **Multi-currency not handled** | Low | All accounts IDR today; `account.currency` exists but unused. Fine to defer; noted so net-worth math doesn't silently assume IDR later. |

---

## 7. Business / Product Gaps to Resolve

| Gap | Risk | Notes |
|---|---|---|
| **No income / cash-flow concept** | Medium | New. Net worth is a stock; savings rate (income − spend) is usually the single most motivating household number and nearly free once credits are parsed. Resolved by §3.5 + `income` type. |
| **"Routine" classification is subjective** | Medium | Recurring transfers to named counterparties could be rent/allowance or one-off. System can't infer intent; add a light onboarding step to tag a few recurring counterparties once, plus `cadence` for annualized items. |
| **Two people, one app — access model** | Resolved | Single shared login (§5); both members see full detail. No per-member access control needed. |
| **Backup / disaster recovery** | Medium | Self-hosted + financial data = disk failure loses the ledger. Add the DB (+ `institution_credential`) and the retained **encrypted** originals to the existing TrueNAS SCALE + restic pipeline — reuse, don't rebuild. Backup never contains plaintext PDFs (§4 retention). |
| **Definition of "done" for MVP** | Medium | Scope v1 to features 1, 2, 3, 3.5, 5 (bill aggregator) + Telegram ingestion + dedup; defer categorization ML, budgets, notifications to v2. |
| **No reconciliation-with-bank-app step** | Low | Nothing confirms parsed net worth matches BCA mobile / Ajaib *right now* (statements are lagged). Monthly manual "spot check" reminder rather than presenting stale numbers as current truth. |
| **No audit trail for manual edits** | Low | Resolved by `transaction.edited_by` / `edited_at` + `override` table. Cheap; avoids "who changed this category" disputes. |

---

## 8. Decisions (resolved)

1. **Auth:** single shared household login. No per-member access control; `member` is attribution + Telegram mapping only. (§5)
2. **CIMB Niaga CC format:** **parser built** (see §4). Format resolved from the real sample; `cimb_kartu_kredit.py` passes fixture tests on the balance-continuity invariant. **One thing outstanding for CIMB: the password scheme.** The sample was uploaded pre-decrypted (`-unlock` in its filename), so the encrypted path is specified (§4) but unverified. Needs a genuinely locked CIMB PDF — or just you telling me the password and whether it's the same every month — to set `password_scheme` to `static` / `derived` / `per_statement`. Other caveats unchanged: validated on one statement, no cash-advance / multi-card / multi-page case seen yet.
3. **Hosting:** self-host on the existing TrueNAS / home server. Webhook exposed via tunnel; dashboard/API on LAN/VPN. (§5)
4. **Routine categories from day one:** utilities, transport, groceries, mortgage, plus the fuller seed set in §3.3 (BPJS, fuel, tolls, food delivery, IPL/estate fee, childcare/baby, pharmacy, subscriptions; annual: STNK, insurance, school fees). Recurring named counterparties resolved via one-time onboarding tag.
5. **Statement passwords:** one password **per institution** (`institution_credential`), with a `password_scheme` of `static` (stored), `derived` (computed from stored inputs), or `per_statement` (prompt each time). CIMB's scheme is TBD — see decision 2 and §4. (§2, §4)
6. **PDF retention:** persist only the **encrypted original** + parsed data + hashes; plaintext lives only in memory during parse, never on disk; reparse re-decrypts on demand. (§4)

### Still requires you — at runtime, not in spec
- The **CIMB statement password** and whether it changes monthly, to set `password_scheme` (§4). You unlocked the sample, so you already know it.
- Tagging your specific recurring counterparties the first time each appears (`TRSF...` to named people = rent / allowance / savings — unknowable by the system). One-time tap per counterparty; the mechanism is built, the intent is yours.
- Providing a CIMB sample statement to unblock its parser (see decision 2).
