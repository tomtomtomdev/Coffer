"""Tests for the institution-credential seed CLI (`coffer.api.seed_credential`).

Core logic runs against real Postgres via the `session` fixture (like the other
persistence tests); the pure validator + the CLI's input-validation exits need no DB.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from coffer.api.seed_credential import (
    SEED_SECRET_ENV,
    SeedStatus,
    main,
    resolve_secret,
    seed_credential,
)
from coffer.domain.entities import Household
from coffer.domain.enums import PasswordScheme
from coffer.persistence.crypto import FieldCipher
from coffer.persistence.repositories import SqlHouseholdRepo, SqlInstitutionCredentialRepo


def _household(session: Session) -> int:
    hh = SqlHouseholdRepo(session).add(Household(name="Yohanes"))
    assert hh.id is not None
    return hh.id


def test_seed_creates_credential(session: Session, cipher: FieldCipher) -> None:
    hid = _household(session)
    creds = SqlInstitutionCredentialRepo(session, cipher)
    status = seed_credential(
        SqlHouseholdRepo(session),
        creds,
        household_id=hid,
        institution="cimb",
        scheme=PasswordScheme.STATIC,
        secret="070587",
        replace=False,
    )
    assert status is SeedStatus.CREATED
    stored = creds.by_household_institution(hid, "cimb")
    assert stored is not None
    assert stored.secret == "070587"
    assert stored.password_scheme is PasswordScheme.STATIC


def test_seed_no_household_makes_no_change(session: Session, cipher: FieldCipher) -> None:
    creds = SqlInstitutionCredentialRepo(session, cipher)
    status = seed_credential(
        SqlHouseholdRepo(session),
        creds,
        household_id=9999,
        institution="cimb",
        scheme=PasswordScheme.STATIC,
        secret="irrelevant",
        replace=False,
    )
    assert status is SeedStatus.NO_HOUSEHOLD
    assert creds.by_household_institution(9999, "cimb") is None


def test_seed_exists_without_replace_is_unchanged(session: Session, cipher: FieldCipher) -> None:
    hid = _household(session)
    creds = SqlInstitutionCredentialRepo(session, cipher)
    households = SqlHouseholdRepo(session)
    seed_credential(
        households,
        creds,
        household_id=hid,
        institution="cimb",
        scheme=PasswordScheme.STATIC,
        secret="first",
        replace=False,
    )
    status = seed_credential(
        households,
        creds,
        household_id=hid,
        institution="cimb",
        scheme=PasswordScheme.STATIC,
        secret="second",
        replace=False,
    )
    assert status is SeedStatus.EXISTS
    stored = creds.by_household_institution(hid, "cimb")
    assert stored is not None and stored.secret == "first"  # not overwritten


def test_seed_replace_overwrites_without_duplicating(session: Session, cipher: FieldCipher) -> None:
    hid = _household(session)
    creds = SqlInstitutionCredentialRepo(session, cipher)
    households = SqlHouseholdRepo(session)
    seed_credential(
        households,
        creds,
        household_id=hid,
        institution="cimb",
        scheme=PasswordScheme.STATIC,
        secret="first",
        replace=False,
    )
    first = creds.by_household_institution(hid, "cimb")
    assert first is not None and first.id is not None

    status = seed_credential(
        households,
        creds,
        household_id=hid,
        institution="cimb",
        scheme=PasswordScheme.STATIC,
        secret="second",
        replace=True,
    )
    assert status is SeedStatus.REPLACED
    current = creds.by_household_institution(hid, "cimb")
    assert current is not None and current.secret == "second"
    # delete-then-add: the old row is gone (no duplicate left behind).
    assert creds.get(first.id) is None
    assert current.id != first.id


def test_seed_per_statement_stores_no_secret(session: Session, cipher: FieldCipher) -> None:
    hid = _household(session)
    creds = SqlInstitutionCredentialRepo(session, cipher)
    status = seed_credential(
        SqlHouseholdRepo(session),
        creds,
        household_id=hid,
        institution="ajaib",
        scheme=PasswordScheme.PER_STATEMENT,
        secret=None,
        replace=False,
    )
    assert status is SeedStatus.CREATED
    stored = creds.by_household_institution(hid, "ajaib")
    assert stored is not None and stored.secret is None


def test_resolve_secret_static_requires_nonempty() -> None:
    assert resolve_secret(PasswordScheme.STATIC, "070587") == "070587"
    with pytest.raises(ValueError, match="requires a statement password"):
        resolve_secret(PasswordScheme.STATIC, None)
    with pytest.raises(ValueError, match="requires a statement password"):
        resolve_secret(PasswordScheme.STATIC, "")


def test_resolve_secret_per_statement_forbids_secret() -> None:
    assert resolve_secret(PasswordScheme.PER_STATEMENT, None) is None
    with pytest.raises(ValueError, match="stores no secret"):
        resolve_secret(PasswordScheme.PER_STATEMENT, "x")


def test_main_per_statement_with_secret_errors_before_db(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A secret supplied for per_statement is a bad invocation; it must fail (exit 2)
    # before any DB/env access — and must NOT echo the secret.
    monkeypatch.setenv(SEED_SECRET_ENV, "should-not-appear")
    rc = main(["--household-id", "1", "--institution", "ajaib", "--scheme", "per_statement"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "per_statement" in err
    assert "should-not-appear" not in err


def test_main_static_empty_secret_errors_before_db(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(SEED_SECRET_ENV, "")  # set-but-empty → treated as missing
    rc = main(["--household-id", "1", "--scheme", "static"])
    assert rc == 2
    assert "requires a statement password" in capsys.readouterr().err
