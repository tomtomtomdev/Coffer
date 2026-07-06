"""BCA Tapres (savings) statement parser.

BCA Tapres shares the Tahapan statement format; the parsing engine lives in
`_bca_rekening_koran`. This module is the Tapres adapter — it only pins the
`parser_version`. Built against a real "REKENING TAPRES" e-statement (a brokerage
RDN held as a Tapres account; PERIODE 01-05-2026 S/D 31-05-2026, 3 pages). The
header differs from Tahapan (title, ``NOMOR REKENING`` label, date-range PERIODE);
the engine handles both. Same reconciliation gate and ``bca_savings`` account type.

Note: this account doubles as an Ajaib brokerage RDN, so its balance overlaps the
broker statement's reported cash — net-worth recompute (S7) must net that, not sum it.
"""

from __future__ import annotations

from typing import IO

from . import _bca_rekening_koran as _rk
from .statement_types import ParsedStatement

PARSER_VERSION = "bca_tapres/1.0.0"


def parse_text(text: str) -> ParsedStatement:
    """Pure function on already-extracted statement text."""
    return _rk.parse_rekening_koran(text, parser_version=PARSER_VERSION)


def parse(pdf_source: str | bytes | bytearray | IO[bytes]) -> ParsedStatement:
    """Production entry point over an already-decrypted PDF source."""
    return _rk.parse_pdf(pdf_source, parser_version=PARSER_VERSION)
