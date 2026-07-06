"""In-memory PDF decryption stage (SPEC §4).

Decryption is the ingestion layer's job — parsers receive already-decrypted input.

Security invariants (CLAUDE.md):
  * Plaintext PDFs never touch disk. We decrypt into a ``BytesIO`` and hand that to
    the parser; nothing is written out.
  * The password is never logged or echoed — not in exceptions, not anywhere.

This module is deliberately **password-source-agnostic**: every entry point takes
the password as a runtime argument. WHERE that password comes from — an interactive
no-echo prompt (``getpass``), a value held in memory for the service session, or an
encrypted-at-rest credential — is a separate credential-resolution concern (S4/S9),
not decided here. So a "static" scheme (same password every month) does not force
storing it; it can equally be entered at runtime.
"""

from __future__ import annotations

import io
from enum import StrEnum
from typing import IO

import pikepdf


class PasswordScheme(StrEnum):
    """How an institution's statement password is obtained (SPEC §2/§4)."""

    STATIC = "static"  # same password every statement
    DERIVED = "derived"  # computed from stored inputs (e.g. DOB + card digits)
    PER_STATEMENT = "per_statement"  # a new password each time; prompt, never persist


class StatementDecryptionError(Exception):
    """Raised when a statement PDF cannot be decrypted (wrong or missing password).

    The password is never included in the message (security invariant).
    """


def _to_bytes(source: bytes | bytearray | IO[bytes]) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    data = source.read()
    try:
        source.seek(0)  # leave a file-like caller's stream re-readable
    except (OSError, ValueError):  # pragma: no cover - non-seekable stream
        pass
    return data


def is_encrypted(source: bytes | bytearray | IO[bytes]) -> bool:
    """True if the PDF requires a password to open."""
    data = _to_bytes(source)
    try:
        with pikepdf.open(io.BytesIO(data)):
            return False
    except pikepdf.PasswordError:
        return True


def decrypt_to_stream(source: bytes | bytearray | IO[bytes], password: str) -> io.BytesIO:
    """Decrypt an encrypted PDF and return an in-memory, unencrypted copy.

    Raises ``StatementDecryptionError`` on a wrong/missing password. The attempted
    password is NOT included in the raised message.
    """
    data = _to_bytes(source)
    try:
        with pikepdf.open(io.BytesIO(data), password=password) as pdf:
            out = io.BytesIO()
            pdf.save(out)  # saved without encryption= → plaintext, in memory only
    except pikepdf.PasswordError:
        raise StatementDecryptionError(
            "could not decrypt statement — wrong or missing password"
        ) from None
    out.seek(0)
    return out


def to_plaintext_stream(
    source: bytes | bytearray | IO[bytes], password: str | None = None
) -> io.BytesIO:
    """Ingestion entry point: return a plaintext stream ready for a parser.

    Unencrypted input passes through untouched. Encrypted input requires ``password``
    (supplied at runtime by the caller); if it is missing we surface a "needs password"
    error rather than guessing.
    """
    data = _to_bytes(source)
    if not is_encrypted(data):
        return io.BytesIO(data)
    if password is None:
        raise StatementDecryptionError("statement is encrypted — a password is required")
    return decrypt_to_stream(data, password)
