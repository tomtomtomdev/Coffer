"""Backup / operations safety core (S15, SPEC §7).

The actual backup is the existing TrueNAS SCALE + restic pipeline, driven by
``scripts/backup.sh``. This module is the small, *testable* logic that wrapper leans on
so the security invariants are enforced in Python (covered by the gate), not buried in
shell:

  * :func:`audit_archive` — the **encrypted-only guard**. The retained statement archive
    must contain only password-protected ``.pdf`` originals and Fernet-at-rest
    ``.pdf.enc`` files (see ``api/adapters.FilesystemStatementArchive``). A plaintext PDF
    or any unexpected file means something has bypassed the retention rule (CLAUDE.md:
    "plaintext PDFs never touch disk"; SPEC §7: "backup never contains plaintext PDFs").
    The wrapper runs this as a preflight and aborts before restic sees a single byte.
  * :func:`spot_check_due` — the monthly manual bank-reconciliation reminder cadence
    (SPEC §7: statements lag reality, so prompt a spot check rather than presenting stale
    numbers as current truth).

Both are pure (``spot_check_due`` fully; ``audit_archive`` only reads the archive). The
``main`` CLI is the thin seam ``scripts/backup.sh`` calls
(``python -m coffer.api.ops {audit DIR | spot-check-due MARKER}``).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from coffer.ingestion.decrypt import is_encrypted  # api → ingestion (dependency points inward)

DEFAULT_SPOT_CHECK_INTERVAL = timedelta(days=30)


@dataclass(frozen=True)
class ArchiveAudit:
    """Result of scanning the statement archive for anything not encrypted at rest."""

    encrypted_pdfs: list[Path]  # password-protected originals stored as-is (safe)
    at_rest_encrypted: list[Path]  # Fernet ``.pdf.enc`` (unencrypted arrivals, encrypted) (safe)
    plaintext_pdfs: list[Path]  # a readable PDF leaked onto disk — a retention violation
    unexpected: list[Path]  # anything else (stray files, subdirs) — investigate before backup

    @property
    def ok(self) -> bool:
        """True only when nothing plaintext or unexpected is present — safe to back up."""
        return not self.plaintext_pdfs and not self.unexpected


def audit_archive(archive_dir: Path) -> ArchiveAudit:
    """Classify every entry in the statement archive by its at-rest encryption.

    A missing or empty directory is OK (no statements retained yet). The archive is flat
    (``{sha256}.pdf`` / ``{sha256}.pdf.enc``); any subdirectory is treated as unexpected.
    """
    encrypted: list[Path] = []
    at_rest: list[Path] = []
    plaintext: list[Path] = []
    unexpected: list[Path] = []

    if archive_dir.is_dir():
        for entry in sorted(archive_dir.iterdir()):
            if not entry.is_file():
                unexpected.append(entry)
            elif entry.name.endswith(".pdf.enc"):
                at_rest.append(entry)
            elif entry.name.endswith(".pdf"):
                # A bare .pdf is only legitimate if it is password-protected (an
                # encrypted arrival stored as-is). A readable one is a leak.
                (encrypted if is_encrypted(entry.read_bytes()) else plaintext).append(entry)
            else:
                unexpected.append(entry)

    return ArchiveAudit(
        encrypted_pdfs=encrypted,
        at_rest_encrypted=at_rest,
        plaintext_pdfs=plaintext,
        unexpected=unexpected,
    )


def spot_check_due(
    last_checked: datetime | None,
    now: datetime,
    *,
    interval: timedelta = DEFAULT_SPOT_CHECK_INTERVAL,
) -> bool:
    """Whether a manual bank-reconciliation spot check is due (SPEC §7).

    Due when never checked, or when at least ``interval`` has elapsed since the last one.
    """
    return last_checked is None or (now - last_checked) >= interval


def _read_marker(path: Path) -> datetime | None:
    """Parse the ISO-8601 timestamp of the last spot check; None if absent/blank/garbage."""
    if not path.is_file():
        return None
    text = path.read_text().strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    """CLI seam for ``scripts/backup.sh``. Returns a process exit code.

    ``audit DIR``            → 0 if the archive is encrypted-only, else 1 (abort backup).
    ``spot-check-due MARKER`` → 0 if a spot check is due, else 1.
    """
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(
            "usage: python -m coffer.api.ops {audit DIR | spot-check-due MARKER}",
            file=sys.stderr,
        )
        return 2
    command, *rest = args

    if command == "audit":
        if not rest:
            print("usage: python -m coffer.api.ops audit DIR", file=sys.stderr)
            return 2
        audit = audit_archive(Path(rest[0]))
        for path in audit.plaintext_pdfs:
            print(f"PLAINTEXT PDF IN ARCHIVE (retention violation): {path}", file=sys.stderr)
        for path in audit.unexpected:
            print(f"UNEXPECTED FILE IN ARCHIVE: {path}", file=sys.stderr)
        print(
            f"archive audit: {len(audit.encrypted_pdfs)} encrypted, "
            f"{len(audit.at_rest_encrypted)} at-rest-encrypted, "
            f"{len(audit.plaintext_pdfs)} plaintext, {len(audit.unexpected)} unexpected"
        )
        return 0 if audit.ok else 1

    if command == "spot-check-due":
        if not rest:
            print("usage: python -m coffer.api.ops spot-check-due MARKER", file=sys.stderr)
            return 2
        due = spot_check_due(_read_marker(Path(rest[0])), datetime.now(UTC))
        print("due" if due else "ok")
        return 0 if due else 1

    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised via scripts/backup.sh
    raise SystemExit(main())
