"""FundamentalDataProvider implementation (Section 8).

Backed by Yahoo Finance (`yfinance`) for the curated Nifty50 seed universe --
a free, ungated, widely-used real-data source (ticker `<SYMBOL>.NS`). It is
explicitly a provisional MVP choice, not a production commitment: Yahoo's
endpoints are unofficial/rate-limited and unsuitable for a licensed advisory
product. Swap in a paid provider (Screener.in API, Tijori, etc.) behind this
same interface before any production use (Section 66).

Every field the upstream API doesn't return is left as `None` ("UNKNOWN"),
never estimated (Section 8 hard rule).
"""

import asyncio
from datetime import date, datetime, timezone

import yfinance as yf

from app.providers.base import FundamentalDataProvider, FundamentalSnapshot
from app.providers.nifty50_seed import NIFTY50_SEED

_SOURCE = "yfinance_nifty50_seed"


def _safe_ratio(info: dict, key: str) -> float | None:
    value = info.get(key)
    return float(value) if isinstance(value, (int, float)) else None


class YFinanceFundamentalProvider(FundamentalDataProvider):
    def __init__(self):
        self._by_symbol = {s.symbol: s for s in NIFTY50_SEED}

    async def get_universe(self) -> list[str]:
        return list(self._by_symbol.keys())

    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot | None:
        seed = self._by_symbol.get(symbol)
        if seed is None:
            return None
        # yfinance is synchronous/blocking -- run off the event loop.
        info = await asyncio.to_thread(self._fetch_info, seed.yfinance_ticker)
        if not info:
            return None

        revenue = _safe_ratio(info, "totalRevenue")
        return FundamentalSnapshot(
            symbol=symbol,
            as_of_date=date.today(),
            revenue=revenue,
            revenue_growth=_safe_ratio(info, "revenueGrowth"),
            ebitda=_safe_ratio(info, "ebitda"),
            ebitda_margin=_safe_ratio(info, "ebitdaMargins"),
            ebit=None,  # not directly exposed by yfinance `info`
            pat=_safe_ratio(info, "netIncomeToCommon"),
            eps=_safe_ratio(info, "trailingEps"),
            eps_growth=_safe_ratio(info, "earningsGrowth"),
            operating_cash_flow=_safe_ratio(info, "operatingCashflow"),
            free_cash_flow=_safe_ratio(info, "freeCashflow"),
            total_debt=_safe_ratio(info, "totalDebt"),
            debt_to_equity=_safe_ratio(info, "debtToEquity"),
            interest_coverage=None,  # not exposed by yfinance `info`
            roe=_safe_ratio(info, "returnOnEquity"),
            roce=None,  # not exposed by yfinance `info`
            operating_margin=_safe_ratio(info, "operatingMargins"),
            net_margin=_safe_ratio(info, "profitMargins"),
            pe=_safe_ratio(info, "trailingPE"),
            forward_pe=_safe_ratio(info, "forwardPE"),
            pb=_safe_ratio(info, "priceToBook"),
            ev_ebitda=_safe_ratio(info, "enterpriseToEbitda"),
            dividend_yield=_safe_ratio(info, "dividendYield"),
            promoter_holding=_safe_ratio(info, "heldPercentInsiders"),
            promoter_pledging=None,  # not available from this source
            institutional_ownership=_safe_ratio(info, "heldPercentInstitutions"),
            market_cap=_safe_ratio(info, "marketCap"),
            source=_SOURCE,
            retrieved_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _fetch_info(ticker: str) -> dict:
        try:
            return yf.Ticker(ticker).info or {}
        except Exception:
            return {}
