"""Total-return series: split/bonus-adjusted price plus cash dividends, reinvested at the ex-date close.

WHY it is needed and HOW it was verified (not assumed): Angel's candles are split/bonus-adjusted but NOT dividend-adjusted. On 3,669 NSE
dividend events (2022-2026), the ex-day price drop (market-neutral) is proportional to the dividend: with dividend amounts scaled to today's
share terms, the drop captures about 0.6 of the dividend at 1-2% yields, 0.8 at 2-5% and 0.7 at 5-25%, and the largest events (ASTERDM, PTC,
HINDZINC, HUDCO) show about 1.0. Had the source adjusted for dividends the capture would be near 0.

SCALING: NSE quotes a dividend per share at the time; prices are in today's share terms. So each dividend is multiplied by the product of the
price factors of every LATER split/bonus event (a Rs 10 dividend before a 1:1 bonus is Rs 5 in today's shares). Without this the 533 events
with a later split/bonus were overstated about 2x and the capture looked like 0.37-0.6 instead of 0.7-0.8.

NOT GUESSED: a dividend whose subject text could not be parsed to a single amount (`needs_review`), or whose scaling depends on a later
split/bonus that is `indeterminate`, `unclear`, `conflict` or has no data, is SKIPPED and counted, never approximated."""

from datetime import date
from decimal import Decimal

from app.portfolio_intelligence.market import adjust as adjust_mod

UNSURE = {"indeterminate", "unclear", "conflict", "no_data"}
TR_METHOD = "total-return-v1"


def scale_dividends(dividends: list[dict], audit: list[dict], first: date, last: date) -> tuple[list[dict], dict]:
    """dividends: {ex_date, amount, needs_review}. audit: adjust_mod.audit_events output. -> (scaled [{ex_date, amount}], skipped counts)."""
    skipped = {"needs_review": 0, "uncertain_scaling": 0, "outside_range": 0}
    out = []
    for d in dividends:
        if d.get("needs_review") or d.get("amount") is None:
            skipped["needs_review"] += 1            # an unparseable or ambiguous dividend is REPORTED, never silently dropped
            continue
        if not (first < d["ex_date"] <= last):
            skipped["outside_range"] += 1
            continue
        later = [a for a in audit if a["ex_date"] > d["ex_date"]]
        if any(a["status"] in UNSURE for a in later):
            skipped["uncertain_scaling"] += 1
            continue
        scale = Decimal(1)
        for a in later:
            if a["status"] in ("adjusted", "raw"):
                scale *= a["factor"]          # 'outside' (a future ex-date the data does not reach yet) is not applied: prices are not adjusted for it either
        out.append({"ex_date": d["ex_date"], "amount": Decimal(d["amount"]) * scale})
    return out, skipped


def build_tr(dates: list[date], closes: list[Decimal], scaled: list[dict]) -> list[Decimal]:
    """tr[0] = close[0]; each later day compounds by (close + dividend on that day) / previous close. A dividend whose ex-date is not a stored
    trading date is applied on the first stored date on or after it."""
    by_day: dict[int, Decimal] = {}
    for d in scaled:
        i = next((k for k, x in enumerate(dates) if x >= d["ex_date"]), None)
        if i is not None and i > 0:
            by_day[i] = by_day.get(i, Decimal(0)) + d["amount"]
    tr = [closes[0]]
    for i in range(1, len(closes)):
        tr.append(tr[-1] * (closes[i] + by_day.get(i, Decimal(0))) / closes[i - 1])
    return tr


def prepare(rows: list[dict], events: list[dict]) -> dict:
    """rows: ascending candle dicts (trade_date, open, high, low, close, volume). events: {ex_date, kind, price_factor, needs_review, amount}.
    -> {rows (split/bonus-adjusted), tr (list of Decimal), applied, skipped, audit}."""
    if not rows:
        return {"rows": [], "tr": [], "applied": 0, "skipped": {}, "audit": []}
    price_events = [e for e in events if e.get("price_factor") is not None or e.get("needs_review")]
    adj = adjust_mod.adjust_series(rows, price_events) if price_events else {"rows": rows, "audit": [], "applied": 0, "unreliable": []}
    r = adj["rows"]
    dates = [x["trade_date"] for x in r]
    divs = [e for e in events if e["kind"] == "dividend"]
    scaled, skipped = scale_dividends(divs, adj["audit"], dates[0], dates[-1])
    return {"rows": r, "tr": build_tr(dates, [x["close"] for x in r], scaled), "applied": len(scaled), "scaled": scaled, "skipped": skipped, "audit": adj["audit"], "method": TR_METHOD}
