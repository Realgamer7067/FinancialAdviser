"""Normalize Angel `getAllHolding` data into import rows plus a reconciliation
against the provider's own aggregate (plan sections 3, 4, 12.4).

Rules that matter:
- `holdings` missing / not a list => BadResponse (a broken response), while
  `holdings: []` is a valid empty account.
- A malformed row is quarantined, never silently dropped or repaired; any
  quarantined row makes the batch `partial`.
- T1 quantity is stored verbatim in source_meta and NOT added to units; its
  semantics are unverified until checked against a real response.
- No cost basis is synthesized; provider averageprice stays in source_meta.
- Value = units x provider LTP, dated with the retrieval date (the payload has
  no exchange timestamp), and labelled as such in source_meta."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.portfolio_intelligence.normalization.identity import is_valid_isin
from app.portfolio_intelligence.sources.angel.errors import BadResponse
from app.portfolio_intelligence.sources.angel.token_store import IST
from app.portfolio_intelligence.sources.import_rows import ImportRow

RECON_TOLERANCE = Decimal("0.01")  # 1% relative gap between computed and provider total
_PAISE = Decimal("0.01")


@dataclass
class ParsedHoldings:
    rows: list[ImportRow] = field(default_factory=list)
    metas: list[dict] = field(default_factory=list)  # parallel to rows
    quarantined: list[dict] = field(default_factory=list)  # {"ordinal", "reasons"}
    provider_total: Decimal | None = None
    provider_total_pnl: Decimal | None = None
    reconciliation: dict = field(default_factory=dict)
    status: str = "complete"  # "complete" | "partial"


def _dec(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def parse_holdings(data: dict, retrieved_at: datetime) -> ParsedHoldings:
    raw = data.get("holdings")
    if not isinstance(raw, list):
        raise BadResponse("holdings response has no holdings list")

    out = ParsedHoldings()
    valuation_date = retrieved_at.astimezone(IST).date()
    computed = Decimal(0)
    computed_rows = 0

    for i, h in enumerate(raw, start=1):
        reasons: list[str] = []
        if not isinstance(h, dict):
            out.quarantined.append({"ordinal": i, "reasons": ["row is not an object"]})
            continue
        symbol = h.get("tradingsymbol")
        exchange = h.get("exchange")
        isin = h.get("isin")
        qty = _dec(h.get("quantity"))
        ltp = _dec(h.get("ltp"))
        avg = _dec(h.get("averageprice"))
        if not isinstance(symbol, str) or not symbol.strip():
            reasons.append("tradingsymbol missing")
        if not isinstance(exchange, str) or not exchange.strip():
            reasons.append("exchange missing")
        if isin is not None and not (isinstance(isin, str) and is_valid_isin(isin.strip().upper())):
            reasons.append("isin invalid")
        if qty is None or qty <= 0:
            reasons.append("quantity missing or not positive")
        if h.get("ltp") is not None and (ltp is None or ltp < 0):
            reasons.append("ltp invalid")
        if h.get("averageprice") is not None and (avg is None or avg < 0):
            reasons.append("averageprice invalid")
        if reasons:
            out.quarantined.append({"ordinal": i, "reasons": reasons})
            continue

        value = None
        if ltp is not None:
            value = (qty * ltp).quantize(_PAISE, rounding=ROUND_HALF_UP)
            computed += value
            computed_rows += 1
        out.rows.append(
            ImportRow(
                asset_type="listed_equity",
                isin=isin.strip().upper() if isinstance(isin, str) and isin.strip() else None,
                symbol=symbol.strip(),
                description=None,
                units=qty,
                value=value,
                valuation_date=valuation_date,
                cost_basis=None,
                locked=False,
                ownership="sole",
            )
        )
        out.metas.append(
            {
                "provider": "angel_one",
                "exchange": exchange.strip(),
                "symboltoken": None if h.get("symboltoken") is None else str(h.get("symboltoken")),
                "product": h.get("product"),
                "quantity": str(qty),
                "t1quantity": None if _dec(h.get("t1quantity")) is None else str(_dec(h.get("t1quantity"))),
                "realisedquantity": None if _dec(h.get("realisedquantity")) is None else str(_dec(h.get("realisedquantity"))),
                "t1_semantics_unverified": True,
                "provider_averageprice": None if avg is None else str(avg),
                "provider_ltp": None if ltp is None else str(ltp),
                "provider_pnl": None if _dec(h.get("profitandloss")) is None else str(_dec(h.get("profitandloss"))),
                "value_basis": "units x provider_ltp; dated by retrieval time (no exchange timestamp in payload)",
                "asset_class_assumed": "listed_equity",
            }
        )

    total = data.get("totalholding")
    if isinstance(total, dict):
        out.provider_total = _dec(total.get("totalholdingvalue"))
        out.provider_total_pnl = _dec(total.get("totalprofitandloss"))

    recon: dict = {
        "computed_value": str(computed),
        "computed_rows": computed_rows,
        "provider_total": None if out.provider_total is None else str(out.provider_total),
        "tolerance": str(RECON_TOLERANCE),
        "retrieved_at": retrieved_at.isoformat(),
    }
    material = False
    if out.provider_total is not None:
        abs_diff = abs(computed - out.provider_total)
        rel = (abs_diff / out.provider_total) if out.provider_total != 0 else (Decimal(0) if abs_diff == 0 else Decimal(1))
        recon.update(abs_diff=str(abs_diff), rel_diff=str(rel.quantize(Decimal("0.0001"))))
        material = rel > RECON_TOLERANCE
    else:
        recon["note"] = "provider aggregate absent; not reconciled"
    recon["material_gap"] = material
    out.reconciliation = recon
    out.status = "partial" if (out.quarantined or material) else "complete"
    return out
