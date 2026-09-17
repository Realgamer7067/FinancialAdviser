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
import logging
from datetime import date, datetime, timezone

import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from app.providers.base import FundamentalDataProvider, FundamentalSnapshot
from app.providers.nifty50_seed import NIFTY50_SEED

_SOURCE = "yfinance_nifty50_seed"
logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def _fetch_info_raw(ticker: str) -> dict:
    return yf.Ticker(ticker).info or {}


def _safe_ratio(info: dict, key: str) -> float | None:
    value = info.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _safe_debt_to_equity(info: dict) -> float | None:
    """yfinance's `debtToEquity` is the one ratio-shaped field it returns
    already multiplied by 100 (e.g. 100.415 for an actual 1.0x ratio) --
    every other fractional field here (`revenueGrowth`, `returnOnEquity`,
    `profitMargins`, ...) yfinance returns as a true 0-1-ish fraction, and
    every consumer of this field (screening.yaml's `max_debt_to_equity`,
    scoring.yaml's `debt_to_equity_bands`) is written assuming a plain
    ratio, not a percentage. Left unconverted, this silently excluded
    almost every real company from screening (found 2026-09-16 testing
    against restored real data: every non-financial symbol with a real
    debt_to_equity value failed `max_debt_to_equity: 3.0` outright, while
    financial-sector tickers only "passed" because yfinance doesn't
    populate `debtToEquity` for them at all -- null skips the check,
    not a real pass)."""
    value = _safe_ratio(info, "debtToEquity")
    return value / 100.0 if value is not None else None


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
        # `mostRecentQuarter` (epoch seconds) is the actual fiscal period end
        # yfinance reports the `.info` figures against, when present. Falling
        # back to today's date used to be presented as if it were the
        # reporting period -- it's really just "when we fetched this",
        # a materially different claim (docs/V2-RETHINK.md P1).
        most_recent_quarter = info.get("mostRecentQuarter")
        as_of_date = (
            datetime.fromtimestamp(most_recent_quarter, tz=timezone.utc).date()
            if isinstance(most_recent_quarter, (int, float))
            else date.today()
        )
        return FundamentalSnapshot(
            symbol=symbol,
            as_of_date=as_of_date,
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
            debt_to_equity=_safe_debt_to_equity(info),
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
            insider_holding_pct=_safe_ratio(info, "heldPercentInsiders"),
            promoter_holding=None,  # true NSE promoter-holding % not available from this source
            promoter_pledging=None,  # not available from this source
            institutional_ownership=_safe_ratio(info, "heldPercentInstitutions"),
            market_cap=_safe_ratio(info, "marketCap"),
            source=_SOURCE,
            retrieved_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _fetch_info(ticker: str) -> dict:
        # Retried transiently above (rate-limit blocks/timeouts are common and
        # transient on yfinance's unofficial endpoint). If it still fails after
        # retries, log it distinctly from "ticker has no data" -- a silent
        # `except: return {}` here would make rate-limit exhaustion
        # indistinguishable from a genuinely missing ticker.
        try:
            return _fetch_info_raw(ticker)
        except Exception as exc:
            logger.warning("yfinance fundamentals fetch failed for %s after retries: %s", ticker, exc)
            return {}
