"""Field-level encryption at rest (SPEC §6 "At-rest encryption").

The statement password stored in ``institution_credential.password_enc`` is real
financial-account access material — it must not sit on disk in plaintext. This
wraps ``cryptography``'s Fernet (AES-128-CBC + HMAC authentication) so the
persistence mappers can encrypt on write and decrypt on read.

The key is supplied by configuration (env), **never** hardcoded and never logged.
Encryption is an infrastructure concern: it lives here in persistence, so the
domain entity carries the plaintext ``secret`` and knows nothing about ciphertext.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


class FieldCipher:
    """Symmetric authenticated encryption for a single sensitive text column."""

    def __init__(self, key: bytes) -> None:
        # Fernet validates the key (urlsafe-base64, 32 bytes) and raises on a bad one.
        self._fernet = Fernet(key)

    @staticmethod
    def generate_key() -> bytes:
        """A fresh key for provisioning / tests. Store it in config, out of the repo."""
        return Fernet.generate_key()

    def encrypt(self, plaintext: str) -> str:
        """Plaintext → an opaque token safe to persist (urlsafe-base64 text)."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        """A stored token → the original plaintext. Raises on tampering / wrong key."""
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
