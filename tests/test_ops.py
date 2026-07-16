"""S15 — backup/ops safety core (`coffer/api/ops.py`).

Two pure, testable pieces the restic wrapper (`scripts/backup.sh`) leans on:

  * ``audit_archive`` — the encrypted-only guard. The backup must NEVER capture a
    plaintext statement PDF (SPEC §7 retention + CLAUDE.md security invariants). The
    statement archive is expected to hold only password-protected ``.pdf`` originals
    and Fernet-at-rest ``.pdf.enc`` files; anything else aborts the backup.
  * ``spot_check_due`` — the monthly manual bank-reconciliation reminder cadence
    (SPEC §7 "present a spot-check reminder rather than stale numbers as truth").

PDFs are generated + encrypted in memory with pikepdf (no real statement, mirroring
``test_decrypt.py``); nothing financial touches disk.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pikepdf

from coffer.api.ops import audit_archive, main, spot_check_due


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


# ── audit_archive ────────────────────────────────────────────────────────────


def test_audit_missing_dir_is_ok(tmp_path: Path) -> None:
    audit = audit_archive(tmp_path / "not-created-yet")
    assert audit.ok
    assert audit.plaintext_pdfs == []
    assert audit.unexpected == []


def test_audit_empty_dir_is_ok(tmp_path: Path) -> None:
    assert audit_archive(tmp_path).ok


def test_audit_accepts_encrypted_and_at_rest(tmp_path: Path) -> None:
    (tmp_path / "aaa.pdf").write_bytes(_encrypted_pdf("pw"))  # password-protected arrival
    (tmp_path / "bbb.pdf.enc").write_bytes(b"gAAAAABm-fernet-ciphertext")  # at-rest encrypted
    audit = audit_archive(tmp_path)
    assert audit.ok
    assert len(audit.encrypted_pdfs) == 1
    assert len(audit.at_rest_encrypted) == 1


def test_audit_flags_a_plaintext_pdf(tmp_path: Path) -> None:
    (tmp_path / "leak.pdf").write_bytes(_plain_pdf())
    audit = audit_archive(tmp_path)
    assert not audit.ok
    assert [p.name for p in audit.plaintext_pdfs] == ["leak.pdf"]


def test_audit_flags_an_unexpected_file(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello")
    audit = audit_archive(tmp_path)
    assert not audit.ok
    assert [p.name for p in audit.unexpected] == ["notes.txt"]


def test_audit_flags_a_subdirectory_as_unexpected(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    audit = audit_archive(tmp_path)
    assert not audit.ok
    assert [p.name for p in audit.unexpected] == ["nested"]


# ── spot_check_due ─────────────────────────────────────────────────────────---

_NOW = datetime(2026, 7, 16, tzinfo=UTC)


def test_spot_check_due_when_never_checked() -> None:
    assert spot_check_due(None, _NOW)


def test_spot_check_not_due_within_interval() -> None:
    assert not spot_check_due(_NOW - timedelta(days=10), _NOW)


def test_spot_check_due_past_interval() -> None:
    assert spot_check_due(_NOW - timedelta(days=31), _NOW)


def test_spot_check_due_exactly_at_interval_boundary() -> None:
    assert spot_check_due(_NOW - timedelta(days=30), _NOW)


# ── CLI (the shell wrapper's entry point) ─────────────────────────────────────


def test_cli_audit_exit_zero_on_clean_archive(tmp_path: Path) -> None:
    (tmp_path / "x.pdf.enc").write_bytes(b"ciphertext")
    assert main(["audit", str(tmp_path)]) == 0


def test_cli_audit_exit_one_on_plaintext(tmp_path: Path) -> None:
    (tmp_path / "leak.pdf").write_bytes(_plain_pdf())
    assert main(["audit", str(tmp_path)]) == 1


def test_cli_spot_check_due_exit_codes(tmp_path: Path) -> None:
    marker = tmp_path / "spot_check.last"
    # no marker → due (exit 0)
    assert main(["spot-check-due", str(marker)]) == 0
    # a fresh timestamp → not due (exit 1)
    marker.write_text(datetime.now(UTC).isoformat())
    assert main(["spot-check-due", str(marker)]) == 1


def test_cli_unknown_command_is_usage_error() -> None:
    assert main(["frobnicate"]) == 2
