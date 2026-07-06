"""BCA Tahapan (savings) statement parser.

BCA Tahapan and Tapres share one statement format; the parsing engine lives in
`_bca_rekening_koran`. This module is the Tahapan adapter — it only pins the
`parser_version`. Built against a real "REKENING TAHAPAN" e-statement (PERIODE
JUNI 2026, 6 pages). See the engine module for layout facts and the reconciliation
gate (SALDO AWAL + Σ credits − Σ debits == SALDO AKHIR).
"""

from __future__ import annotations

from typing import IO

from . import _bca_rekening_koran as _rk
from .statement_types import ParsedStatement

PARSER_VERSION = "bca_tahapan/1.0.0"


def parse_text(text: str) -> ParsedStatement:
    """Pure function on already-extracted statement text."""
    return _rk.parse_rekening_koran(text, parser_version=PARSER_VERSION)


def parse(pdf_source: str | bytes | bytearray | IO[bytes]) -> ParsedStatement:
    """Production entry point over an already-decrypted PDF source."""
    return _rk.parse_pdf(pdf_source, parser_version=PARSER_VERSION)
