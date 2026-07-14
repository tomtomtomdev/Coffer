"""S10 — Telegram ingestion use-case (``coffer.ingestion.telegram``).

Unit tests over in-memory fakes for the domain repo Protocols + the injected ports
(``TelegramClient`` / ``PendingUploadStore`` / ``PdfReader`` / ``Ingestor``). No real
Telegram, PDF or DB — the concrete httpx client + store adapters are wired in the
api layer. Here we pin the *orchestration* the use-case owns (SPEC §4/§5):

  * server-side ``telegram_user_id`` allowlist (unknown user → silent ignore),
  * account auto-detection from header text → resolve to a household account,
  * inline-keyboard on ambiguity + the callback that completes the ingest,
  * stored ``static`` credential for encrypted statements (never prompt in chat),
  * delete the source message only after a successful ingest.
"""

from __future__ import annotations

from dataclasses import replace

from coffer.domain.entities import Account, InstitutionCredential, Member
from coffer.domain.enums import AccountType, PasswordScheme, UploadedVia
from coffer.ingestion.decrypt import StatementDecryptionError
from coffer.ingestion.pipeline import DecryptedPdf, IngestOutcome, IngestResult
from coffer.ingestion.telegram import (
    InlineButton,
    PendingUpload,
    TelegramIngest,
    TelegramOutcome,
)

_TAHAPAN = "REKENING TAHAPAN\nMEMBER SATU NO. REKENING : 0160XXXXXX\nPERIODE : JUNI 2026\n" + (
    "x" * 100
)
_JUNK = "this is not a bank statement at all, just some text " * 4
_INGESTED = IngestResult(IngestOutcome.INGESTED, new_transactions=5)


# ── in-memory fakes ──────────────────────────────────────────────────────────────────
class _Counter:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> int:
        self.n += 1
        return self.n


class _FakeMemberRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, Member] = {}
        self._c = _Counter()

    def add(self, member: Member) -> Member:
        m = replace(member, id=self._c.next())
        assert m.id is not None
        self._by_id[m.id] = m
        return m

    def get(self, member_id: int) -> Member | None:
        return self._by_id.get(member_id)

    def by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        return next(
            (m for m in self._by_id.values() if m.telegram_user_id == telegram_user_id), None
        )

    def list_by_household(self, household_id: int) -> list[Member]:
        return [m for m in self._by_id.values() if m.household_id == household_id]


class _FakeAccountRepo:
    def __init__(self, members: _FakeMemberRepo) -> None:
        self._members = members
        self._by_id: dict[int, Account] = {}
        self._c = _Counter()

    def add(self, account: Account) -> Account:
        a = replace(account, id=self._c.next())
        assert a.id is not None
        self._by_id[a.id] = a
        return a

    def get(self, account_id: int) -> Account | None:
        return self._by_id.get(account_id)

    def by_number_masked(self, account_number_masked: str) -> Account | None:
        return next(
            (a for a in self._by_id.values() if a.account_number_masked == account_number_masked),
            None,
        )

    def list_by_household(self, household_id: int) -> list[Account]:
        out = []
        for a in self._by_id.values():
            m = self._members.get(a.member_id)
            if m is not None and m.household_id == household_id:
                out.append(a)
        return out


class _FakeCredentialRepo:
    def __init__(self) -> None:
        self._by_key: dict[tuple[int, str], InstitutionCredential] = {}
        self._c = _Counter()

    def add(self, credential: InstitutionCredential) -> InstitutionCredential:
        c = replace(credential, id=self._c.next())
        self._by_key[(c.household_id, c.institution)] = c
        return c

    def get(self, credential_id: int) -> InstitutionCredential | None:
        return next((c for c in self._by_key.values() if c.id == credential_id), None)

    def by_household_institution(
        self, household_id: int, institution: str
    ) -> InstitutionCredential | None:
        return self._by_key.get((household_id, institution))


class _FakeReader:
    """Stands in for pikepdf/pdfplumber. If ``encrypted``, only ``password`` decrypts."""

    def __init__(self, text: str, *, encrypted: bool = False, password: str | None = None) -> None:
        self._text = text
        self._encrypted = encrypted
        self._password = password

    def read(self, raw_bytes: bytes, password: str | None) -> DecryptedPdf:
        if self._encrypted:
            if password is None or password != self._password:
                raise StatementDecryptionError("wrong or missing password")
            return DecryptedPdf(text=self._text, was_encrypted=True)
        return DecryptedPdf(text=self._text, was_encrypted=False)


class _FakeIngestor:
    def __init__(self, result: IngestResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def execute(
        self,
        *,
        raw_bytes: bytes,
        account_id: int,
        uploaded_via: UploadedVia,
        password: str | None = None,
        uploaded_by_member_id: int | None = None,
    ) -> IngestResult:
        self.calls.append(
            {
                "raw_bytes": raw_bytes,
                "account_id": account_id,
                "uploaded_via": uploaded_via,
                "password": password,
                "uploaded_by_member_id": uploaded_by_member_id,
            }
        )
        return self.result


class _FakeTelegramClient:
    def __init__(self, file_bytes: bytes = b"%PDF-fake") -> None:
        self._file_bytes = file_bytes
        self.downloaded: list[str] = []
        self.sent: list[tuple[int, str, list[InlineButton] | None]] = []
        self.deleted: list[tuple[int, int]] = []
        self.answered: list[str] = []

    def download_file(self, file_id: str) -> bytes:
        self.downloaded.append(file_id)
        return self._file_bytes

    def send_message(
        self, *, chat_id: int, text: str, buttons: list[InlineButton] | None = None
    ) -> None:
        self.sent.append((chat_id, text, buttons))

    def delete_message(self, *, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))

    def answer_callback_query(self, callback_query_id: str) -> None:
        self.answered.append(callback_query_id)


class _FakePendingStore:
    def __init__(self) -> None:
        self._d: dict[str, PendingUpload] = {}

    def put(self, token: str, upload: PendingUpload) -> None:
        self._d[token] = upload

    def pop(self, token: str) -> PendingUpload | None:
        return self._d.pop(token, None)


# ── fixture builder ──────────────────────────────────────────────────────────────────
class _Ctx:
    def __init__(
        self,
        *,
        reader: _FakeReader,
        ingest_result: IngestResult = _INGESTED,
        file_bytes: bytes = b"%PDF-fake",
    ) -> None:
        self.members = _FakeMemberRepo()
        self.accounts = _FakeAccountRepo(self.members)
        self.credentials = _FakeCredentialRepo()
        self.reader = reader
        self.ingestor = _FakeIngestor(ingest_result)
        self.client = _FakeTelegramClient(file_bytes)
        self.pending = _FakePendingStore()

        self.member = self.members.add(Member(household_id=1, name="Tommy", telegram_user_id=111))
        assert self.member.id is not None

        self.uc = TelegramIngest(
            members=self.members,
            accounts=self.accounts,
            credentials=self.credentials,
            reader=self.reader,
            ingest=self.ingestor,
            client=self.client,
            pending=self.pending,
        )

    def add_account(
        self, account_type: AccountType, institution: str = "bca", masked: str = "****1000"
    ) -> int:
        assert self.member.id is not None
        acct = self.accounts.add(
            Account(
                member_id=self.member.id,
                institution=institution,
                account_type=account_type,
                account_number_masked=masked,
            )
        )
        assert acct.id is not None
        return acct.id


def _doc(ctx: _Ctx, *, user: int = 111, chat: int = 900, message: int = 42) -> TelegramOutcome:
    return ctx.uc.handle_document(
        telegram_user_id=user, chat_id=chat, message_id=message, file_id="FILE123"
    ).outcome


# ── allowlist ────────────────────────────────────────────────────────────────────────
def test_non_allowlisted_user_is_silently_ignored() -> None:
    ctx = _Ctx(reader=_FakeReader(_TAHAPAN))
    ctx.add_account(AccountType.BCA_SAVINGS)
    outcome = _doc(ctx, user=666)  # unknown telegram_user_id
    assert outcome is TelegramOutcome.IGNORED
    assert ctx.client.downloaded == []  # never even downloaded the file
    assert ctx.client.sent == []  # no reply — don't leak that the bot exists
    assert ctx.ingestor.calls == []


# ── happy path: detect → ingest → delete ─────────────────────────────────────────────
def test_detected_single_account_ingests_and_deletes_source() -> None:
    ctx = _Ctx(reader=_FakeReader(_TAHAPAN))
    account_id = ctx.add_account(AccountType.BCA_SAVINGS)
    outcome = _doc(ctx)

    assert outcome is TelegramOutcome.INGESTED
    call = ctx.ingestor.calls[0]
    assert call["account_id"] == account_id
    assert call["uploaded_via"] is UploadedVia.TELEGRAM
    assert call["uploaded_by_member_id"] == ctx.member.id
    assert call["password"] is None  # unencrypted
    # source message deleted after a successful ingest (untrusted transport, SPEC §4).
    assert ctx.client.deleted == [(900, 42)]
    # a confirmation was sent and it does NOT leak raw content.
    assert ctx.client.sent and "✅" in ctx.client.sent[0][1]


def test_rejected_ingest_does_not_delete_source() -> None:
    ctx = _Ctx(
        reader=_FakeReader(_TAHAPAN),
        ingest_result=IngestResult(IngestOutcome.REJECTED, reason="balance discontinuity"),
    )
    ctx.add_account(AccountType.BCA_SAVINGS)
    outcome = _doc(ctx)
    assert outcome is TelegramOutcome.REJECTED
    assert ctx.client.deleted == []  # keep the source; the ingest failed
    assert ctx.client.sent and "❌" in ctx.client.sent[0][1]


def test_duplicate_ingest_does_not_delete_source() -> None:
    ctx = _Ctx(
        reader=_FakeReader(_TAHAPAN),
        ingest_result=IngestResult(IngestOutcome.DUPLICATE),
    )
    ctx.add_account(AccountType.BCA_SAVINGS)
    outcome = _doc(ctx)
    assert outcome is TelegramOutcome.DUPLICATE
    assert ctx.client.deleted == []


# ── encrypted statements: stored static credential, never prompt in chat ─────────────
def test_encrypted_uses_stored_static_credential() -> None:
    ctx = _Ctx(reader=_FakeReader(_TAHAPAN, encrypted=True, password="s3cret"))
    account_id = ctx.add_account(AccountType.BCA_SAVINGS)
    ctx.credentials.add(
        InstitutionCredential(
            household_id=1,
            institution="bca",
            password_scheme=PasswordScheme.STATIC,
            secret="s3cret",
        )
    )
    outcome = _doc(ctx)
    assert outcome is TelegramOutcome.INGESTED
    call = ctx.ingestor.calls[0]
    assert call["account_id"] == account_id
    assert call["password"] == "s3cret"  # resolved from the stored credential
    assert ctx.client.deleted == [(900, 42)]


def test_encrypted_without_stored_credential_needs_password() -> None:
    ctx = _Ctx(reader=_FakeReader(_TAHAPAN, encrypted=True, password="s3cret"))
    ctx.add_account(AccountType.BCA_SAVINGS)  # no credential stored
    outcome = _doc(ctx)
    assert outcome is TelegramOutcome.NEEDS_PASSWORD
    assert ctx.ingestor.calls == []
    assert ctx.client.deleted == []
    assert ctx.client.sent and "🔒" in ctx.client.sent[0][1]
    # the prompt never contains the (unknown-to-us) password — nothing to leak.


# ── ambiguity → inline keyboard, then the callback completes it ───────────────────────
def test_ambiguous_accounts_sends_keyboard_without_ingesting() -> None:
    ctx = _Ctx(reader=_FakeReader(_TAHAPAN))
    a1 = ctx.add_account(AccountType.BCA_SAVINGS, masked="****1000")
    a2 = ctx.add_account(AccountType.BCA_SAVINGS, masked="****2000")
    outcome = _doc(ctx)

    assert outcome is TelegramOutcome.NEEDS_ACCOUNT
    assert ctx.ingestor.calls == []  # nothing ingested yet
    assert ctx.client.deleted == []
    # a keyboard with one button per candidate account was sent.
    _chat, _text, buttons = ctx.client.sent[0]
    assert buttons is not None and len(buttons) == 2
    data = {b.callback_data for b in buttons}
    assert f"acct:900:42:{a1}" in data
    assert f"acct:900:42:{a2}" in data
    # the pending upload was stashed keyed by chat:message so the callback can find it.
    assert ctx.pending.pop("900:42") is not None


def test_undetected_type_sends_keyboard_of_all_accounts() -> None:
    ctx = _Ctx(reader=_FakeReader(_JUNK))  # detect_account_type → None
    ctx.add_account(AccountType.BCA_SAVINGS)
    ctx.add_account(AccountType.CIMB_CREDIT_CARD, institution="cimb", masked="****9000")
    outcome = _doc(ctx)
    assert outcome is TelegramOutcome.NEEDS_ACCOUNT
    _chat, _text, buttons = ctx.client.sent[0]
    assert buttons is not None and len(buttons) == 2


def test_callback_completes_ingest_and_deletes_original() -> None:
    ctx = _Ctx(reader=_FakeReader(_TAHAPAN))
    a1 = ctx.add_account(AccountType.BCA_SAVINGS, masked="****1000")
    ctx.add_account(AccountType.BCA_SAVINGS, masked="****2000")
    _doc(ctx)  # → keyboard, pending stashed
    assert ctx.pending.pop("900:42") is not None  # (peek) then restore for the callback
    ctx.pending.put(
        "900:42",
        PendingUpload(file_id="FILE123", chat_id=900, message_id=42, telegram_user_id=111),
    )

    result = ctx.uc.handle_callback(
        telegram_user_id=111,
        callback_query_id="CB1",
        callback_data=f"acct:900:42:{a1}",
        chat_id=900,
    )
    assert result.outcome is TelegramOutcome.INGESTED
    assert ctx.ingestor.calls[0]["account_id"] == a1
    assert ctx.ingestor.calls[0]["uploaded_via"] is UploadedVia.TELEGRAM
    assert ctx.client.deleted == [(900, 42)]  # original document message deleted
    assert ctx.client.answered == ["CB1"]  # spinner dismissed
    assert ctx.pending.pop("900:42") is None  # consumed


def test_callback_from_a_different_user_is_ignored() -> None:
    ctx = _Ctx(reader=_FakeReader(_TAHAPAN))
    a1 = ctx.add_account(AccountType.BCA_SAVINGS, masked="****1000")
    ctx.add_account(AccountType.BCA_SAVINGS, masked="****2000")
    _doc(ctx)

    other = ctx.members.add(Member(household_id=1, name="Priskila", telegram_user_id=222))
    assert other.id is not None
    result = ctx.uc.handle_callback(
        telegram_user_id=222,  # not the uploader
        callback_query_id="CB1",
        callback_data=f"acct:900:42:{a1}",
        chat_id=900,
    )
    assert result.outcome is TelegramOutcome.IGNORED
    assert ctx.ingestor.calls == []
    assert ctx.pending.pop("900:42") is not None  # left intact for the real uploader


def test_callback_with_expired_pending_reports_needs_account() -> None:
    ctx = _Ctx(reader=_FakeReader(_TAHAPAN))
    a1 = ctx.add_account(AccountType.BCA_SAVINGS)
    result = ctx.uc.handle_callback(
        telegram_user_id=111,
        callback_query_id="CB1",
        callback_data=f"acct:900:42:{a1}",  # nothing stashed under 900:42
        chat_id=900,
    )
    assert result.outcome is TelegramOutcome.NEEDS_ACCOUNT
    assert ctx.ingestor.calls == []
    assert ctx.client.answered == ["CB1"]
