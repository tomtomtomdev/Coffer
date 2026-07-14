"""S9 — the filesystem statement archive (SPEC §4 retention / §6 at-rest encryption).

Guards the hard invariant: an unencrypted arrival is Fernet-encrypted before it is
written, so no plaintext-financial bytes ever land on disk; a password-protected PDF is
kept as-is (already unreadable without its password). Reparse can recover the original.
"""

from __future__ import annotations

from pathlib import Path

from coffer.api.adapters import FilesystemStatementArchive
from coffer.persistence.crypto import FieldCipher

PLAINTEXT = b"%PDF-1.7 unencrypted statement with SALDO AKHIR 12345"


def _archive(tmp_path: Path) -> FilesystemStatementArchive:
    return FilesystemStatementArchive(tmp_path, FieldCipher(FieldCipher.generate_key()))


def test_unencrypted_arrival_is_encrypted_at_rest(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    path = archive.store(raw_bytes=PLAINTEXT, was_encrypted=False)

    on_disk = Path(path).read_bytes()
    assert on_disk != PLAINTEXT  # NOT stored in the clear
    assert b"SALDO AKHIR" not in on_disk  # ciphertext, not the statement content
    assert path.endswith(".pdf.enc")

    # reparse can recover the exact original bytes.
    assert archive.load(path, was_encrypted=False).read() == PLAINTEXT


def test_encrypted_arrival_is_stored_as_is(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    encrypted_pdf = b"%PDF-1.7 already-password-protected-bytes"
    path = archive.store(raw_bytes=encrypted_pdf, was_encrypted=True)

    assert Path(path).read_bytes() == encrypted_pdf  # kept verbatim
    assert path.endswith(".pdf")
    assert archive.load(path, was_encrypted=True).read() == encrypted_pdf
