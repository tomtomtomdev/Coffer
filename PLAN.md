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

### S6 · Categorization + learned rules ⬜
- Regex `category` rules; `learned_rule` engine matching **structured fields** (`counterparty_acct`
  primary, amount guarded); precedence parser → learned → regex → uncategorized; `category_source`
  stamped; `override` handling with rule-refinement.
- **Intra-household transfer detection:** counterparty resolves to another member's account →
  auto-`transfer`, netted at household level (SPEC §3.3).
- **Test:** learned rule by recipient acct auto-classifies future txns; amount-only rule requires
  confirmation; intra-household transfer nets out; override refines rather than duplicates.
- **Depends on:** S4, S5.

### S7 · Net-worth snapshot recompute ⬜
- Carry-forward month-end grid (SPEC §3.1); event-driven recompute on ingest; handle out-of-order/
  backfill; **serialized per household** (single-writer/lock).
- **Test:** async period ends align to grid; backfilled Feb-after-Mar updates only Feb; two
  concurrent ingests don't corrupt the snapshot.
- **Depends on:** S4.

### S8 · Spend + cash-flow read models ⬜
- Routine estimate = median of monthly totals + amortized annual; per-category medians;
  anomaly flag with ≥3-obs + floor guards; cold-start < 3 months. Income / cash flow / savings rate.
- **Test:** median-of-totals ≠ sum-of-category-medians (both correct); annual item amortizes;
  sparse category doesn't divide-by-zero; <3 months → no estimate.
- **Depends on:** S4, S6.

---

## Phase C — Interfaces

### S9 · Ingestion API (FastAPI) ⬜
- Orchestrates Decrypt → Parse → Validate → Dedup → Persist → Recompute (serialized).
- Web upload endpoint; response surfaces new/dup/needs-account/needs-password counts.
- **Depends on:** S2, S3, S4, S5, S7.

### S10 · Telegram bot ⬜
- Webhook (secret-token verify), server-side `telegram_user_id` allowlist, account auto-detect,
  inline keyboard on ambiguity, password prompt, **delete source message after ingest**.
- Public webhook via tunnel; dashboard/API stays on LAN/VPN (SPEC §5).
- **Depends on:** S9.

### S11 · Dashboard — Ringkasan (§3.1) ⬜
- Net-worth hero + tide chart (Gabungan/Per-Anggota toggle), KPI row (deep-links),
  Rincian Akun, **+ bill due-date card (§3.4 — its home; confirm placement first)**.
- Match frozen design tokens exactly; Bahasa Indonesia; `id-ID` IDR formatting; real charting lib.
- **Depends on:** S7, S8; design handoff.

### S12 · Dashboard — Portofolio (§3.2) ⬜
- Mixed-as-of-date caveat banner, summary cards, holdings table with CORP ACTION tags.
- **Depends on:** S4 (holdings), S1 (portfolio parsers).

### S13 · Dashboard — Belanja (§3.3) ⬜
- Routine hero + 6-month sparkline, per-category medians with cadence tags, review queue with
  source badges + Tag/Ubah actions wired to S6 categorization.
- **Depends on:** S6, S8.

### S14 · Dashboard — Arus Kas (§3.5) ⬜
- Income-vs-spend bars + savings-rate line, source/type breakdown lists.
- **Depends on:** S8.

### S15 · Backup + ops ⬜
- Add DB + **encrypted** originals to the existing TrueNAS SCALE + restic pipeline; monthly
  spot-check reminder (SPEC §7).
- **Depends on:** S4.

---

## Open items blocking specific slices (need Tommy)
- **CIMB password scheme** → unblocks S2 end-to-end (SPEC §8). You unlocked the sample; the password + whether it changes monthly is all that's needed.
- **§3.4 bill-aggregator placement** (card on Ringkasan vs. 5th tab) → confirm before S11.
- **Real samples**: BCA CC, BCA savings, Ajaib, Stockbit → unblock the remaining S1 parsers.
- **CIMB edge cases**: a statement with cash advance / multi-card / multi-page → parser follow-up on S1.
