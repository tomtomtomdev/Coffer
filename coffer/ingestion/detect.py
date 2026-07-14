"""Account-type sniffer — routes an uploaded statement to its account/parser (SPEC §4).

The Telegram bot has no manually-selected ``account_id`` (unlike web upload); it must
infer the account type from the decrypted statement's header text, then resolve that to
one of the household's accounts. This module is the first half — a **pure** text →
``AccountType | None`` classifier keyed on distinctive header markers.

Grounded in the anonymized fixture headers (CLAUDE.md — don't invent a format):

  * ``REKENING TAHAPAN`` / ``REKENING TAPRES``  → ``bca_savings``  (shared engine)
  * ``REKENING KARTU KREDIT``                   → ``bca_credit_card``
  * ``CIMB``/``NIAGA`` letterhead, or the ``Tgl. Statement`` + ``Tgl. Jatuh Tempo``
    layout                                       → ``cimb_credit_card``
  * ``AJAIB`` branding                           → ``ajaib_portfolio``
  * ``STOCKBIT`` branding                        → ``stockbit_portfolio``

Matching is on the **specific** BCA header phrase ``REKENING KARTU KREDIT`` — the CIMB
statement mentions ``kartu kredit`` generically ("Limit kartu kredit Anda...") and must
not be mistaken for a BCA card. Returns ``None`` when nothing matches (the caller then
falls back to an inline-keyboard account picker rather than guessing).
"""

from __future__ import annotations

from collections.abc import Callable

from coffer.domain.enums import AccountType

__all__ = ["detect_account_type"]


def _has_all(*needles: str) -> Callable[[str], bool]:
    return lambda text: all(n in text for n in needles)


def _has_any(*needles: str) -> Callable[[str], bool]:
    return lambda text: any(n in text for n in needles)


# Ordered rules; first match wins. Markers are matched against lower-cased text.
# The authoritative bank-account HEADERS come first: a BCA RDN/Tapres statement is a
# brokerage account and mentions the broker ("AJAIB"/"STOCKBIT") in its transaction
# lines, so the definitive "REKENING TAPRES" header must win over the brand name.
_RULES: tuple[tuple[Callable[[str], bool], AccountType], ...] = (
    (_has_any("rekening tahapan", "rekening tapres"), AccountType.BCA_SAVINGS),
    (_has_any("rekening kartu kredit"), AccountType.BCA_CREDIT_CARD),
    (_has_any("cimb", "niaga"), AccountType.CIMB_CREDIT_CARD),
    (_has_all("tgl. statement", "tgl. jatuh tempo"), AccountType.CIMB_CREDIT_CARD),
    (_has_any("ajaib"), AccountType.AJAIB_PORTFOLIO),
    (_has_any("stockbit"), AccountType.STOCKBIT_PORTFOLIO),
)


def detect_account_type(text: str) -> AccountType | None:
    """Infer the ``AccountType`` from a decrypted statement's text, or ``None``."""
    haystack = text.lower()
    for matches, account_type in _RULES:
        if matches(haystack):
            return account_type
    return None
