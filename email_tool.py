"""Narrow IMAP email operations for operator-approved Hermes plugins.

OAuth access tokens must be retrieved at call time from a secret manager.  This
module neither stores tokens nor implements a password fallback.  Permanent
delete requires a separate, validated approval token from the policy layer.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import random
import time
from dataclasses import dataclass
from email.header import decode_header, make_header
from typing import Callable


class EmailToolError(RuntimeError):
    """Raised when a bounded mail operation cannot complete safely."""


@dataclass(frozen=True)
class EmailAccount:
    email_address: str
    imap_host: str
    imap_port: int = 993


@dataclass(frozen=True)
class MailSummary:
    uid: str
    sender: str
    subject: str
    received: str


class ImapOAuthTool:
    """Support unread listing and approval-gated state changes for one mailbox."""

    def __init__(self, account: EmailAccount, token_provider: Callable[[], str]) -> None:
        self.account = account
        self.token_provider = token_provider

    async def list_unread(self, *, limit: int = 20) -> list[MailSummary]:
        if not 1 <= limit <= 50:
            raise ValueError("Unread-mail limit must be between 1 and 50.")
        return await asyncio.to_thread(self._retry, self._list_unread_once, limit)

    async def mark_as_read(self, *, uid: str, approval_id: str) -> None:
        self._require_approval(approval_id)
        await asyncio.to_thread(self._retry, self._mark_as_read_once, uid)

    async def delete_permanently(self, *, uid: str, approval_id: str) -> None:
        self._require_approval(approval_id)
        await asyncio.to_thread(self._retry, self._delete_permanently_once, uid)

    def _connect(self) -> imaplib.IMAP4_SSL:
        token = self.token_provider()
        if not token:
            raise EmailToolError("OAuth token provider returned no access token.")
        client = imaplib.IMAP4_SSL(self.account.imap_host, self.account.imap_port, timeout=15)
        auth = f"user={self.account.email_address}\x01auth=Bearer {token}\x01\x01".encode("utf-8")
        response, data = client.authenticate("XOAUTH2", lambda _: auth)
        if response != "OK":
            client.logout()
            raise EmailToolError("OAuth IMAP authentication failed.")
        response, _ = client.select("INBOX", readonly=False)
        if response != "OK":
            client.logout()
            raise EmailToolError("Could not select INBOX.")
        return client

    def _list_unread_once(self, limit: int) -> list[MailSummary]:
        client = self._connect()
        try:
            response, data = client.uid("search", None, "UNSEEN")
            if response != "OK":
                raise EmailToolError("Unread search failed.")
            uids = data[0].decode("ascii").split()[-limit:]
            summaries: list[MailSummary] = []
            for uid in reversed(uids):
                response, records = client.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if response != "OK" or not records or not isinstance(records[0], tuple):
                    continue
                message = email.message_from_bytes(records[0][1])
                summaries.append(
                    MailSummary(
                        uid=uid,
                        sender=self._decode_header(message.get("From", "")),
                        subject=self._decode_header(message.get("Subject", "")),
                        received=message.get("Date", ""),
                    )
                )
            return summaries
        finally:
            client.logout()

    def _mark_as_read_once(self, uid: str) -> None:
        client = self._connect()
        try:
            response, _ = client.uid("store", uid, "+FLAGS.SILENT", "(\\Seen)")
            if response != "OK":
                raise EmailToolError("Could not mark the selected message as read.")
        finally:
            client.logout()

    def _delete_permanently_once(self, uid: str) -> None:
        client = self._connect()
        try:
            response, _ = client.uid("store", uid, "+FLAGS.SILENT", "(\\Deleted)")
            if response != "OK":
                raise EmailToolError("Could not mark the selected message for deletion.")
            response, _ = client.expunge()
            if response != "OK":
                raise EmailToolError("Permanent deletion could not be completed.")
        finally:
            client.logout()

    @staticmethod
    def _decode_header(value: str) -> str:
        try:
            return str(make_header(decode_header(value)))[:500]
        except (ValueError, TypeError):
            return "[undecodable header]"

    @staticmethod
    def _require_approval(approval_id: str) -> None:
        if len(approval_id) < 16:
            raise PermissionError("A validated, short-lived human approval is required.")

    @staticmethod
    def _retry(operation, *args):
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                return operation(*args)
            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError, EmailToolError) as error:
                last_error = error
                if attempt < 3:
                    time.sleep(random.uniform(0, min(4.0, 0.5 * (2 ** (attempt - 1)))))
        raise EmailToolError("Mail operation failed after bounded retries.") from last_error
