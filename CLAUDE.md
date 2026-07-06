# CLAUDE.md — Coffer

Operating rules for Claude Code. Read this, then `PROGRESS.md`, then act.

Coffer is a private, self-hosted household finance consolidator for a two-person
household (Tommy & Priskila). It parses Indonesian bank/broker statements and shows
net worth, portfolio, routine spend, and cash flow. Real financial data — treat
security and correctness as non-negotiable.

---

## Session workflow (every session)
1. Read `PROGRESS.md` — it is the persistent memory across cold sessions. It says
   what's done, what's in progress, and what's next.
2. Read `SPEC.md` for the behavior of the slice you're on, and `PLAN.md` for order.
3. Work **exactly one slice** from `PLAN.md`. Do not widen scope.
4. TDD: **write the failing test first (red)** → minimal code to green → refactor.
5. Run the full gate before you consider the slice done (see "Definition of done").
6. **Update `PROGRESS.md`** at the end: mark the slice, note decisions, list the next step.

Never start coding a slice before its dependencies (per `PLAN.md`) are green.

---

## Architecture — Clean Architecture, dependencies point inward
Layers, outer → inner. **Imports may only point inward.** Enforced by `import-linter`;
a violating import fails CI.

- `coffer/web` — UI (frozen design). Depends on api contracts only.
- `coffer/api` — FastAPI + Telegram bot. Orchestrates use-cases.
- `coffer/ingestion` — pipeline stages: decrypt, validate, dedup, categorize, recompute.
- `coffer/persistence` — Postgres repos (implement domain interfaces).
- `coffer/parsers` — pure statement parsers → `ParsedStatement`.
- `coffer/domain` — entities, value objects, repository *interfaces*, use-case logic.
  **Depends on nothing.**

Rules:
- `domain` imports no other layer. `parsers` import only `domain` types.
- Persistence/api/web depend on `domain` via interfaces, never the reverse.
- Business logic lives in `domain`/`ingestion`, never in parsers, repos, or UI.

---

## Money & locale
- **All money is `Decimal`. Never float, ever.** Parse with `Decimal(s.replace(",", ""))`
  for the CIMB comma-thousands/dot-decimal format; each parser documents its own format.
- IDR everywhere this phase. `id-ID` currency formatting happens **only at the UI edge**
  (`Intl.NumberFormat('id-ID', …)`), never in domain/persistence.
- UI copy is **Bahasa Indonesia**. Match the frozen design tokens in the handoff /
  `MEASUREMENTS.md` exactly — colors, radii, type (Plus Jakarta Sans + IBM Plex Mono).

---

## Parser rules
- A parser is a **pure function** on already-decrypted text/stream → `ParsedStatement`.
  Decryption is the ingestion layer's job; parsers never touch encryption or disk.
- **Raise, never return partial data.** Structural mismatch → `StatementParseError`;
  balance mismatch → `BalanceReconciliationError`. A silent bad parse corrupts net worth.
- Balance continuity is a **hard gate**: cash `saldo_awal + Σmutasi == saldo_akhir`;
  CC `opening + Σcharges − Σcredits == closing == Tagihan Baru`. Portfolio lot continuity
  is **soft** (corporate actions are legitimate discontinuities).
- Every parser has fixture-based tests using **anonymized** text (amounts/dates kept so
  reconciliation is real; PII stripped). Include a tampered-amount → raises test.
- **Don't invent a format.** No real sample → no parser. Flag it as blocked in `PROGRESS.md`.

---

## Security invariants (do not violate)
- **Never log** statement passwords or raw statement content.
- **Plaintext PDFs never touch disk.** Decrypt in memory (`pikepdf` → `BytesIO`); persist
  only the **encrypted original** + parsed data + hashes. If a statement arrives unencrypted,
  encrypt it at rest before storing.
- **Never commit** real PII, real account numbers, or real PDFs to the repo or fixtures.
- Telegram webhook: verify the secret token; enforce the `telegram_user_id` allowlist
  **server-side**; delete the source message after successful ingest.
- Public surface is the webhook only (via tunnel); dashboard/API stays LAN/VPN.

---

## Categorization rules
- Precedence on ingest: parser → learned rule → regex → uncategorized (queued). A manual
  tag always wins and is recorded in `override`.
- Learned rules generalize on **structured fields** (`counterparty_acct` primary; amount
  guarded) — **never** on the noisy `description` string. Amount-only rules require explicit
  confirmation.
- **Intra-household transfers net out**: if a counterparty resolves to another member's
  account, auto-type `transfer` and exclude from household spend/income.
- Re-tagging a learned-rule result **refines/deactivates** the rule; it doesn't just override.

---

## Definition of done (per slice)
- The slice's tests are green; the full suite is green.
- `ruff`, `mypy --strict`, and `lint-imports` (layer contract) pass.
- No secret/PII/plaintext-PDF introduced.
- `PROGRESS.md` updated with status + next step.
- Committed with a message referencing the slice id (e.g. `S6: learned-rule engine`).

## Don't
- Don't widen beyond the current slice or skip the red step.
- Don't add the LLM-assisted classifier in v1 (it's v2; the structured learned-rule engine is v1).
- Don't put business logic in parsers, repos, or components.
- Don't present stale numbers as current truth — respect the carry-forward grid and the
  mixed-as-of-date caveat.
