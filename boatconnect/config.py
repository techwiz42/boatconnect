"""Settings from the environment: where the data lives, who administers the site, and whether cookies are marked Secure (true behind https)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    admin_emails: Tuple[str, ...]
    cookie_secure: bool
    mail_host: str                      # the SMTP relay; empty means no mail is sent
    mail_port: int
    mail_starttls: bool                 # the relay is always reached over TLS; off only for a local test server
    mail_user: str                      # a mailbox to log in as (Gmail with an app password); empty for a relay that trusts this machine
    mail_password: str
    mail_from: str
    mail_reply_to: str
    public_url: str                     # what links in emails point at

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        admins = tuple(sorted({e.strip().lower() for e in env.get("ADMIN_EMAILS", "").split(",") if e.strip()}))
        return cls(
            data_dir=Path(env.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data"),
            admin_emails=admins,
            cookie_secure=env.get("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes"),
            mail_host=env.get("MAIL_HOST", "").strip(),
            mail_port=int(env.get("MAIL_PORT", "587") or 587),
            mail_starttls=env.get("MAIL_STARTTLS", "1").strip().lower() not in ("0", "false", "no"),
            mail_user=env.get("MAIL_USER", "").strip(),
            mail_password=env.get("MAIL_PASSWORD", "").replace(" ", ""),     # Google shows app passwords in groups of four
            mail_from=env.get("MAIL_FROM", "boatconnect <noreply@boatconnect.org>").strip(),
            mail_reply_to=env.get("MAIL_REPLY_TO", "").strip(),
            public_url=(env.get("PUBLIC_URL", "https://boatconnect.org").strip().rstrip("/")),
        )
