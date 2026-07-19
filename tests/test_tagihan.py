"""§3.4 — Bill due-date aggregator read model.

The query-side use-case behind the Ringkasan "Tagihan Jatuh Tempo" card: given a
household's credit-card accounts + members + statements, surface each card's latest
billed statement (the most recent one carrying a ``due_date``) as a ``BillDue`` —
card holder, due date, days remaining, minimum payment, full statement balance —
sorted ascending by days remaining (soonest first). ``today`` is injected so the
countdown is deterministic (the api edge passes ``date.today()``).

Pure and repo-driven like the other read models; exercised with in-memory fakes over
the domain Protocols, no Postgres.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from coffer.domain.entities import Account, Member, Statement
from coffer.domain.enums import AccountType, UploadedVia
from coffer.domain.read_models import (
    BillDue,
    TagihanView,
    bill_due_dates,
    compute_tagihan,
)

HOUSEHOLD = 1
TOMMY, PRISKILA = 1, 2
TODAY = datetime.date(2026, 7, 19)


# ── builders ─────────────────────────────────────────────────────────────────────────
def member(id_: int, name: str) -> Member:
    return Member(id=id_, household_id=HOUSEHOLD, name=name)


def account(id_: int, member_id: int, account_type: AccountType) -> Account:
    return Account(
        id=id_,
        member_id=member_id,
        institution="bca" if account_type is AccountType.BCA_CREDIT_CARD else "cimb",
        account_type=account_type,
        account_number_masked=f"****{id_:04d}",
    )


_stmt_seq = 0


def statement(
    account_id: int,
    period_end: datetime.date,
    *,
    closing: str | None = None,
    due_date: datetime.date | None = None,
    minimum: str | None = None,
) -> Statement:
    global _stmt_seq
    _stmt_seq += 1
    return Statement(
        id=_stmt_seq,
        account_id=account_id,
        period_start=datetime.date(period_end.year, period_end.month, 1),
        period_end=period_end,
        file_hash=f"f{_stmt_seq}",
        content_hash=f"c{_stmt_seq}",
        uploaded_via=UploadedVia.WEB,
        uploaded_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        parser_version="v1",
        is_encrypted=False,
        closing_balance=Decimal(closing) if closing is not None else None,
        due_date=due_date,
        minimum_payment=Decimal(minimum) if minimum is not None else None,
    )


# ── in-memory fakes over the domain Protocols ──────────────────────────────────────────
class FakeAccountRepo:
    def __init__(self, accounts: list[Account]) -> None:
        self._accounts = accounts

    def list_by_household(self, household_id: int) -> list[Account]:
        return list(self._accounts)

    def add(self, account: Account) -> Account:
        raise NotImplementedError

    def get(self, account_id: int) -> Account | None:
        raise NotImplementedError

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        raise NotImplementedError


class FakeMemberRepo:
    def __init__(self, members: list[Member]) -> None:
        self._members = members

    def list_by_household(self, household_id: int) -> list[Member]:
        return list(self._members)

    def add(self, member: Member) -> Member:
        raise NotImplementedError

    def get(self, member_id: int) -> Member | None:
        raise NotImplementedError

    def by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        raise NotImplementedError


class FakeStatementRepo:
    def __init__(self, statements: list[Statement]) -> None:
        self._statements = statements

    def list_by_account(self, account_id: int) -> list[Statement]:
        return sorted(
            (s for s in self._statements if s.account_id == account_id),
            key=lambda s: s.period_end,
        )

    def add(self, statement: Statement) -> Statement:
        raise NotImplementedError

    def get(self, statement_id: int) -> Statement | None:
        raise NotImplementedError

    def by_file_hash(self, file_hash: str) -> Statement | None:
        raise NotImplementedError

    def by_content_hash(self, content_hash: str) -> Statement | None:
        raise NotImplementedError


# ── the pure core ──────────────────────────────────────────────────────────────────────
def test_credit_card_bill_surfaces_with_all_fields() -> None:
    accts = [account(2, TOMMY, AccountType.BCA_CREDIT_CARD)]
    members = [member(TOMMY, "Tommy")]
    stmts = {
        2: [
            statement(
                2,
                datetime.date(2026, 7, 5),
                closing="2177067",
                due_date=datetime.date(2026, 7, 25),
                minimum="150000",
            )
        ]
    }

    bills = bill_due_dates(accts, members, stmts, today=TODAY)

    assert bills == [
        BillDue(
            account_id=2,
            member_id=TOMMY,
            member_name="Tommy",
            institution="bca",
            account_type=AccountType.BCA_CREDIT_CARD,
            account_number_masked="****0002",
            due_date=datetime.date(2026, 7, 25),
            days_remaining=6,  # 25 − 19 Jul
            minimum_payment=Decimal("150000"),
            statement_balance=Decimal("2177067"),
        )
    ]


def test_latest_statement_with_a_due_date_wins() -> None:
    accts = [account(2, TOMMY, AccountType.CIMB_CREDIT_CARD)]
    stmts = {
        2: [
            statement(
                2, datetime.date(2026, 6, 5), closing="500000", due_date=datetime.date(2026, 6, 25)
            ),
            statement(
                2, datetime.date(2026, 7, 5), closing="838303", due_date=datetime.date(2026, 7, 25)
            ),
        ]
    }

    bills = bill_due_dates(accts, [member(TOMMY, "Tommy")], stmts, today=TODAY)

    assert len(bills) == 1
    assert bills[0].due_date == datetime.date(2026, 7, 25)
    assert bills[0].statement_balance == Decimal("838303")


def test_sorted_ascending_by_days_remaining() -> None:
    accts = [
        account(2, TOMMY, AccountType.BCA_CREDIT_CARD),
        account(3, PRISKILA, AccountType.CIMB_CREDIT_CARD),
    ]
    members = [member(TOMMY, "Tommy"), member(PRISKILA, "Priskila")]
    stmts = {
        2: [
            statement(
                2, datetime.date(2026, 7, 5), closing="1", due_date=datetime.date(2026, 7, 28)
            )
        ],
        3: [
            statement(
                3, datetime.date(2026, 7, 3), closing="1", due_date=datetime.date(2026, 7, 22)
            )
        ],
    }

    bills = bill_due_dates(accts, members, stmts, today=TODAY)

    assert [b.account_id for b in bills] == [3, 2]  # 22 Jul (3d) before 28 Jul (9d)
    assert [b.days_remaining for b in bills] == [3, 9]


def test_non_credit_card_accounts_are_excluded() -> None:
    accts = [
        account(1, TOMMY, AccountType.BCA_SAVINGS),
        account(4, TOMMY, AccountType.AJAIB_PORTFOLIO),
        account(2, TOMMY, AccountType.BCA_CREDIT_CARD),
    ]
    stmts = {
        1: [statement(1, datetime.date(2026, 7, 5), closing="611000000")],  # savings, no due date
        4: [statement(4, datetime.date(2026, 7, 5), closing="4750000")],  # portfolio
        2: [
            statement(
                2, datetime.date(2026, 7, 5), closing="1", due_date=datetime.date(2026, 7, 25)
            )
        ],
    }

    bills = bill_due_dates(accts, [member(TOMMY, "Tommy")], stmts, today=TODAY)

    assert [b.account_id for b in bills] == [2]


def test_credit_card_without_a_due_dated_statement_contributes_nothing() -> None:
    accts = [account(2, TOMMY, AccountType.BCA_CREDIT_CARD)]
    stmts = {2: [statement(2, datetime.date(2026, 7, 5), closing="1", due_date=None)]}

    assert bill_due_dates(accts, [member(TOMMY, "Tommy")], stmts, today=TODAY) == []


def test_overdue_bill_has_negative_days_remaining() -> None:
    accts = [account(2, TOMMY, AccountType.BCA_CREDIT_CARD)]
    stmts = {
        2: [
            statement(
                2, datetime.date(2026, 6, 30), closing="1", due_date=datetime.date(2026, 7, 15)
            )
        ]
    }

    bills = bill_due_dates(accts, [member(TOMMY, "Tommy")], stmts, today=TODAY)

    assert bills[0].days_remaining == -4  # 15 − 19 Jul


def test_minimum_payment_none_and_missing_closing_balance() -> None:
    accts = [account(2, TOMMY, AccountType.BCA_CREDIT_CARD)]
    stmts = {
        2: [
            statement(
                2, datetime.date(2026, 7, 5), closing=None, due_date=datetime.date(2026, 7, 25)
            )
        ]
    }

    bills = bill_due_dates(accts, [member(TOMMY, "Tommy")], stmts, today=TODAY)

    assert bills[0].minimum_payment is None
    assert bills[0].statement_balance == Decimal("0")


def test_empty_household_has_no_bills() -> None:
    assert bill_due_dates([], [], {}, today=TODAY) == []


# ── the repo-driven wrapper ────────────────────────────────────────────────────────────
def test_compute_tagihan_wraps_the_pure_core_over_repos() -> None:
    accts = [
        account(2, TOMMY, AccountType.BCA_CREDIT_CARD),
        account(1, TOMMY, AccountType.BCA_SAVINGS),
    ]
    stmts = [
        statement(
            2,
            datetime.date(2026, 7, 5),
            closing="2177067",
            due_date=datetime.date(2026, 7, 25),
            minimum="150000",
        ),
        statement(1, datetime.date(2026, 7, 5), closing="611000000"),
    ]

    view = compute_tagihan(
        household_id=HOUSEHOLD,
        today=TODAY,
        accounts=FakeAccountRepo(accts),
        members=FakeMemberRepo([member(TOMMY, "Tommy")]),
        statements=FakeStatementRepo(stmts),
    )

    assert isinstance(view, TagihanView)
    assert view.as_of == TODAY
    assert [b.account_id for b in view.bills] == [2]
    assert view.bills[0].minimum_payment == Decimal("150000")
