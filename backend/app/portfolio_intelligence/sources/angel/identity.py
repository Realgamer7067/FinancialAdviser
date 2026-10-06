"""Keyed broker-account fingerprint. A plain hash of a short client code is
brute-forceable, so this is an HMAC under a persistent local key
(ANGEL_FINGERPRINT_KEY). Changing that key makes the same account look new."""

import hashlib
import hmac

from app.core.config import settings
from app.portfolio_intelligence.sources.angel.errors import Unavailable


def fingerprint(client_code: str) -> str:
    key = settings.angel_fingerprint_key
    if not key:
        raise Unavailable("ANGEL_FINGERPRINT_KEY is not configured")
    return hmac.new(key.encode(), client_code.strip().upper().encode(), hashlib.sha256).hexdigest()


def mask(client_code: str) -> str:
    c = client_code.strip()
    return f"{c[:1]}***{c[-2:]}" if len(c) > 3 else "***"
