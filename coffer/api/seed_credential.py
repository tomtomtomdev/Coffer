"""Seed an institution statement-password credential (S2/§8 operational tool).

An encrypted statement (e.g. CIMB, or the BCA credit card) can only be ingested
*unattended* (via the Telegram bot) if the household's ``static`` password is stored,
Fernet-encrypted at rest, in ``institution_credential``. Web upload prompts for the
password at runtime, so this is only needed for the unattended path.

This is a thin operational CLI — a Humble Object over the persistence layer, like
``coffer.api.ops``:

    python -m coffer.api.seed_credential --household-id 1 --institution cimb \
        [--scheme static] [--replace]

Security invariants (CLAUDE.md, SPEC §6):
  * The password is **never** a command-line argument (it would leak into the shell
    history and the process list). It is read from a no-echo ``getpass`` prompt, or —
    for automation/tests — the ``COFFER_SEED_SECRET`` environment variable.
  * The password is **never logged or printed** — not on success, not in errors.
  * The plaintext only lives in memory; the repo's mapper encrypts it at rest. The same
    ``COFFER_ENCRYPTION_KEY`` this tool uses must be the one the running app uses, or the
    app will not be able to decrypt it.

The database (``COFFER_DATABASE_URL``) and Fernet key (``COFFER_ENCRYPTION_KEY``) come
from the environment (never hardcoded), exactly like the API's composition root.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from enum import StrEnum

from coffer.domain.entities import InstitutionCredential
from coffer.domain.enums import PasswordScheme
from coffer.persistence.config import Settings
from coffer.persistence.crypto import FieldCipher
from coffer.persistence.db import create_db_engine, create_session_factory
from coffer.persistence.repositories import SqlHouseholdRepo, SqlInstitutionCredentialRepo

SEED_SECRET_ENV = "COFFER_SEED_SECRET"


class SeedStatus(StrEnum):
    """What the seed did (drives the CLI exit code + message)."""

    CREATED = "created"  # no prior credential → added
    REPLACED = "replaced"  # prior credential overwritten (--replace)
    EXISTS = "exists"  # prior credential kept (no --replace) — no change
    NO_HOUSEHOLD = "no_household"  # the household id does not exist


def resolve_secret(scheme: PasswordScheme, raw: str | None) -> str | None:
    """Validate the supplied password against the scheme and return what to store.

    ``static`` / ``derived`` require a non-empty secret. ``per_statement`` stores nothing
    (a new password each time; it is prompted at ingest, never persisted), so a secret
    must NOT be supplied. Raises ``ValueError`` on a mismatch (surfaced as a CLI error).
    """
    if scheme is PasswordScheme.PER_STATEMENT:
        if raw:
            raise ValueError("per_statement scheme stores no secret — omit the password")
        return None
    if not raw:
        raise ValueError(f"{scheme.value} scheme requires a statement password")
    return raw


def seed_credential(
    households: SqlHouseholdRepo,
    credentials: SqlInstitutionCredentialRepo,
    *,
    household_id: int,
    institution: str,
    scheme: PasswordScheme,
    secret: str | None,
    replace: bool,
) -> SeedStatus:
    """Store (or replace) one household's statement-password credential.

    There is no DB unique constraint on ``(household, institution)``, so this
    checks-before-add to avoid silently duplicating a row. With ``replace`` an existing
    credential is deleted first (delete-then-add). The repo encrypts ``secret`` at rest;
    it is never logged here.
    """
    if households.get(household_id) is None:
        return SeedStatus.NO_HOUSEHOLD
    existing = credentials.by_household_institution(household_id, institution)
    if existing is not None and not replace:
        return SeedStatus.EXISTS
    if existing is not None:
        assert existing.id is not None
        credentials.delete(existing.id)
    credentials.add(
        InstitutionCredential(
            household_id=household_id,
            institution=institution,
            password_scheme=scheme,
            secret=secret,
        )
    )
    return SeedStatus.REPLACED if existing is not None else SeedStatus.CREATED


def _read_secret(scheme: PasswordScheme, institution: str) -> str | None:
    """The secret from ``COFFER_SEED_SECRET`` if set, else a no-echo prompt (skipped for
    ``per_statement``, which stores nothing). Validated against the scheme."""
    raw = os.environ.get(SEED_SECRET_ENV)
    if raw is None and scheme is not PasswordScheme.PER_STATEMENT:
        raw = getpass.getpass(f"Statement password for {institution} ({scheme.value}): ")
    return resolve_secret(scheme, raw)


def main(argv: list[str] | None = None) -> int:
    """CLI seam. Exit codes: 0 created/replaced · 2 bad input · 3 already exists (use
    --replace) · 4 no such household."""
    parser = argparse.ArgumentParser(
        prog="python -m coffer.api.seed_credential",
        description="Seed an institution statement-password credential (encrypted at rest).",
    )
    parser.add_argument("--household-id", type=int, required=True)
    parser.add_argument("--institution", default="cimb")
    parser.add_argument(
        "--scheme", default=PasswordScheme.STATIC.value, choices=[s.value for s in PasswordScheme]
    )
    parser.add_argument(
        "--replace", action="store_true", help="overwrite an existing credential for this pair"
    )
    ns = parser.parse_args(argv)
    scheme = PasswordScheme(ns.scheme)

    # Read + validate the secret BEFORE touching the environment/DB, so a bad invocation
    # fails fast without a connection.
    try:
        secret = _read_secret(scheme, ns.institution)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    factory = create_session_factory(create_db_engine(settings.database_url))
    cipher = FieldCipher(settings.encryption_key)
    with factory() as session:
        status = seed_credential(
            SqlHouseholdRepo(session),
            SqlInstitutionCredentialRepo(session, cipher),
            household_id=ns.household_id,
            institution=ns.institution,
            scheme=scheme,
            secret=secret,
            replace=ns.replace,
        )
        if status in (SeedStatus.CREATED, SeedStatus.REPLACED):
            session.commit()

    if status is SeedStatus.NO_HOUSEHOLD:
        print(f"error: no household with id {ns.household_id}", file=sys.stderr)
        return 4
    if status is SeedStatus.EXISTS:
        print(
            f"credential for household {ns.household_id} / {ns.institution!r} already exists — "
            "pass --replace to overwrite (unchanged).",
            file=sys.stderr,
        )
        return 3
    print(
        f"{status.value}: {ns.institution!r} credential for household {ns.household_id} "
        f"(scheme={scheme.value}). Secret encrypted at rest; not logged."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - operational entry point
    raise SystemExit(main())
