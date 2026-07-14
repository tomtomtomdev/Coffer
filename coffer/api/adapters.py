"""Concrete infrastructure adapters for the ingestion use-case ports.

These implement the ``coffer.ingestion.pipeline`` Protocols (``PdfReader``,
``StatementArchive``) with the real pikepdf/pdfplumber decrypt+extract path and
filesystem + Fernet at-rest retention. They live in the api (outermost) layer; the
use-case depends only on the Protocols, so the dependency points inward.

Security invariants (CLAUDE.md / SPEC §4, §6):
  * Plaintext PDFs never touch disk — decrypt in memory, extract, discard.
  * Only the *encrypted* original is persisted; an unencrypted arrival is Fernet-
    encrypted at rest before it is written.
  * The password is never logged.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import IO

import pdfplumber

from coffer.ingestion.decrypt import is_encrypted, to_plaintext_stream
from coffer.ingestion.pipeline import DecryptedPdf
from coffer.persistence.crypto import FieldCipher


def _extract_text(stream: IO[bytes]) -> str:
    """The text layer of an already-decrypted PDF (statements are text-based).

    Mirrors the parsers' own pdfplumber entry points; the pipeline runs the shared
    near-empty ``check_extraction`` gate on the result before handing it to a parser."""
    with pdfplumber.open(stream) as pdf:  # type: ignore[arg-type]
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


class PdfPlumberReader:
    """``PdfReader``: decrypt in memory (pikepdf), then extract text (pdfplumber)."""

    def read(self, raw_bytes: bytes, password: str | None) -> DecryptedPdf:
        was_encrypted = is_encrypted(raw_bytes)
        stream = to_plaintext_stream(raw_bytes, password)  # raises StatementDecryptionError
        return DecryptedPdf(text=_extract_text(stream), was_encrypted=was_encrypted)


class FilesystemStatementArchive:
    """``StatementArchive``: keep only the encrypted original under ``base_dir``.

    A password-protected PDF is already unreadable without its password, so it is
    stored as-is. An unencrypted arrival is Fernet-encrypted at rest first — nothing
    plaintext-financial ever lands on disk (SPEC §4 retention)."""

    def __init__(self, base_dir: Path, cipher: FieldCipher) -> None:
        self._dir = base_dir
        self._cipher = cipher

    def store(self, *, raw_bytes: bytes, was_encrypted: bool) -> str:
        self._dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        if was_encrypted:
            payload, suffix = raw_bytes, ".pdf"
        else:
            payload, suffix = self._cipher.encrypt_bytes(raw_bytes), ".pdf.enc"
        path = self._dir / f"{digest}{suffix}"
        path.write_bytes(payload)
        return str(path)

    def load(self, path: str, *, was_encrypted: bool) -> io.BytesIO:
        """Re-read a stored original for reparse (§4 step 5). An at-rest-encrypted
        arrival is decrypted back to its original bytes; a password-protected PDF is
        returned as stored (the decrypt stage re-applies the password)."""
        raw = Path(path).read_bytes()
        if not was_encrypted:
            raw = self._cipher.decrypt_bytes(raw)
        return io.BytesIO(raw)
