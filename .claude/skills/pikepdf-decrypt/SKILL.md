---
name: pikepdf-decrypt
description: Decrypt password-protected PDF statements in memory with pikepdf for the Coffer ingestion layer. Use when implementing or reviewing the S2 decryption stage, resolving statement passwords by scheme (static/derived/per_statement), detecting encryption, re-encrypting an unencrypted arrival at rest, or any code that opens a bank/broker PDF. Encodes Coffer's hard security invariants: plaintext PDFs never touch disk, passwords are never logged.
---

# pikepdf — in-memory statement decryption (Coffer S2)

Decryption is the **ingestion layer's** job, not the parser's. A parser receives an
already-decrypted `BytesIO`/text and never touches encryption or disk.

## Non-negotiable invariants (CLAUDE.md security)
- **Plaintext PDFs never touch disk.** Decrypt into a `BytesIO`, hand that to the parser,
  let it be garbage-collected. Persist only the **encrypted original** + parsed data + hashes.
- **Never log the password** or raw statement bytes — not in exceptions, not in debug lines.
- If a statement arrives **unencrypted**, encrypt it at rest before storing.

## Decrypt to an in-memory stream

```python
import io
import pikepdf

def decrypt_to_stream(encrypted: bytes | str, password: str) -> io.BytesIO:
    """Open an encrypted PDF and return a decrypted, in-memory copy.

    Raises pikepdf.PasswordError on a wrong/missing password (do NOT log `password`).
    The returned buffer is unencrypted and lives only in memory.
    """
    with pikepdf.open(encrypted, password=password) as pdf:  # PasswordError if wrong
        buf = io.BytesIO()
        pdf.save(buf)          # saved without an Encryption= arg → plaintext, in memory only
    buf.seek(0)
    return buf
```

Then: `parsed = cimb_kartu_kredit.parse(decrypt_to_stream(enc_bytes, pw))`.

## Detect whether a source needs a password

```python
def needs_password(source: bytes | str) -> bool:
    try:
        with pikepdf.open(source):        # no password
            return False
    except pikepdf.PasswordError:
        return True
```

`pikepdf.Pdf.is_encrypted` tells you a file *is* encrypted, but a file can be encrypted
with an empty user password (opens fine). The try/except above is the reliable "does the
user need to supply a secret" check. On `PasswordError`, surface **"🔒 needs password"**
upstream — never the password, never a stack trace containing bytes.

## Password schemes (`institution_credential.password_scheme`, SPEC §4/§8)
- `static` — one stored password per institution. **Build this path first.**
- `derived` — computed from stored inputs (e.g. a rule over DOB/card digits). Keep the
  derivation pure and unit-tested; store the *inputs*, not the derived secret.
- `per_statement` — prompt each time; never persist.

Resolve the password by scheme, then call `decrypt_to_stream`. Wrong password →
`PasswordError` → mark the statement "needs password" and stop; do not retry-log.

## Encrypt an unencrypted arrival at rest

```python
def encrypt_for_storage(plaintext: bytes, user_pw: str, owner_pw: str) -> bytes:
    with pikepdf.open(io.BytesIO(plaintext)) as pdf:
        buf = io.BytesIO()
        pdf.save(buf, encryption=pikepdf.Encryption(user=user_pw, owner=owner_pw, aes=True))
    return buf.getvalue()
```

## Testing (TDD, no real PDF committed)
- Generate a fixture PDF locally in the test, encrypt it with a known password, assert
  `decrypt_to_stream(...)` round-trips and the parser output reconciles.
- Assert a **wrong password raises `pikepdf.PasswordError`** and that the password string
  does not appear in the raised message.
- Never commit a real encrypted statement. See [[pdfplumber-extract]] for the parse side and
  [[clean-architecture]] for keeping decrypt in ingestion, behind a domain-owned interface.
```
