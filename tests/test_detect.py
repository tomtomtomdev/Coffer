"""S10 — account-type sniffer (``coffer.ingestion.detect``).

The Telegram bot auto-detects the account type from the decrypted statement's header
text (SPEC §4) so it can route to the right parser / resolve the target account. This
is a pure text classifier; it is grounded in the anonymized fixture headers (never
invents a format — CLAUDE.md parser rules).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from coffer.domain.enums import AccountType
from coffer.ingestion.detect import detect_account_type

_FIXTURES = Path(__file__).parent / "fixtures"


def _text(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("bca_tahapan_2026-06.txt", AccountType.BCA_SAVINGS),
        ("bca_tapres_2026-05.txt", AccountType.BCA_SAVINGS),
        ("bca_tapres_empty_2026-06.txt", AccountType.BCA_SAVINGS),
        ("bca_kartu_kredit_2026-06.txt", AccountType.BCA_CREDIT_CARD),
        ("cimb_mc_gold_2026-03.txt", AccountType.CIMB_CREDIT_CARD),
        ("ajaib_portfolio_2026-06-30.txt", AccountType.AJAIB_PORTFOLIO),
        ("stockbit_soa_2026-06.txt", AccountType.STOCKBIT_PORTFOLIO),
    ],
)
def test_detects_every_real_fixture(fixture: str, expected: AccountType) -> None:
    assert detect_account_type(_text(fixture)) is expected


def test_unknown_text_returns_none() -> None:
    assert detect_account_type("a grocery receipt, not a statement") is None
    assert detect_account_type("") is None


def test_detection_is_case_insensitive() -> None:
    assert detect_account_type("...rekening tahapan...") is AccountType.BCA_SAVINGS
    assert detect_account_type("...REKENING TAHAPAN...") is AccountType.BCA_SAVINGS


def test_cimb_generic_kartu_kredit_is_not_a_bca_card() -> None:
    # The CIMB statement mentions "kartu kredit" generically ("Limit kartu kredit
    # Anda...") but is NOT a BCA card — only the full "REKENING KARTU KREDIT" header
    # marks a BCA card. Detection must key on the specific header, not the substring.
    cimb = _text("cimb_mc_gold_2026-03.txt")
    assert "kartu kredit" in cimb.lower()
    assert detect_account_type(cimb) is AccountType.CIMB_CREDIT_CARD


def test_explicit_cimb_letterhead_detected() -> None:
    # Real (non-anonymized) CIMB statements carry the "CIMB Niaga" letterhead; the
    # anonymized fixture relies on the structural markers instead. Both must work.
    assert (
        detect_account_type("PT BANK CIMB NIAGA TBK\nLembar Tagihan")
        is AccountType.CIMB_CREDIT_CARD
    )
