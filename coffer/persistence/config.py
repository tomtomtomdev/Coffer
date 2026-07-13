"""Persistence configuration — read from the environment, never hardcoded.

No database URL and no encryption key ever live in the repository (SPEC §6). Both
are resolved from environment variables at runtime:

  * ``COFFER_DATABASE_URL``  — e.g. ``postgresql+psycopg://user:pw@host/coffer``
  * ``COFFER_ENCRYPTION_KEY`` — a Fernet key (urlsafe-base64, 32 bytes) for at-rest
                                field encryption (see ``crypto.FieldCipher``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DATABASE_URL_ENV = "COFFER_DATABASE_URL"
ENCRYPTION_KEY_ENV = "COFFER_ENCRYPTION_KEY"


@dataclass(frozen=True)
class Settings:
    database_url: str
    encryption_key: bytes

    @classmethod
    def from_env(cls) -> Settings:
        try:
            database_url = os.environ[DATABASE_URL_ENV]
            encryption_key = os.environ[ENCRYPTION_KEY_ENV]
        except KeyError as exc:  # missing config is a deploy error, surfaced loudly
            raise RuntimeError(f"missing required environment variable: {exc.args[0]}") from None
        return cls(database_url=database_url, encryption_key=encryption_key.encode("ascii"))
