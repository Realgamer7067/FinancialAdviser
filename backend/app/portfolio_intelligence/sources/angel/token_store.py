"""Short-lived Angel session store shared by the API process and the worker.

A 0600 JSON file in a 0700 directory OUTSIDE the repository. Holds only the
session tokens and their expiry -- never the PIN, TOTP or TOTP seed. Angel
sessions end at midnight IST, so `expires_at` is the next 00:00 IST and an
expired file reads as "no session". Writes are atomic (temp file + rename)."""

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.utils.time import utcnow

IST = ZoneInfo("Asia/Kolkata")
_FILE = "angel_session.json"


def session_dir() -> Path:
    return Path(settings.angel_session_dir).expanduser() if settings.angel_session_dir else Path.home() / ".local" / "state" / "pie"


def _path() -> Path:
    return session_dir() / _FILE


@dataclass(frozen=True)
class Session:
    jwt: str
    refresh_token: str
    feed_token: str
    expires_at: datetime
    obtained_at: datetime

    def __repr__(self) -> str:  # never leak tokens through logs/tracebacks
        return f"Session(expires_at={self.expires_at.isoformat()})"


def next_midnight_ist(now: datetime | None = None) -> datetime:
    now_ist = (now or utcnow()).astimezone(IST)
    return (now_ist + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def save_session(jwt: str, refresh_token: str, feed_token: str, *, now: datetime | None = None) -> Session:
    now = now or utcnow()
    d = session_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    sess = Session(jwt, refresh_token, feed_token, next_midnight_ist(now), now)
    payload = {
        "jwt": jwt,
        "refresh_token": refresh_token,
        "feed_token": feed_token,
        "expires_at": sess.expires_at.isoformat(),
        "obtained_at": now.isoformat(),
    }
    tmp = d / (_FILE + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, _path())
    return sess


def load_session(*, now: datetime | None = None) -> Session | None:
    """None if absent, unreadable, wrongly permissioned, or expired."""
    p = _path()
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:  # readable by group/other: refuse rather than trust it
            return None
        data = json.loads(p.read_text())
        sess = Session(
            data["jwt"],
            data["refresh_token"],
            data["feed_token"],
            datetime.fromisoformat(data["expires_at"]),
            datetime.fromisoformat(data["obtained_at"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if sess.expires_at <= (now or utcnow()):
        return None
    return sess


def clear_session() -> None:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass
