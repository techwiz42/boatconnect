"""Sending mail through an SMTP server: either a relay that trusts this machine by its address (no login), or a mailbox with an app password (Gmail's smtp.gmail.com).

Sending is best-effort and never holds up a request: a message that cannot be delivered is logged (the address, never the text) and dropped. With no relay configured nothing is
sent, and the features that depend on mail say so. Tests pass in a fake that records messages instead.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mail:
    """What to say; who it goes to is decided where it is sent."""
    subject: str
    text: str
    html: str
    unsubscribe_url: Optional[str] = None            # for mail a person can opt out of: becomes the List-Unsubscribe header (one-click)


def one_line(value: str, limit: int = 200) -> str:
    """A header value from text a user wrote: one line, no control characters (so it cannot add headers of its own)."""
    cleaned = " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())
    return cleaned[:limit]


def build_message(sender: str, reply_to: Optional[str], to: str, mail: Mail) -> EmailMessage:
    domain = sender.rsplit("@", 1)[-1].rstrip("> ")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = one_line(to, 320)
    if reply_to:
        message["Reply-To"] = reply_to
    message["Subject"] = one_line(mail.subject)
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=domain)
    message["Auto-Submitted"] = "auto-generated"                                       # a notice, not a conversation: autoresponders leave it alone
    if mail.unsubscribe_url:
        message["List-Unsubscribe"] = f"<{mail.unsubscribe_url}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(mail.text)
    message.add_alternative(mail.html, subtype="html")
    return message


class Mailer:
    enabled = False

    async def send(self, to: Sequence[str], mail: Mail) -> None:                       # pragma: no cover - the interface
        raise NotImplementedError


class NoMailer(Mailer):
    """No relay is configured: nothing is sent."""
    enabled = False

    async def send(self, to: Sequence[str], mail: Mail) -> None:
        return None


class SmtpMailer(Mailer):
    enabled = True

    def __init__(self, host: str, port: int, sender: str, reply_to: Optional[str] = None, timeout: float = 20.0, starttls: bool = True,
                 username: str = "", password: str = "") -> None:
        self.host, self.port, self.sender, self.reply_to, self.timeout, self.starttls = host, port, sender, reply_to, timeout, starttls
        self.username, self.password = username, password

    def _deliver(self, recipients: List[str], mail: Mail) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.username:                                                          # only ever after the connection is encrypted
                smtp.ehlo_or_helo_if_needed()
                smtp.user, smtp.password = self.username, self.password
                smtp.auth("LOGIN", smtp.auth_login, initial_response_ok=False)         # Gmail hangs up on the PLAIN that smtplib tries first
            for to in recipients:                                                      # one message each, so nobody sees anyone else's address
                try:
                    smtp.send_message(build_message(self.sender, self.reply_to, to, mail))
                except smtplib.SMTPException as error:
                    logger.warning("mail to %s was refused: %s", to, error)

    async def send(self, to: Sequence[str], mail: Mail) -> None:
        recipients = sorted({address.strip() for address in to if address and "@" in address})
        if not recipients:
            return
        try:
            await asyncio.to_thread(self._deliver, recipients, mail)
        except (OSError, smtplib.SMTPException) as error:
            logger.warning("mail to %d recipient(s) could not be sent: %s", len(recipients), error)
