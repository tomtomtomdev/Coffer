"""The (institution, account_type) → parser registry for the ingestion pipeline.

Maps an account's ``account_type`` to the matching parser's pure ``parse_text`` entry
point. The pipeline extracts the PDF text once (via the ``PdfReader``) and dispatches
here, so the parsers stay pure functions on text (Clean Architecture: parsers know
nothing about decryption or disk).

Note: BCA Tahapan and Tapres are both ``bca_savings`` and share one engine
(``_bca_rekening_koran``); the engine auto-detects the header variant, so either
adapter's ``parse_text`` serves the type. The Tahapan/Tapres ``parser_version``
distinction (only relevant to targeted reparse) is a follow-up.
"""

from __future__ import annotations

from coffer.domain.enums import AccountType
from coffer.ingestion.pipeline import ParserRegistry
from coffer.parsers import (
    ajaib_portfolio,
    bca_kartu_kredit,
    bca_tahapan,
    cimb_kartu_kredit,
    stockbit_soa,
)

PARSERS: ParserRegistry = {
    AccountType.BCA_SAVINGS: bca_tahapan.parse_text,
    AccountType.BCA_CREDIT_CARD: bca_kartu_kredit.parse_text,
    AccountType.CIMB_CREDIT_CARD: cimb_kartu_kredit.parse_text,
    AccountType.AJAIB_PORTFOLIO: ajaib_portfolio.parse_text,
    AccountType.STOCKBIT_PORTFOLIO: stockbit_soa.parse_text,
}
