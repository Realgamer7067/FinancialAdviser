"""Redacted, hand-built SmartAPI response shapes (from the public docs, NOT a
live capture). Values are synthetic. Replace/extend with redacted live shapes
after the live spike."""

import httpx

RELIANCE_ISIN = "INE002A01018"
TCS_ISIN = "INE467B01029"


def holding(**kw):
    base = {"tradingsymbol": "RELIANCE-EQ", "exchange": "NSE", "isin": RELIANCE_ISIN, "t1quantity": 0,
            "realisedquantity": 10, "quantity": 10, "averageprice": 2000.5, "ltp": 2500.25,
            "symboltoken": "2885", "product": "DELIVERY", "profitandloss": 4997.5}
    base.update(kw)
    return base


def holdings_payload(rows=None, total=25002.5):
    rows = [holding()] if rows is None else rows
    data = {"holdings": rows}
    if total is not None:
        data["totalholding"] = {"totalholdingvalue": total, "totalinvvalue": 20005, "totalprofitandloss": 4997.5}
    return {"status": True, "message": "SUCCESS", "errorcode": "", "data": data}


def ok(data):
    return {"status": True, "message": "SUCCESS", "errorcode": "", "data": data}


def transport(routes, calls=None):
    """routes: {path-suffix: dict | callable(request)->httpx.Response}"""
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append((request.method, request.url.path))
        for suffix, resp in routes.items():
            if request.url.path.endswith(suffix):
                if callable(resp):
                    return resp(request)
                return httpx.Response(200, json=resp)
        return httpx.Response(404, json={"status": False, "message": "no route", "errorcode": "X"})
    return httpx.MockTransport(handler)
