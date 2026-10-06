"""One identity-resolution function shared by every import source (plan
section 12.1). Pure: callers pass in the candidate instruments.

Order: user-approved instrument -> validated ISIN match -> otherwise the row
stays unresolved/ambiguous. A symbol alone never proves identity."""

import re
import uuid
from dataclasses import dataclass
from typing import Iterable, Protocol

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Asset types where an instrument identity is expected.
IDENTIFIED_ASSET_TYPES = {"listed_equity", "etf", "mutual_fund"}


class InstrumentLike(Protocol):
    id: uuid.UUID
    symbol: str
    isin: str | None


@dataclass(frozen=True)
class Resolution:
    status: str  # "resolved" | "ambiguous" | "unresolved" | "not_applicable"
    instrument_id: uuid.UUID | None = None
    note: str | None = None


def is_valid_isin(isin: str) -> bool:
    """Format plus the ISO 6166 Luhn check digit."""
    if not _ISIN_RE.match(isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(isin[-1])


def resolve_identity(
    *,
    asset_type: str,
    isin: str | None,
    symbol: str | None,
    approved_instrument_id: uuid.UUID | None,
    instruments: Iterable[InstrumentLike],
) -> Resolution:
    if asset_type not in IDENTIFIED_ASSET_TYPES:
        return Resolution("not_applicable")

    instruments = list(instruments)
    known_ids = {i.id for i in instruments}

    if approved_instrument_id is not None:
        if approved_instrument_id in known_ids:
            return Resolution("resolved", approved_instrument_id, "user_approved")
        return Resolution("unresolved", None, "approved_instrument_not_found")

    if isin:
        if not is_valid_isin(isin):
            return Resolution("unresolved", None, "invalid_isin")
        matches = [i for i in instruments if i.isin == isin]
        if len(matches) == 1:
            return Resolution("resolved", matches[0].id, "isin_match")
        if len(matches) > 1:
            return Resolution("ambiguous", None, "multiple_instruments_for_isin")
        if symbol:
            same_symbol = [i for i in instruments if i.symbol.upper() == symbol.upper()]
            if same_symbol and all(i.isin and i.isin != isin for i in same_symbol):
                return Resolution("ambiguous", None, "symbol_matches_instrument_with_different_isin")
        return Resolution("unresolved", None, "isin_not_in_universe")

    if symbol:
        same_symbol = [i for i in instruments if i.symbol.upper() == symbol.upper()]
        if same_symbol:
            # Symbol text alone is not proof; needs an ISIN or user approval.
            return Resolution("ambiguous", None, "symbol_only_match_needs_confirmation")
    return Resolution("unresolved", None, "no_identifier_match")
