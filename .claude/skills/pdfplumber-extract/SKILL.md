---
name: pdfplumber-extract
description: Extract text and tables from decrypted statement PDFs with pdfplumber for Coffer parsers. Use when writing or reviewing any statement parser's production entry point (the pdfplumber side of parse()), handling multi-page statements, deciding text vs. table extraction, or routing scanned/empty-text PDFs to OCR/manual review. Keeps parsers pure — no disk, no decryption — per Coffer's parser rules.
---

# pdfplumber — statement text/table extraction (Coffer parsers)

A parser is a **pure function** on already-decrypted input. `parse_text(text)` does the
real work and is what tests target with an anonymized text fixture. `parse(source)` is the
thin production entry point that turns a decrypted path/bytes/stream into text via pdfplumber.

## Text extraction (the common case for CIMB-style line-item statements)

```python
import io
import pdfplumber

def parse(source: str | bytes | bytearray | "IO[bytes]") -> ParsedStatement:
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    with pdfplumber.open(source) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if len(text.strip()) < 50:
        # scanned image / no text layer → do NOT return partial data
        raise StatementParseError("near-empty extraction — route to OCR/manual review")
    return parse_text(text)
```

Notes:
- `page.extract_text()` returns `None` for a page with no text layer — the `or ""` guard
  matters. Join **all** pages: statements can span multiple pages (a known CIMB unknown).
- `pdfplumber.open` accepts a path, a `BytesIO`, or an open binary file — so the in-memory
  `BytesIO` from [[pikepdf-decrypt]] flows straight in. Never write plaintext to disk to
  "make pdfplumber happy."
- `extract_text(layout=True)` preserves column spacing when word order gets scrambled by the
  default reading order — reach for it only if the flat text loses row structure.

## When to use tables instead of text

Line-item statements (CIMB CC) parse cleanly from flat text + regex. Reach for tables when
a statement is a real grid (some savings/portfolio SOAs):

```python
for page in pdf.pages:
    for table in page.extract_tables():          # list[list[list[str | None]]]
        for row in table:
            ...  # cells can be None; guard before Decimal()
```

`extract_tables()` uses line-detection heuristics; if it misses, tune
`table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"}`.

## Extraction hygiene
- **Raise, never return partial data.** Structural mismatch → `StatementParseError`. A silent
  bad parse corrupts net worth (CLAUDE.md).
- Money stays a **string until the domain converts it** with `Decimal(s.replace(",", ""))` —
  never `float`. Keep locale/format handling documented per parser.
- Empty/near-empty text is the scanned-PDF signal → route to OCR/manual review, don't guess.
- Keep pdfplumber **only** in `parse()`. `parse_text()` must import nothing heavy so tests
  run in milliseconds against text fixtures (F.I.R.S.T., see [[tdd]]).

## Testing
- Test `parse_text()` against `tests/fixtures/*.txt` (anonymized; real amounts/dates so
  reconciliation is genuine). Do not commit real PDFs.
- One test per parser must feed empty/near-empty text and assert it raises rather than
  producing a zero-transaction statement.
```
