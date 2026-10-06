"""P7 expense ratios: pagination/throttle handling, latest-per-scheme, and strict matching (no guessing)."""

import json
from datetime import date

import httpx
import pytest

from app.portfolio_intelligence.costs import ter_match as M
from app.portfolio_intelligence.costs import ter_source as T


def row(code, name, dt="2026-09-30", r="1.20", d="0.30", cat="Equity Scheme - Large Cap Fund", mf=28):
    return {"NSDLSchemeCode": code, "Scheme_Name": name, "SchemeCat_Desc": cat, "TER_Date": f"{dt}T00:00:00.000Z", "R_TER": r, "D_TER": d, "R_BER": "1.0", "D_BER": "0.2", "MF_ID": mf}


def pages(rows, size=3):
    out = []
    for i in range(0, len(rows), size):
        out.append({"data": rows[i : i + size], "meta": {"page": i // size + 1, "pageSize": size, "total": len(rows), "pageCount": -(-len(rows) // size)}})
    return out


async def nosleep(_):
    return None


# --- source ---------------------------------------------------------------------------------------------------------------------------

async def test_every_page_is_fetched_and_a_truncated_download_is_an_error():
    rows = [row(f"C{i}", f"S{i}") for i in range(8)]
    pg = pages(rows)
    calls = []

    def handler(req):
        p = int(req.url.params["page"])
        calls.append(p)
        return httpx.Response(200, json=pg[p - 1])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        got = await T.fetch_amc_month(c, 28, "09-2026", sleep=nosleep, page_size=3)
    assert len(got) == 8 and calls == [1, 2, 3]
    short = [dict(pg[0]), dict(pg[1])]
    short[1] = {"data": pg[1]["data"][:1], "meta": pg[1]["meta"]}                  # page 2 comes back short while the total says 8

    async def short_handler(req):
        return httpx.Response(200, json=short[int(req.url.params["page"]) - 1] if int(req.url.params["page"]) <= 2 else {"data": [], "meta": pg[0]["meta"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=short[int(r.url.params["page"]) - 1] if int(r.url.params["page"]) <= 2 else {"data": [], "meta": pg[0]["meta"]}))) as c:
        with pytest.raises(T.TerError, match="got"):
            await T.fetch_amc_month(c, 28, "09-2026", sleep=nosleep, page_size=3)


async def test_malformed_json_is_treated_as_throttling_not_as_an_empty_result():
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(200, content=b"<html>slow down</html>")        # HTTP 200 with garbage: AMFI's throttle signature
        return httpx.Response(200, json=pages([row("C1", "S1")], 10)[0])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        got = await T.fetch_amc_month(c, 28, "09-2026", sleep=nosleep)
    assert len(got) == 1 and state["n"] == 3
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"nope"))) as c:
        with pytest.raises(T.TerError, match="malformed JSON"):
            await T.fetch_amc_month(c, 28, "09-2026", sleep=nosleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": "x", "meta": {}}))) as c:
        with pytest.raises(T.TerError, match="unexpected TER response shape"):
            await T.fetch_amc_month(c, 28, "09-2026", sleep=nosleep)


def test_latest_row_per_scheme_and_bad_values():
    rows = [row("A", "UTI - Arbitrage Fund", "2026-09-22", "1.9", "1.3"), row("A", "UTI - Arbitrage Fund", "2026-09-30", "1.8", "1.25"), row("B", "UTI - Bond Fund", "2026-09-30", "N.A.", "-1"),
            {"NSDLSchemeCode": "", "Scheme_Name": "x", "TER_Date": "2026-09-30T00:00:00Z"}, {"NSDLSchemeCode": "Z", "Scheme_Name": "z", "TER_Date": "garbage"}]
    out = {r["nsdl_code"]: r for r in T.latest_per_scheme(rows, 28)}
    assert set(out) == {"A", "B"} and out["A"]["ter_date"] == date(2026, 9, 30) and out["A"]["direct_ter"] == 1.25 and out["A"]["regular_ter"] == 1.8
    assert out["B"]["regular_ter"] is None and out["B"]["direct_ter"] is None                        # unparseable or negative: unknown, never zero


def test_month_helpers():
    assert T.current_month(date(2026, 10, 1)) == "10-2026" and T.previous_month(date(2026, 1, 15)) == "12-2025" and T.previous_month(date(2026, 10, 1)) == "09-2026"


# --- matching -------------------------------------------------------------------------------------------------------------------------------

AMCS = {28: "UTI Mutual Fund", 22: "SBI Mutual Fund", 3: "Aditya Birla Sun Life Mutual Fund"}


def ter(code, name, mf, r, d):
    return {"mf_id": mf, "nsdl_code": code, "scheme_name": name, "category": "x", "ter_date": date(2026, 9, 30), "regular_ter": r, "direct_ter": d, "regular_ber": 0, "direct_ber": 0}


def sec(name, amc, plan="direct", kind="mutual_fund", isin=None):
    return {"kind": kind, "name": name, "amc": amc, "plan": plan, "isin": isin}


def test_normalization_ignores_plan_option_punctuation_and_order_but_not_real_differences():
    k = M.scheme_key
    assert k("UTI - Nifty 50 Index Fund") == k("UTI Nifty 50 Index Fund - Direct Plan - Growth Option") == k("Nifty 50 UTI Index Fund")
    assert k("UTI Nifty 50 Index Fund") != k("UTI Nifty Next 50 Index Fund") and k("UTI Nifty 50 Index Fund") != k("UTI Nifty 500 Index Fund")
    assert k("Axis Large Cap Fund (erstwhile Axis Bluechip Fund)") == k("Axis Large Cap Fund")
    assert k("UTI - Bond Fund ( Segregated - 17022020 )") is None                              # segregated portfolios never match
    assert k("HDFC ELSS Tax Saver") != k("HDFC Tax Saver") and k("") is None
    assert M.amc_key("UTI Mutual Fund") == M.amc_key("UTI Asset Management Company Ltd") == "uti"


def test_matching_is_scoped_to_the_fund_house_and_uses_the_right_plan_column():
    index, st = M.build_index([ter("1", "UTI - Nifty 50 Index Fund", 28, 0.6, 0.2), ter("2", "SBI - Nifty 50 Index Fund", 22, 0.5, 0.18), ter("7", "Nifty Next 50 Index Fund", 28, 0.7, 0.3), ter("8", "Nifty Next 50 Index Fund", 22, 0.75, 0.35)], AMCS)
    assert st["indexed"] == 4 and st["ambiguous_keys"] == 0
    d = M.match_security(sec("UTI Nifty 50 Index Fund", "UTI Mutual Fund", "direct"), index)
    r = M.match_security(sec("UTI Nifty 50 Index Fund", "UTI Mutual Fund", "regular"), index)
    assert d["ter"] == 0.2 and r["ter"] == 0.6 and d["ter_row"]["nsdl_code"] == "1"
    assert M.match_security(sec("Nifty Next 50 Index Fund", "UTI Mutual Fund", "direct"), index)["ter"] == 0.3                # the SAME name in two houses: each gets its own
    assert M.match_security(sec("Nifty Next 50 Index Fund", "SBI Mutual Fund", "direct"), index)["ter"] == 0.35
    assert M.match_security(sec("UTI Nifty 50 Index Fund", "SBI Mutual Fund", "direct"), index) is None                        # the brand is part of the name
    assert M.match_security(sec("UTI Nifty 50 Index Fund", "HDFC Mutual Fund", "direct"), index) is None                       # a house with no such scheme: no match
    assert M.match_security(sec("UTI Nifty 50 Index Fund", "UTI Mutual Fund", None), index) is None                             # unknown plan: no guess


def test_ambiguous_keys_and_lookalikes_match_nothing():
    index, st = M.build_index([ter("1", "UTI - Value Fund", 28, 1.0, 0.5), ter("2", "UTI Value Fund (erstwhile UTI Opportunities)", 28, 1.1, 0.6), ter("3", "UTI - Growth Fund", 28, 1.0, 0.5)], AMCS)
    assert st["ambiguous_keys"] == 1 and st["indexed"] == 1                                                                   # the two "Value Fund" rows collide: neither is used
    assert M.match_security(sec("UTI Value Fund", "UTI Mutual Fund"), index) is None
    assert M.match_security(sec("UTI Growth Opportunities Fund", "UTI Mutual Fund"), index) is None                          # similar is not equal


def test_etfs_are_matched_through_their_amfi_isin_and_take_the_regular_column():
    index, _ = M.build_index([ter("9", "UTI - BSE Sensex Next 50 Exchange Traded Fund", 28, 0.31, 0.0)], AMCS)
    navs = {"INF789FB1R16": {"name": "UTI BSE Sensex Next 50 Exchange Traded Fund", "amc": "UTI Mutual Fund"}}
    m = M.match_security(sec("UTI-SENSEXNXT50", None, None, kind="etf", isin="inf789fb1r16"), index, nav_row_by_isin=navs)
    assert m["ter"] == 0.31 and m["plan_used"] == "etf" and m["matched_via"].startswith("etf_isin")                          # NOT the 0.0 direct column
    assert M.match_security(sec("OTHERETF", None, None, kind="etf", isin="INF000000000"), index, nav_row_by_isin=navs) is None
    assert M.match_security(sec("S", "UTI Mutual Fund", kind="stock"), index) is None


def ter_c(code, name, mf, r, d, cat):
    return {**ter(code, name, mf, r, d), "category": cat}


def test_an_etf_takes_its_single_nonzero_ratio_whichever_column_holds_it():
    rows = [ter_c("1", "HSBC - Gold ETF", 28, 0.0, 0.62, "Other Scheme - Gold ETF"), ter_c("2", "UTI - Sensex ETF", 28, 0.31, 0.0, "Exchange Traded Funds (ETFs) - Equity"),
            ter_c("3", "UTI - Both ETF", 28, 0.4, 0.4, "Exchange Traded Funds (ETFs)"), ter_c("4", "UTI - Clash ETF", 28, 0.4, 0.5, "Exchange Traded Funds (ETFs)"),
            ter_c("5", "UTI - Dead ETF", 28, 0.0, 0.0, "Exchange Traded Funds (ETFs)")]
    index, _ = M.build_index(rows, AMCS)
    navs = {f"INF00000000{i}": {"name": n, "amc": "UTI Mutual Fund"} for i, n in enumerate(["HSBC Gold ETF", "UTI Sensex ETF", "UTI Both ETF", "UTI Clash ETF", "UTI Dead ETF"], 1)}
    got = [M.match_security(sec("E", None, None, kind="etf", isin=i), index, nav_row_by_isin=navs) for i in navs]
    assert [g["ter"] if g else None for g in got] == [0.62, 0.31, 0.4, None, None]                   # Direct-only, Regular-only, equal, contradictory, not applicable
    listed = M.match_security(sec("UTI Sensex ETF", "UTI Mutual Fund", "direct"), index)            # the same ETF reached as a NAV-file "fund" with a plan
    assert listed["ter"] == 0.31 and listed["plan_used"] == "etf"                                      # NOT the 0.0 Direct column


def test_zero_implausible_and_contradictory_ratios_are_unknown_never_shown():
    rows = [ter("1", "UTI - Free Fund", 28, 0.0, 0.0), ter("2", "UTI - Wild Fund", 28, 10.2, 9.4), ter("3", "UTI - Odd Fund", 28, 1.0, 1.4), ter("4", "UTI - Fine Fund", 28, 3.9, 1.1)]
    index, _ = M.build_index(rows, AMCS)
    for name, plan in (("UTI Free Fund", "direct"), ("UTI Wild Fund", "direct"), ("UTI Wild Fund", "regular"), ("UTI Odd Fund", "direct"), ("UTI Odd Fund", "regular")):
        assert M.match_security(sec(name, "UTI Mutual Fund", plan), index) is None, (name, plan)       # 0% is "not applicable"; 10% is a data error; Direct > Regular is contradictory
    assert M.match_security(sec("UTI Fine Fund", "UTI Mutual Fund", "regular"), index)["ter"] == 3.9      # the plausible ceiling is 4%
