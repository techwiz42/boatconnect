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

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        admins = tuple(sorted({e.strip().lower() for e in env.get("ADMIN_EMAILS", "").split(",") if e.strip()}))
        return cls(
            data_dir=Path(env.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data"),
            admin_emails=admins,
            cookie_secure=env.get("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes"),
        )
