"""Personal context for a watched stock (facts only, never a recommendation).

Everything is derived from the owner's own snapshot and limits: what they
already hold, how much room is left before THEIR concentration limits, and
whether a confirmed restriction applies. No buy/sell signal, no target price."""

from decimal import Decimal

ZERO = Decimal(0)


def _pct(x: Decimal) -> str:
    return f"{x * 100:.1f}%"


def _money(x: Decimal) -> str:
    return f"₹{x:,.0f}"


def build_context(*, symbol: str, instrument_id: str | None, sector: str | None, isin: str | None, holdings: dict, total: Decimal,
                  sector_values: dict, restrictions: list[dict], thesis: dict | None, limits: dict) -> dict:
    owned_value = holdings.get(instrument_id, {}).get("value", ZERO) if instrument_id else ZERO
    accounts = sorted(holdings.get(instrument_id, {}).get("accounts", [])) if instrument_id else []
    out: dict = {"owned": owned_value > 0, "owned_value": str(owned_value.normalize()) if owned_value else "0", "accounts": accounts,
                 "owned_weight": None, "sector": sector, "sector_weight_now": None, "context_available": instrument_id is not None,
                 "facts": [], "restriction_conflicts": [], "thesis": thesis}
    if instrument_id is None:
        out["facts"].append("This stock is outside the universe we have sector data for, so portfolio context is limited to what you hold.")
        return out
    if total <= 0:
        out["facts"].append("Your portfolio has no valued holdings yet, so there is no concentration to compare against.")
        return out
    w = owned_value / total
    out["owned_weight"] = f"{w:.4f}"
    issuer_limit, sector_limit = limits["max_single_issuer_weight"], limits["max_sector_weight"]
    if owned_value > 0:
        msg = f"You hold {_money(owned_value)} ({_pct(w)} of your known portfolio value) across {', '.join(accounts)}."
        if w > issuer_limit:
            msg += f" That is above your {_pct(issuer_limit)} single-company limit."
        out["facts"].append(msg)
        room = issuer_limit * total - owned_value
        out["issuer_room_rupees"] = str(max(room, ZERO).quantize(Decimal("1")))
    else:
        out["issuer_room_rupees"] = str((issuer_limit * total).quantize(Decimal("1")))
    if sector:
        sv = sector_values.get(sector, ZERO)
        sw = sv / total
        out["sector_weight_now"] = f"{sw:.4f}"
        room_s = sector_limit * total - sv
        out["sector_room_rupees"] = str(max(room_s, ZERO).quantize(Decimal("1")))
        out["facts"].append(f"{sector} is {_pct(sw)} of your known value; there is room for about {_money(max(room_s, ZERO))} more "
                            f"before your {_pct(sector_limit)} sector limit (at today's total).")
    for r in restrictions:
        if (r["kind"] == "exclude_sector" and sector and r["value"].lower() == sector.lower()) or \
           (r["kind"] == "exclude_isin" and isin and r["value"].upper() == isin.upper()):
            out["restriction_conflicts"].append(f"you excluded {r['value']}")
    if out["restriction_conflicts"]:
        out["facts"].append("A restriction you confirmed applies: " + "; ".join(out["restriction_conflicts"]) + ".")
    if thesis:
        out["facts"].append(f"You have a thesis on this stock; its latest assessment is {thesis.get('status') or 'not yet assessed'}.")
    return out
