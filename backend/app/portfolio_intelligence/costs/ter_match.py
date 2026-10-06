"""Join AMFI TER schemes to catalogue securities WITHOUT guessing.

Rules (a match that cannot be defended is a non-match):
- the fund house must be the same (normalized);
- the scheme name must be equal after normalization (lower case, punctuation, parenthetical "erstwhile" names, plan/option and filler words removed),
  compared as a SET of words so word order cannot hide a difference;
- if two TER schemes share a key in one fund house, that key is ambiguous and matches nothing;
- segregated portfolios never match;
- a mutual fund takes the Direct or Regular ratio according to its own plan;
- an exchange-traded fund has ONE ratio, which AMFI files in the Regular column for some fund houses and in the Direct column for others (the
  other column reads 0). The ETF takes its single non-zero value; two different non-zero values are a contradiction and match nothing. An ETF is
  reached through the AMFI NAV row that carries its ISIN, and an ETF-category scheme found by name is treated the same way;
- a ratio of exactly 0 means "not applicable" in AMFI's file, never a free fund: it is unknown. A ratio above MAX_PLAUSIBLE_TER (SEBI's caps plus
  statutory levies stay well under it) is a data error: unknown. A fund whose Direct ratio exceeds its Regular ratio is contradictory: unknown.
Names that are merely similar are NOT matched; the unmatched remainder is reported."""

import re
from collections import defaultdict

_NOISE = {"fund", "scheme", "plan", "direct", "regular", "growth", "option", "idcw", "dividend", "payout", "reinvestment", "reinvest", "of", "the", "and", "a", "mutual", "ltd", "limited"}
_AMC_NOISE = {"mutual", "fund", "ltd", "limited", "asset", "management", "company", "amc", "india", "pvt", "private"}


def _tokens(text: str) -> list[str]:
    t = re.sub(r"\([^)]*\)", " ", text.lower().replace("&", " and "))
    return [w for w in re.sub(r"[^a-z0-9]+", " ", t).split() if w]


def scheme_key(name: str) -> frozenset[str] | None:
    if re.search(r"segregat", name, re.I):
        return None
    toks = [w for w in _tokens(name) if w not in _NOISE]
    return frozenset(toks) if toks else None


def amc_key(name: str | None) -> str | None:
    if not name:
        return None
    toks = [w for w in _tokens(name) if w not in _AMC_NOISE]
    return " ".join(sorted(toks)) or None


MAX_PLAUSIBLE_TER = 4.0     # percent a year: equity-oriented regular plans are capped near 2.25-2.5% by SEBI, plus a few tenths for levies; above this is a data error


def _is_etf_category(category: str | None) -> bool:
    c = (category or "").lower()
    return "etf" in c or "exchange traded" in c


def _etf_value(row: dict) -> float | None:
    vals = [v for v in (row.get("regular_ter"), row.get("direct_ter")) if v is not None and v > 0]
    if not vals or (len(vals) == 2 and abs(vals[0] - vals[1]) > 1e-9):
        return None
    return vals[0]


def _plausible(v: float | None) -> float | None:
    return v if v is not None and 0 < v <= MAX_PLAUSIBLE_TER else None


def build_index(ter_rows: list[dict], amc_names: dict[int, str]) -> tuple[dict, dict]:
    """-> ({(amc_key, scheme_key): ter_row}, stats). Keys that occur more than once are dropped as ambiguous."""
    seen: dict[tuple, list[dict]] = defaultdict(list)
    skipped = 0
    for r in ter_rows:
        k = (amc_key(amc_names.get(r["mf_id"])), scheme_key(r["scheme_name"]))
        if k[0] is None or k[1] is None:
            skipped += 1
            continue
        seen[k].append(r)
    index = {k: v[0] for k, v in seen.items() if len(v) == 1}
    return index, {"ter_schemes": len(ter_rows), "indexed": len(index), "ambiguous_keys": sum(1 for v in seen.values() if len(v) > 1), "unkeyable": skipped}


def match_security(sec: dict, index: dict, *, nav_row_by_isin: dict[str, dict] | None = None) -> dict | None:
    """sec: {kind, name, amc, plan, isin}. -> {ter_row, ter, plan_used, matched_via} or None."""
    if sec["kind"] == "mutual_fund":
        row = index.get((amc_key(sec.get("amc")), scheme_key(sec["name"])))
        if row is None:
            return None
        if _is_etf_category(row.get("category")):                    # an ETF listed among the funds: its single ratio, whichever column holds it
            ter = _plausible(_etf_value(row))
            return None if ter is None else {"ter_row": row, "ter": ter, "plan_used": "etf", "matched_via": "name_in_fund_house_etf"}
        if sec.get("plan") not in ("direct", "regular"):
            return None
        reg, dr = row.get("regular_ter"), row.get("direct_ter")
        if reg is not None and dr is not None and dr > reg:
            return None                                              # contradictory: a Direct plan cannot cost more than its Regular plan
        ter = _plausible(dr if sec["plan"] == "direct" else reg)
        return None if ter is None else {"ter_row": row, "ter": ter, "plan_used": sec["plan"], "matched_via": "name_in_fund_house"}
    if sec["kind"] == "etf":
        nav = (nav_row_by_isin or {}).get((sec.get("isin") or "").upper())
        if nav is None:
            return None
        row = index.get((amc_key(nav.get("amc")), scheme_key(nav["name"])))
        ter = _plausible(_etf_value(row)) if row is not None else None
        return None if ter is None else {"ter_row": row, "ter": ter, "plan_used": "etf", "matched_via": "etf_isin_to_amfi_scheme_then_name"}
    return None
