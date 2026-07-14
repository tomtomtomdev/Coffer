"""Telegram ingestion use-case (SPEC §4/§5) — the bot's business logic.

The Telegram bot is a second entry point into the same pipeline as web upload, so this
use-case is a thin orchestrator around ``IngestStatement.execute`` (reused verbatim,
with ``uploaded_via=TELEGRAM``). It owns only the concerns that are Telegram-specific:

  * **Server-side allowlist.** ``telegram_user_id`` must map to a household ``member``
    (SPEC §5). An unknown user is *silently ignored* — no download, no reply — so the
    bot never confirms it exists to a stranger (treat Telegram as untrusted transport).
  * **Account auto-detection.** Web upload sends a manually-selected ``account_id``; the
    bot has none, so it decrypts + extracts the header text and sniffs the
    ``AccountType`` (``coffer.ingestion.detect``), then resolves it to one of the
    household's accounts. Exactly one match → ingest straight away. Zero or many → reply
    with an **inline keyboard** to pick, and complete the ingest on the callback.
  * **Passwords, reconciled for unattended ingest.** Web upload takes a runtime password
    (Tommy's preference); an unattended Telegram upload cannot prompt, and a password
    typed into a Telegram chat is exactly the plaintext-on-untrusted-transport we avoid.
    So encrypted statements are decrypted with the household's **stored ``static``
    credential** (``InstitutionCredential``). We try each stored credential in memory
    (bounded by the household's few institutions) — the one that opens the PDF is passed
    to ``execute``. No stored credential opens it → reply "🔒 needs password", no ingest.
    The attempted password is never logged (security invariant).
  * **Delete after ingest.** On a successful ingest the source message is deleted (SPEC
    §4) so the raw statement does not linger on Telegram's servers.

Clean Architecture: this lives in ``ingestion`` and depends only on domain repo
Protocols, its sibling ingestion modules, and injected ports. The concrete Telegram
HTTP client + pending-upload store are wired in the api layer (they implement the
``TelegramClient`` / ``PendingUploadStore`` Protocols here), so the dependency points
inward and the use-case is testable with in-memory fakes (mirrors ``pipeline``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coffer.domain.entities import Account, Member
from coffer.domain.enums import AccountType, PasswordScheme, UploadedVia
from coffer.domain.repositories import (
    AccountRepo,
    InstitutionCredentialRepo,
    MemberRepo,
)
from coffer.ingestion.decrypt import StatementDecryptionError
from coffer.ingestion.detect import detect_account_type
from coffer.ingestion.pipeline import IngestOutcome, IngestResult, PdfReader

__all__ = [
    "InlineButton",
    "Ingestor",
    "PendingUpload",
    "PendingUploadStore",
    "TelegramClient",
    "TelegramIngest",
    "TelegramOutcome",
    "TelegramResult",
]


# ── injected ports (concrete adapters live in the api layer) ─────────────────────────
@dataclass(frozen=True)
class InlineButton:
    """One inline-keyboard button. ``callback_data`` rides back to us on the tap."""

    text: str
    callback_data: str


@dataclass(frozen=True)
class PendingUpload:
    """A statement awaiting an account pick — stashed between the document message and
    the inline-keyboard callback. Holds no password (re-resolved from credentials)."""

    file_id: str
    chat_id: int
    message_id: int  # the original document message (deleted on a successful ingest)
    telegram_user_id: int


class Ingestor(Protocol):
    """The pipeline use-case this bot delegates to (``IngestStatement.execute``)."""

    def execute(
        self,
        *,
        raw_bytes: bytes,
        account_id: int,
        uploaded_via: UploadedVia,
        password: str | None = None,
        uploaded_by_member_id: int | None = None,
    ) -> IngestResult: ...


class TelegramClient(Protocol):
    """The Telegram Bot API surface the bot needs (concrete: httpx in the api layer)."""

    def download_file(self, file_id: str) -> bytes: ...
    def send_message(
        self, *, chat_id: int, text: str, buttons: list[InlineButton] | None = None
    ) -> None: ...
    def delete_message(self, *, chat_id: int, message_id: int) -> None: ...
    def answer_callback_query(self, callback_query_id: str) -> None: ...


class PendingUploadStore(Protocol):
    """Short-lived store for uploads awaiting an account pick (keyed ``chat:message``)."""

    def put(self, token: str, upload: PendingUpload) -> None: ...
    def pop(self, token: str) -> PendingUpload | None: ...


# ── outcome model ────────────────────────────────────────────────────────────────────
class TelegramOutcome(StrEnum):
    IGNORED = "ignored"  # not on the allowlist, or another user's callback — silent
    UNSUPPORTED = "unsupported"  # a callback we couldn't parse
    INGESTED = "ingested"
    DUPLICATE = "duplicate"
    NEEDS_PASSWORD = "needs_password"
    NEEDS_ACCOUNT = "needs_account"  # detection ambiguous/failed → keyboard sent
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


@dataclass(frozen=True)
class TelegramResult:
    outcome: TelegramOutcome
    ingest: IngestResult | None = None


# ── Bahasa Indonesia replies (UI copy is BI — CLAUDE.md) ─────────────────────────────
_NEEDS_PASSWORD_MSG = (
    "🔒 Laporan terenkripsi dan tidak ada kata sandi tersimpan untuk institusi ini. "
    "Tambahkan kredensial lewat web, lalu kirim ulang berkasnya."
)
_PICK_ACCOUNT_MSG = "Rekening tidak terdeteksi otomatis. Pilih rekening untuk laporan ini:"
_NO_ACCOUNTS_MSG = "⚠️ Tidak ada rekening yang cocok. Tambahkan rekening lewat web terlebih dahulu."
_EXPIRED_MSG = "Sesi unggahan sudah kedaluwarsa. Kirim ulang berkasnya."


@dataclass
class TelegramIngest:
    members: MemberRepo
    accounts: AccountRepo
    credentials: InstitutionCredentialRepo
    reader: PdfReader
    ingest: Ingestor
    client: TelegramClient
    pending: PendingUploadStore

    # ── entry points (called by the humble webhook router) ────────────────────────────
    def handle_document(
        self, *, telegram_user_id: int, chat_id: int, message_id: int, file_id: str
    ) -> TelegramResult:
        """A PDF arrived. Detect the account and ingest, or ask which account."""
        member = self.members.by_telegram_user_id(telegram_user_id)
        if member is None:  # allowlist: never download or reply to a stranger.
            return TelegramResult(TelegramOutcome.IGNORED)

        raw = self.client.download_file(file_id)
        opened = self._open(raw, member.household_id)
        if opened is None:
            self.client.send_message(chat_id=chat_id, text=_NEEDS_PASSWORD_MSG)
            return TelegramResult(TelegramOutcome.NEEDS_PASSWORD)
        text, password = opened

        account_type = detect_account_type(text)
        candidates = (
            self._accounts_of_type(member.household_id, account_type)
            if account_type is not None
            else []
        )
        if len(candidates) == 1:
            return self._finish(
                member=member,
                raw=raw,
                account=candidates[0],
                chat_id=chat_id,
                doc_message_id=message_id,
                password=password,
            )

        # 0 (undetected / no matching account) or >1 (ambiguous) → let the user pick.
        options = (
            candidates
            if len(candidates) > 1
            else self.accounts.list_by_household(member.household_id)
        )
        if not options:
            self.client.send_message(chat_id=chat_id, text=_NO_ACCOUNTS_MSG)
            return TelegramResult(TelegramOutcome.NEEDS_ACCOUNT)
        self._send_account_keyboard(
            chat_id=chat_id,
            doc_message_id=message_id,
            telegram_user_id=telegram_user_id,
            file_id=file_id,
            accounts=options,
        )
        return TelegramResult(TelegramOutcome.NEEDS_ACCOUNT)

    def handle_callback(
        self, *, telegram_user_id: int, callback_query_id: str, callback_data: str, chat_id: int
    ) -> TelegramResult:
        """The user tapped an account button. Complete the deferred ingest."""
        member = self.members.by_telegram_user_id(telegram_user_id)
        if member is None:
            self.client.answer_callback_query(callback_query_id)
            return TelegramResult(TelegramOutcome.IGNORED)

        parsed = _parse_callback(callback_data)
        if parsed is None:
            self.client.answer_callback_query(callback_query_id)
            return TelegramResult(TelegramOutcome.UNSUPPORTED)
        token, account_id = parsed

        upload = self.pending.pop(token)
        if upload is None:
            self.client.answer_callback_query(callback_query_id)
            self.client.send_message(chat_id=chat_id, text=_EXPIRED_MSG)
            return TelegramResult(TelegramOutcome.NEEDS_ACCOUNT)
        if upload.telegram_user_id != telegram_user_id:  # only the uploader may complete it
            self.pending.put(token, upload)  # restore — not this user's to finish
            self.client.answer_callback_query(callback_query_id)
            return TelegramResult(TelegramOutcome.IGNORED)

        account = self._household_account(account_id, member.household_id)
        if account is None:
            self.client.answer_callback_query(callback_query_id)
            self.client.send_message(chat_id=upload.chat_id, text=_NO_ACCOUNTS_MSG)
            return TelegramResult(TelegramOutcome.NEEDS_ACCOUNT)

        raw = self.client.download_file(upload.file_id)
        opened = self._open(raw, member.household_id)  # text unused here; want the password
        if opened is None:
            self.client.answer_callback_query(callback_query_id)
            self.client.send_message(chat_id=upload.chat_id, text=_NEEDS_PASSWORD_MSG)
            return TelegramResult(TelegramOutcome.NEEDS_PASSWORD)
        _text, password = opened

        result = self._finish(
            member=member,
            raw=raw,
            account=account,
            chat_id=upload.chat_id,
            doc_message_id=upload.message_id,
            password=password,
        )
        self.client.answer_callback_query(callback_query_id)
        return result

    # ── internals ─────────────────────────────────────────────────────────────────────
    def _finish(
        self,
        *,
        member: Member,
        raw: bytes,
        account: Account,
        chat_id: int,
        doc_message_id: int,
        password: str | None,
    ) -> TelegramResult:
        assert account.id is not None
        result = self.ingest.execute(
            raw_bytes=raw,
            account_id=account.id,
            uploaded_via=UploadedVia.TELEGRAM,
            password=password,
            uploaded_by_member_id=member.id,
        )
        self.client.send_message(chat_id=chat_id, text=_reply_text(result))
        if result.ok:
            # Untrusted transport: drop the raw statement from Telegram once it's stored.
            self.client.delete_message(chat_id=chat_id, message_id=doc_message_id)
        return TelegramResult(TelegramOutcome(result.outcome.value), ingest=result)

    def _open(self, raw: bytes, household_id: int) -> tuple[str, str | None] | None:
        """Decrypt in memory + extract text, returning ``(text, password)`` or ``None``
        when the PDF is encrypted and no stored credential opens it. Unencrypted PDFs
        need no password; encrypted ones are opened with a stored ``static`` credential
        (never a chat-typed password). The tried password is never logged."""
        try:
            return self.reader.read(raw, None).text, None
        except StatementDecryptionError:
            pass  # encrypted — fall through to the stored credentials
        for secret in self._candidate_secrets(household_id):
            try:
                return self.reader.read(raw, secret).text, secret
            except StatementDecryptionError:
                continue
        return None

    def _candidate_secrets(self, household_id: int) -> list[str]:
        """Stored ``static`` statement passwords for the household's institutions."""
        institutions = sorted(
            {a.institution for a in self.accounts.list_by_household(household_id)}
        )
        secrets: list[str] = []
        for institution in institutions:
            cred = self.credentials.by_household_institution(household_id, institution)
            if cred is not None and cred.password_scheme is PasswordScheme.STATIC and cred.secret:
                secrets.append(cred.secret)
        return secrets

    def _accounts_of_type(self, household_id: int, account_type: AccountType) -> list[Account]:
        return [
            a
            for a in self.accounts.list_by_household(household_id)
            if a.account_type is account_type
        ]

    def _household_account(self, account_id: int, household_id: int) -> Account | None:
        account = self.accounts.get(account_id)
        if account is None or account.id is None:
            return None
        member = self.members.get(account.member_id)
        if member is None or member.household_id != household_id:
            return None  # never ingest into another household's account
        return account

    def _send_account_keyboard(
        self,
        *,
        chat_id: int,
        doc_message_id: int,
        telegram_user_id: int,
        file_id: str,
        accounts: list[Account],
    ) -> None:
        token = _token(chat_id, doc_message_id)
        self.pending.put(
            token,
            PendingUpload(
                file_id=file_id,
                chat_id=chat_id,
                message_id=doc_message_id,
                telegram_user_id=telegram_user_id,
            ),
        )
        buttons = [
            InlineButton(
                text=_account_label(a),
                callback_data=f"acct:{chat_id}:{doc_message_id}:{a.id}",
            )
            for a in accounts
            if a.id is not None
        ]
        self.client.send_message(chat_id=chat_id, text=_PICK_ACCOUNT_MSG, buttons=buttons)


def _token(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _parse_callback(data: str) -> tuple[str, int] | None:
    """``acct:<chat_id>:<message_id>:<account_id>`` → (``chat:message`` token, account_id)."""
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "acct":
        return None
    try:
        chat_id, message_id, account_id = int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError:
        return None
    return _token(chat_id, message_id), account_id


def _account_label(account: Account) -> str:
    return (
        f"{account.institution.upper()} · {account.account_type.value} · "
        f"{account.account_number_masked}"
    )


def _reply_text(result: IngestResult) -> str:
    outcome = result.outcome
    if outcome is IngestOutcome.INGESTED:
        parts = [f"✅ {result.new_transactions} transaksi baru"]
        if result.duplicate_transactions:
            parts.append(f"⏭️ {result.duplicate_transactions} duplikat dilewati")
        if result.holdings:
            parts.append(f"📊 {result.holdings} kepemilikan")
        return ", ".join(parts) + "."
    if outcome is IngestOutcome.DUPLICATE:
        return "⏭️ Laporan ini sudah pernah diunggah."
    if outcome is IngestOutcome.NEEDS_PASSWORD:
        return _NEEDS_PASSWORD_MSG
    if outcome is IngestOutcome.NEEDS_ACCOUNT:
        return _NO_ACCOUNTS_MSG
    if outcome is IngestOutcome.NEEDS_REVIEW:
        return "⚠️ Ekstraksi teks nyaris kosong — perlu tinjauan manual (kemungkinan hasil scan)."
    return f"❌ Laporan ditolak: {result.reason}"
