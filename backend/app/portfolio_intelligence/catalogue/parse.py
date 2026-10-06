"""Pure parsers for the public reference files behind the securities catalogue.

No I/O, no network: each takes the file's text and returns plain dicts. Tolerant by design: a malformed
row is skipped and counted, never guessed. Source files:
- NSE `EQUITY_L.csv` (listed equities, ISIN + series + face value)
- NSE `eq_etfseclist.csv` (exchange-traded funds with their underlying class)
- NSE Indices `ind_niftytotalmarket_list.csv` (ISIN -> macro sector for ~750 stocks)
- AMFI `NAVAll.txt` (every mutual fund scheme, semicolon-separated, with category/AMC header lines)"""

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.portfolio_intelligence.normalization.identity import is_valid_isin

_AMFI_DATE = "%d-%b-%Y"
_NSE_DATE = ("%d-%b-%Y", "%d-%b-%y")

# NSE ETF list "ETF Underlying" class -> our asset class. Gold and silver get their own class because the
# allocator treats them differently from other commodities; the NSE list calls both "COMMODITY".
_ETF_CLASS = {"EQUITY": "equity", "DEBT": "debt", "COMMODITY": "commodity", "GLOBAL INDICES": "international", "HYBRID": "hybrid"}


def _dec(v) -> Decimal | None:
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _date(v: str, formats) -> date | None:
    if isinstance(formats, str):
        formats = (formats,)
    for f in formats:
        try:
            return datetime.strptime(v.strip(), f).date()
        except ValueError:
            continue
    return None


def _rows(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _isin(v: str | None) -> str | None:
    v = (v or "").strip().upper()
    return v if v and is_valid_isin(v) else None


def parse_equity_l(text: str) -> tuple[list[dict], int]:
    out, bad = [], 0
    for r in _rows(text):
        isin, symbol = _isin(r.get("ISIN NUMBER")), r.get("SYMBOL", "")
        if not isin or not symbol:
            bad += 1
            continue
        lot = _dec(r.get("MARKET LOT"))
        out.append({"kind": "stock", "isin": isin, "symbol": symbol, "name": r.get("NAME OF COMPANY") or symbol, "series": r.get("SERIES") or None,
                    "exchange": "NSE", "lot_size": int(lot) if lot else 1, "face_value": _dec(r.get("FACE VALUE")),
                    "listing_date": _date(r.get("DATE OF LISTING", ""), _NSE_DATE), "asset_class": "equity", "is_active": True, "source": "nse_equity_l"})
    return out, bad


def parse_etf_list(text: str) -> tuple[list[dict], int]:
    out, bad = [], 0
    for r in _rows(text):
        isin, symbol = _isin(r.get("ISINNumber")), r.get("Symbol", "")
        if not isin or not symbol:
            bad += 1
            continue
        underlying_class = (r.get("ETF Underlying") or "").upper()
        asset_class = _ETF_CLASS.get(underlying_class, "other")
        asset_text = (r.get("Underlying Asset") or "").lower()
        if asset_class == "commodity":
            asset_class = "gold" if "gold" in asset_text else "silver" if "silver" in asset_text else "commodity"
        lot = _dec(r.get("MarketLot"))
        out.append({"kind": "etf", "isin": isin, "symbol": symbol, "name": r.get("SecurityName") or symbol, "series": "EQ", "exchange": "NSE",
                    "lot_size": int(lot) if lot else 1, "face_value": _dec(r.get("FaceValue")),
                    "listing_date": _date(r.get("DateofListing", ""), _NSE_DATE), "asset_class": asset_class,
                    "category": r.get("Underlying Asset") or None, "is_active": True, "source": "nse_etf_list"})
    return out, bad


def parse_sector_map(text: str) -> dict[str, str]:
    """ISIN -> NSE Indices macro sector. Rows without a valid ISIN or a sector are ignored."""
    out = {}
    for r in _rows(text):
        isin, sector = _isin(r.get("ISIN Code")), r.get("Industry", "")
        if isin and sector:
            out[isin] = sector
    return out


def _plan_option(name: str, plan: str, option: str) -> tuple[str | None, str | None]:
    """AMFI's Plan/Option columns are blank for older schemes, so fall back to the scheme name. Unknown stays None."""
    p, o = f"{plan} {name}".lower(), f"{option} {name}".lower()
    pl = "direct" if "direct" in p else "regular" if "regular" in p else None
    op = "idcw" if any(w in o for w in ("idcw", "dividend", "payout", "reinvest", "income distribution")) else "growth" if "growth" in o else None
    return pl, op


_ASSET_BY_CATEGORY = (("equity scheme", "equity"), ("debt scheme", "debt"), ("hybrid scheme", "hybrid"),
                      ("solution oriented", "hybrid"), ("other scheme", "other"))


_GOLD, _SILVER = re.compile(r"\bgold\b", re.I), re.compile(r"\bsilver\b", re.I)
_INTL = re.compile(r"\b(nasdaq|s&p 500|us equity|international|global|overseas|world|emerging markets|hang seng|china|japan|europe)\b", re.I)
# Debt/equity hints in the NAME, used only where AMFI's category is too generic to decide (index funds, FoFs, ETFs).
_DEBT_NAME = re.compile(r"\b(gilt|sdl|ibx|g-?sec|bond|treasury|liquid|overnight|money market|target maturity|t-?bill|debt|income|duration|maturity)\b", re.I)
_EQUITY_NAME = re.compile(r"\b(nifty|sensex|equity|midcap|smallcap|large ?cap|flexi|momentum|quality|alpha|low volatility|value|dividend yield|bse|msci|banking|pharma|infra\w*|consumption|manufacturing|multicap|elss|tax saver)\b", re.I)
_GENERIC_CATEGORY = ("index fund", "fund of funds", "fof", "etf", "other scheme")


def _fund_asset_class(category: str, name: str) -> str:
    """AMFI's own category first, then name checks where the category is generic. Word-boundary matches only
    (a bare substring test would call a "Goldman Sachs" index fund gold). Anything still undecidable is
    "other" (shown as unclassified), never guessed."""
    c = category.lower()
    if _GOLD.search(name):
        return "gold"
    if _SILVER.search(name):
        return "silver"
    if _INTL.search(name) and ("equity" in c or any(g in c for g in _GENERIC_CATEGORY)):
        return "international"
    if "hybrid" in c or "solution oriented" in c or "retirement" in c or "children" in c:
        return "hybrid"
    if any(w in c for w in ("debt", "income", "liquid", "gilt", "money market", "overnight")) and "equity" not in c:
        return "debt"
    if "equity" in c or "growth/equity" in c or "elss" in c:
        generic = any(g in c for g in _GENERIC_CATEGORY)
        if not generic:
            return "equity"
        if _DEBT_NAME.search(name):
            return "debt"
        return "equity"
    if any(g in c for g in _GENERIC_CATEGORY):
        if _DEBT_NAME.search(name):
            return "debt"
        if _EQUITY_NAME.search(name):
            return "equity"
    return "other"


def parse_amfi_navall(text: str) -> tuple[list[dict], int, date | None]:
    """Returns (schemes, skipped_rows, newest NAV date in the file). Header lines (no ';') set the current
    category (contains '(') or AMC; data lines have 8 ';' fields starting with a numeric scheme code."""
    out, bad = [], 0
    category = amc = None
    newest: date | None = None
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        if ";" not in line:
            if "(" in line and ")" in line:
                category = line[line.index("(") + 1 : line.rindex(")")].strip()
            else:
                amc = line
            continue
        f = [x.strip() for x in line.split(";")]
        if len(f) != 8 or not f[0].isdigit():
            bad += 1
            continue
        nav, nav_date = _dec(f[6]), _date(f[7], _AMFI_DATE)
        isin1, isin2 = _isin(f[1]), _isin(f[2])
        if nav is None or nav <= 0 or nav_date is None:
            bad += 1  # e.g. "N.A." NAV: the scheme is kept out rather than carrying a made-up price
            continue
        newest = max(newest, nav_date) if newest else nav_date
        plan, option = _plan_option(f[3], f[4], f[5])
        out.append({"kind": "mutual_fund", "scheme_code": f[0], "isin": isin1 or isin2, "isin_reinvest": isin2 if isin1 else None,
                    "name": f[3], "amc": amc, "category": category, "plan": plan, "option": option, "nav": nav, "nav_date": nav_date,
                    "asset_class": _fund_asset_class(category or "", f[3]), "source": "amfi_navall"})
    return out, bad, newest


STALE_NAV_DAYS = 10


def mark_stale_funds(schemes: list[dict], newest: date | None) -> None:
    """A scheme whose NAV stopped updating (matured, merged, closed) is inactive, so it is never suggested."""
    for s in schemes:
        s["is_active"] = bool(newest and s["nav_date"] and (newest - s["nav_date"]).days <= STALE_NAV_DAYS)
