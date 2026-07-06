---
name: sqlalchemy-2x
description: Model Coffer's Postgres persistence with SQLAlchemy 2.0 and Alembic. Use when writing or reviewing the S4 persistence layer — mapping money as Decimal (never Float), defining tables for the SPEC §2 model, implementing domain repository interfaces, session handling, or writing up/down migrations. Enforces Clean Architecture: repos in persistence implement interfaces declared in domain; the dependency points inward.
---

# SQLAlchemy 2.0 + Alembic — Coffer persistence (S4)

Persistence is an **outer** layer: it *implements* repository interfaces declared in
`coffer.domain`. Domain never imports SQLAlchemy. UI/api depend on the interface, never
the concrete repo (import-linter enforces this).

## Money is `Decimal`, always — map with `Numeric`, never `Float`

```python
from decimal import Decimal
from sqlalchemy import Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

MONEY = Numeric(18, 2, asdecimal=True)   # returns Decimal; scale 2 for IDR-at-rest

class TransactionRow(Base):
    __tablename__ = "transaction"
    id:      Mapped[int]     = mapped_column(primary_key=True)
    debit:   Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    credit:  Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    dedup_key: Mapped[str]   = mapped_column(String, index=True, unique=True)
```

`Numeric(asdecimal=True)` round-trips `Decimal` exactly. **Never** `Float`/`REAL` for money —
it reintroduces the binary-float error the whole domain avoids. Postgres type is `NUMERIC`.

## The domain interface / persistence impl split

```python
# coffer/domain/repositories.py  — pure, no SQLAlchemy
from typing import Protocol
class TransactionRepo(Protocol):
    def add(self, txn: "Transaction") -> None: ...
    def by_dedup_key(self, key: str) -> "Transaction | None": ...

# coffer/persistence/transaction_repo.py  — implements the Protocol
class SqlTransactionRepo:
    def __init__(self, session: Session) -> None:
        self._session = session
    def add(self, txn: Transaction) -> None:
        self._session.add(_to_row(txn))
    def by_dedup_key(self, key: str) -> Transaction | None:
        row = self._session.scalar(select(TransactionRow).where(TransactionRow.dedup_key == key))
        return _to_domain(row) if row else None
```

Map ORM rows ↔ domain entities at the boundary (`_to_row`/`_to_domain`). Don't leak ORM
objects into the domain — keeps domain a pure value world (see [[clean-architecture]]).

## Sessions & queries (2.0 style)

```python
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

engine = create_engine(settings.database_url)     # never hardcode; no creds in code

with Session(engine) as session, session.begin():  # begin() = commit on success, rollback on error
    repo = SqlTransactionRepo(session)
    repo.add(txn)
```

Use `select(...)` + `session.scalars()/scalar()` — the 1.x `session.query()` API is legacy.
Net-worth recompute is **serialized per household** (S7): take a row/advisory lock inside the
transaction so two concurrent ingests can't corrupt the snapshot.

## Alembic migrations (up AND down)
- `alembic revision --autogenerate -m "S4: SPEC §2 model"`, then **read** the generated file —
  autogenerate misses `Numeric` scale changes, indexes, and enums.
- Every migration needs a working `downgrade()` (DoD: migration up/down tested).
- Encryption at rest: store only the **encrypted** original blob + hashes, never plaintext.

## Testing
- Repo round-trip per aggregate against a real Postgres (testcontainers or a disposable schema),
  not SQLite — `NUMERIC`/locking/`ON CONFLICT` semantics differ.
- Assert a `Decimal("838303.83")` round-trips byte-identical (no float drift).
- Migration up→down→up leaves an empty-but-valid schema. Pair with [[tdd]].
```
