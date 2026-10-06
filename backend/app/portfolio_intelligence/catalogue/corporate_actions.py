"""NSE corporate actions: subject-text parsing and split/bonus price adjustment.

Angel's daily candles are unadjusted, so risk maths (volatility, drawdown, trend) on raw history would
read a 1:1 bonus as a 50% crash. We keep the raw candles and adjust at read time from this table.

Only what can be derived mechanically is derived:
- bonus a:b           -> prices before ex-date are multiplied by b/(a+b)
- face-value split    -> prices before ex-date are multiplied by new/old face value
- dividend            -> amount kept (for yield); no price factor, because it needs the prior close
- rights, demerger, scheme of arrangement, anything unparseable -> `needs_review`, factor left null.
Guessing a rights/demerger adjustment would silently corrupt history, so the caller must treat a
`needs_review` event inside a lookback window as "history around this date is unreliable"."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

_AMOUNT = re.compile(r"(?:\bRs\.?|\bRe\.?|₹)\s*(\d+(?:\.\d+)?)", re.I)
_BONUS = re.compile(r"^bonus\s+(\d+)\s*:\s*(\d+)$", re.I)
_SPLIT = re.compile(r"face value (?:split|consolidation).*?from\s+r[a-z.]*\s*(\d+(?:\.\d+)?)\s*/?-?\s*per share\s+to\s+r[a-z.]*\s*(\d+(?:\.\d+)?)", re.I)
_RIGHTS = re.compile(r"^rights\s+(\d+)\s*:\s*(\d+)", re.I)


def normalize_subject(subject: str) -> str:
    return " ".join((subject or "").split())


def parse_subject(subject: str) -> dict:
    """-> {kind, ratio_num, ratio_den, amount, price_factor, needs_review}. Never raises."""
    s = normalize_subject(subject)
    out = {"kind": "other", "ratio_num": None, "ratio_den": None, "amount": None, "price_factor": None, "needs_review": True}
    try:
        if m := _BONUS.match(s):
            a, b = Decimal(m.group(1)), Decimal(m.group(2))
            if a > 0 and b > 0:
                out.update(kind="bonus", ratio_num=a, ratio_den=b, price_factor=b / (a + b), needs_review=False)
            return out
        if m := _SPLIT.search(s):
            old, new = Decimal(m.group(1)), Decimal(m.group(2))
            if old > 0 and new > 0 and old != new:
                out.update(kind="split", ratio_num=new, ratio_den=old, price_factor=new / old, needs_review=False)
            return out
        low = s.lower()
        if m := _RIGHTS.match(s):
            out.update(kind="rights", ratio_num=Decimal(m.group(1)), ratio_den=Decimal(m.group(2)))
            return out
        if low.startswith("rights"):
            out["kind"] = "rights"
            return out
        if "demerger" in low:
            out["kind"] = "demerger"
            return out
        if re.search(r"buy\s*-?\s*back", low):
            out.update(kind="buyback", needs_review=False)  # no price effect at the ex-date
            return out
        if any(w in low for w in ("scheme of arrangement", "amalgamation", "merger", "capital reduction")):
            return out
        if re.search(r"general meeting", low) and "dividend" not in low:
            out.update(kind="meeting", needs_review=False)  # AGM/EGM notice: no price effect
            return out
        if low.startswith(("interest", "distribution", "redemption")):
            out["needs_review"] = False  # debt/InvIT/REIT payments: no equity price adjustment
            return out
        if "dividend" in low:
            out["kind"] = "dividend"
            amounts = [Decimal(x) for x in _AMOUNT.findall(s)]
            per_share = len(re.findall(r"per (?:equity )?share", low))
            # One amount, or several payments each stated "per share" (final + special): their sum is the cash per share.
            if amounts and all(a > 0 for a in amounts) and (len(amounts) == 1 or len(amounts) == per_share):
                out.update(amount=sum(amounts), needs_review=False)
            return out
    except (InvalidOperation, ZeroDivisionError):
        pass
    return out


def parse_nse_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def normalize_records(records: Iterable[dict]) -> list[dict]:
    """NSE JSON rows -> unique event dicts keyed (symbol, ex_date, subject). Rows with no usable ex-date,
    symbol or subject are dropped; the first of any exact duplicate wins."""
    out, seen = [], set()
    for r in records:
        if not isinstance(r, dict):
            continue
        symbol, ex = str(r.get("symbol") or "").strip(), parse_nse_date(r.get("exDate"))
        subject = normalize_subject(str(r.get("subject") or ""))
        if not symbol or ex is None or not subject or (symbol, ex, subject) in seen:
            continue
        seen.add((symbol, ex, subject))
        isin = str(r.get("isin") or "").strip().upper() or None
        out.append({"symbol": symbol, "isin": isin, "ex_date": ex, "subject": subject, **parse_subject(subject)})
    return out


def cumulative_price_factor(actions: Iterable[dict], price_date: date, as_of: date | None = None) -> Decimal:
    """Multiplier to bring a price observed on `price_date` onto today's share basis: the product of every
    split/bonus factor whose ex-date is after `price_date` (and not after `as_of`). Dividends/needs-review
    events contribute nothing (factor is null)."""
    f = Decimal(1)
    for a in actions:
        factor = a.get("price_factor")
        if factor is None or a["ex_date"] <= price_date or (as_of is not None and a["ex_date"] > as_of):
            continue
        f *= Decimal(factor)
    return f


def adjust_closes(closes: list[tuple[date, Decimal]], actions: list[dict]) -> list[tuple[date, Decimal]]:
    return [(d, c * cumulative_price_factor(actions, d)) for d, c in closes]


def review_events_between(actions: Iterable[dict], start: date, end: date) -> list[dict]:
    """Events inside the window that could not be adjusted mechanically: the caller should flag history as unreliable."""
    return [a for a in actions if a.get("needs_review") and start <= a["ex_date"] <= end]
