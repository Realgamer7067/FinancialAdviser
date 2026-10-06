"""Verify, per corporate-action event, whether a stored price series is already adjusted, and adjust only
what is not.

Why: the source (Angel) delivers split/bonus-adjusted history (checked live: RELIANCE 1:1 bonus 2024-10-28,
KOTAKBANK 5->1 split 2026-01-14, TRENT 1:2 and LICI 1:1 bonuses are all flat across their ex-dates). An
earlier assumption that the candles were raw would have halved them a second time. So nothing is assumed:
for each split/bonus event inside the series the overnight move across the ex-date is compared with the
event's factor. A move near the factor means the series is still raw there (apply it); a move near 1 means the
source already adjusted it (leave it). Small factors (within 15% of 1) cannot be told apart from an ordinary
move, so they are reported as `indeterminate` and never applied. Rights, demergers and schemes of arrangement
are never adjusted; they mark the surrounding dates unreliable."""

import math
from datetime import date
from decimal import Decimal
from typing import Iterable

INDETERMINATE_BAND = Decimal("0.15")  # |factor - 1| below this: the jump is not distinguishable from a normal move
UNCLEAR_LOG_DISTANCE = 0.22           # the move matches neither "raw" nor "adjusted" within ~25% (a -30% day is not a halving)


def _collapse(events: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """One event per (ex_date, kind) for split/bonus. Identical duplicates (the same event re-worded by NSE)
    collapse; same date and kind with DIFFERENT factors is a conflict and is not applied."""
    groups: dict[tuple, list[dict]] = {}
    for e in events:
        if e.get("price_factor") is not None:
            groups.setdefault((e["ex_date"], e["kind"]), []).append(e)
    good, conflicts = [], []
    for (_, _), g in groups.items():
        if len({Decimal(x["price_factor"]) for x in g}) == 1:
            good.append(g[0])
        else:
            conflicts.append(g[0])
    return sorted(good, key=lambda e: e["ex_date"]), conflicts


def audit_events(closes: list[tuple[date, Decimal]], events: Iterable[dict]) -> list[dict]:
    """closes: ascending (date, close). -> one dict per split/bonus event with
    status: raw | adjusted | indeterminate | unclear | conflict | outside | no_data."""
    events = list(events)
    good, conflicts = _collapse(events)
    out = [{"ex_date": c["ex_date"], "kind": c["kind"], "factor": None, "status": "conflict", "ratio": None} for c in conflicts]
    if not closes:
        return out + [{"ex_date": e["ex_date"], "kind": e["kind"], "factor": Decimal(e["price_factor"]), "status": "outside", "ratio": None} for e in good]
    first, last = closes[0][0], closes[-1][0]
    for e in good:
        f, ex = Decimal(e["price_factor"]), e["ex_date"]
        item = {"ex_date": ex, "kind": e["kind"], "factor": f, "ratio": None}
        if ex <= first or ex > last:
            out.append({**item, "status": "outside"})
            continue
        prev = next((c for d, c in reversed(closes) if d < ex), None)
        cur = next((c for d, c in closes if d >= ex), None)
        if not prev or not cur or prev <= 0 or cur <= 0:
            out.append({**item, "status": "no_data"})
            continue
        ratio = cur / prev
        item["ratio"] = ratio
        if abs(f - 1) < INDETERMINATE_BAND:
            out.append({**item, "status": "indeterminate"})
            continue
        d_raw, d_adj = abs(math.log(float(ratio / f))), abs(math.log(float(ratio)))
        if min(d_raw, d_adj) > UNCLEAR_LOG_DISTANCE:
            out.append({**item, "status": "unclear"})
        else:
            out.append({**item, "status": "raw" if d_raw < d_adj else "adjusted"})
    return sorted(out, key=lambda x: x["ex_date"])


def adjust_series(rows: list[dict], events: Iterable[dict]) -> dict:
    """rows: ascending dicts with trade_date, open, high, low, close (Decimals) and anything else (kept).
    -> {rows, audit, applied, unreliable: [{from, to, reason}]}. `unreliable` windows say where a human or a
    later source must be consulted before trusting returns/volatility."""
    events = list(events)
    audit = audit_events([(r["trade_date"], r["close"]) for r in rows], events)
    raw = [a for a in audit if a["status"] == "raw"]
    adjusted = []
    for r in rows:
        f = Decimal(1)
        for a in raw:
            if r["trade_date"] < a["ex_date"]:
                f *= a["factor"]
        adjusted.append({**r, **{k: r[k] * f for k in ("open", "high", "low", "close")}} if f != 1 else dict(r))
    unreliable = []
    for a in audit:
        if a["status"] in ("indeterminate", "unclear", "conflict"):
            unreliable.append({"date": a["ex_date"], "reason": f"{a['kind']} on {a['ex_date']}: {a['status']}"})
    if rows:
        lo, hi = rows[0]["trade_date"], rows[-1]["trade_date"]
        for e in events:
            if e.get("needs_review") and e["kind"] in ("rights", "demerger", "other") and lo <= e["ex_date"] <= hi:
                unreliable.append({"date": e["ex_date"], "reason": f"{e['kind']} on {e['ex_date']} is not adjusted automatically"})
    return {"rows": adjusted, "audit": audit, "applied": len(raw), "unreliable": sorted(unreliable, key=lambda u: u["date"])}
