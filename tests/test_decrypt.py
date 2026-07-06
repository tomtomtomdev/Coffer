"""Tests for the ingestion decryption stage (SPEC §4, security invariants).

Uses PDFs generated + encrypted in-memory with pikepdf (no real statement, no PDF
on disk). Verifies: encryption detection, in-memory decrypt round-trip, a wrong
password fails WITHOUT leaking the password, and the plaintext-stream entry point.
"""

from __future__ import annotations

import io

import pikepdf
import pytest

from coffer.ingestion.decrypt import (
    PasswordScheme,
    StatementDecryptionError,
    decrypt_to_stream,
    is_encrypted,
    to_plaintext_stream,
)

_USER_PW = "s3cret-user-pw"


def _plain_pdf() -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _encrypted_pdf(password: str) -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    buf = io.BytesIO()
    pdf.save(buf, encryption=pikepdf.Encryption(user=password, owner=password, aes=True))
    return buf.getvalue()


def test_is_encrypted_detects_both() -> None:
    assert is_encrypted(_encrypted_pdf(_USER_PW)) is True
    assert is_encrypted(_plain_pdf()) is False


def test_decrypt_round_trips_to_plaintext_in_memory() -> None:
    out = decrypt_to_stream(_encrypted_pdf(_USER_PW), _USER_PW)
    assert isinstance(out, io.BytesIO)
    # the returned stream is now openable without a password
    assert is_encrypted(out.getvalue()) is False
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1


def test_wrong_password_raises_without_leaking_the_password() -> None:
    enc = _encrypted_pdf(_USER_PW)
    with pytest.raises(StatementDecryptionError) as ei:
        decrypt_to_stream(enc, "the-wrong-password")
    msg = str(ei.value)
    assert "the-wrong-password" not in msg  # never echo the attempted secret
    assert _USER_PW not in msg


def test_to_plaintext_stream_passes_through_unencrypted() -> None:
    plain = _plain_pdf()
    out = to_plaintext_stream(plain)  # no password needed
    assert is_encrypted(out.getvalue()) is False


def test_to_plaintext_stream_needs_password_when_encrypted() -> None:
    enc = _encrypted_pdf(_USER_PW)
    with pytest.raises(StatementDecryptionError):
        to_plaintext_stream(enc, password=None)  # encrypted but no password → surface it
    # with the password it succeeds
    out = to_plaintext_stream(enc, password=_USER_PW)
    assert is_encrypted(out.getvalue()) is False


def test_password_scheme_values() -> None:
    assert PasswordScheme.STATIC.value == "static"
    assert PasswordScheme.DERIVED.value == "derived"
    assert PasswordScheme.PER_STATEMENT.value == "per_statement"
