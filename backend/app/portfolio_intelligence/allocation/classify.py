"""Put each held position into an allocation bucket using the catalogue's asset class, matched by validated ISIN.

Unresolved or mixed positions go to an explicit `unknown` bucket that is never redistributed. Cash (bank balances) is NOT part of
the allocation: it is reported separately. Matching is by ISIN only (symbols never prove identity); funds match on either of
their two AMFI ISINs."""

from collections import defaultdict
from decimal import Decimal

_ZERO = Decimal(0)

# catalogue asset_class -> bucket. Hybrid funds mix classes and cannot be split, so they are unknown, not guessed.
_BY_CATALOGUE = {"equity": "equity_india", "international": "equity_intl", "gold": "gold", "silver": "gold", "commodity": "gold", "debt": "debt", "hybrid": "unknown"}
# user-declared asset type, used only when the catalogue cannot place the holding AND the type is unambiguous
_BY_DECLARED = {"listed_equity": "equity_india", "gold": "gold", "deposit": "debt"}


def classify_positions(positions: list[dict], by_isin: dict[str, dict]) -> dict:
    """positions: engine-style dicts (position_id, asset_type, isin, value, label). by_isin: {ISIN: {asset_class, kind, symbol}}.
    -> {buckets: {bucket: Decimal}, unknown: Decimal, cash: Decimal, rows: [...], unvalued: n}"""
    buckets: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    rows, unknown, cash, unvalued = [], _ZERO, _ZERO, 0
    for p in positions:
        v = p.get("value")
        if v is None:
            unvalued += 1
            rows.append({"position_id": p["position_id"], "label": p.get("label"), "bucket": None, "basis": "unvalued", "value": None})
            continue
        if p["asset_type"] == "cash":
            cash += v
            rows.append({"position_id": p["position_id"], "label": p.get("label"), "bucket": "cash", "basis": "not part of the allocation", "value": v})
            continue
        sec = by_isin.get((p.get("isin") or "").upper()) if p.get("isin") else None
        bucket, basis = None, None
        if sec is not None and sec.get("asset_class") in _BY_CATALOGUE:
            bucket, basis = _BY_CATALOGUE[sec["asset_class"]], "catalogue"
        elif p["asset_type"] in _BY_DECLARED:
            bucket, basis = _BY_DECLARED[p["asset_type"]], "declared"
        if bucket is None or bucket == "unknown":
            unknown += v
            rows.append({"position_id": p["position_id"], "label": p.get("label"), "bucket": "unknown", "basis": basis or "unresolved", "value": v})
        else:
            buckets[bucket] += v
            rows.append({"position_id": p["position_id"], "label": p.get("label"), "bucket": bucket, "basis": basis, "value": v})
    return {"buckets": dict(buckets), "unknown": unknown, "cash": cash, "rows": rows, "unvalued": unvalued}
