# Coffer — PROGRESS

> Persistent memory across cold sessions. Read this first. Update it last.
> Format: what's done, what's in progress, what's next, and any live decisions/blockers.

_Last updated: 2026-07-13_

## Done (this session) ✅ — S4 persistence
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
- **⚠ Net-worth double-count to handle at S7:** BCA **Tapres/RDN** accounts hold the same money
  the broker statements already report as cash. Known RDN accounts (all Tommy's): `4958…` =
  **Ajaib RDN** (= Ajaib "Saldo RDN"), `4996…` = **Stockbit RDN** (= Stockbit "Cash Investor"),
  `4959…` = a dormant RDN (bal 1.33). Recompute must net/dedupe the RDN↔broker-cash identity, not
  sum both. Also relevant to S4 account seeding (multiple RDN accounts per member).
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
