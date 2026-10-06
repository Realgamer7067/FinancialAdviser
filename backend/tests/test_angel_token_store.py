import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.portfolio_intelligence.sources.angel import token_store as ts


@pytest.fixture(autouse=True)
def _dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "angel_session_dir", str(tmp_path / "pie"))


def test_roundtrip_permissions_and_no_secret_in_repr():
    sess = ts.save_session("JWT-SECRET", "REFRESH-SECRET", "FEED-SECRET")
    d = ts.session_dir()
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert stat.S_IMODE((d / "angel_session.json").stat().st_mode) == 0o600
    loaded = ts.load_session()
    assert loaded is not None and loaded.jwt == "JWT-SECRET"
    assert "SECRET" not in repr(sess) and "SECRET" not in repr(loaded)


def test_expiry_is_next_midnight_ist():
    now = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)  # 15:30 IST
    exp = ts.next_midnight_ist(now)
    assert exp.astimezone(ts.IST).hour == 0 and exp.astimezone(ts.IST).day == 1
    ts.save_session("j", "r", "f", now=now)
    assert ts.load_session(now=now + timedelta(hours=8)) is not None
    assert ts.load_session(now=now + timedelta(hours=10)) is None  # after midnight IST


def test_group_readable_file_refused_and_clear():
    ts.save_session("j", "r", "f")
    os.chmod(ts.session_dir() / "angel_session.json", 0o644)
    assert ts.load_session() is None
    ts.clear_session()
    ts.clear_session()  # idempotent


def test_missing_or_corrupt_is_none():
    assert ts.load_session() is None
    ts.save_session("j", "r", "f")
    (ts.session_dir() / "angel_session.json").write_text("{not json")
    assert ts.load_session() is None
