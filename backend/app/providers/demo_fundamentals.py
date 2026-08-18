"""Fallback FundamentalDataProvider used in DEMO_MODE (mirrors
demo_market_data.py's rationale) -- synthetic, deterministic per-symbol
fundamentals so the pipeline never has to call Yahoo Finance's fundamentals
endpoint when the operator has explicitly opted into demo mode. Every row is
flagged `source="demo_seed"`, never presented as live filings data."""

import random
from datetime import date, datetime, timezone

from app.providers.base import FundamentalDataProvider, FundamentalSnapshot
from app.providers.nifty50_seed import NIFTY50_SEED

_SOURCE = "demo_seed"


class DemoFundamentalProvider(FundamentalDataProvider):
    def __init__(self):
        self._by_symbol = {s.symbol: s for s in NIFTY50_SEED}

    async def get_universe(self) -> list[str]:
        return list(self._by_symbol.keys())

    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot | None:
        if symbol not in self._by_symbol:
            return None
        rng = random.Random(hash(symbol))
        revenue = rng.uniform(5e9, 5e11)
        eps = rng.uniform(5, 200)
        pe = rng.uniform(8, 60)
        return FundamentalSnapshot(
            symbol=symbol,
            as_of_date=date.today(),
            revenue=revenue,
            revenue_growth=rng.uniform(-0.05, 0.25),
            ebitda=revenue * rng.uniform(0.1, 0.35),
            ebitda_margin=rng.uniform(0.1, 0.35),
            ebit=None,
            pat=revenue * rng.uniform(0.05, 0.2),
            eps=eps,
            eps_growth=rng.uniform(-0.1, 0.3),
            operating_cash_flow=revenue * rng.uniform(0.08, 0.25),
            free_cash_flow=revenue * rng.uniform(0.02, 0.15),
            total_debt=revenue * rng.uniform(0.0, 0.6),
            debt_to_equity=rng.uniform(0.0, 1.5),
            interest_coverage=None,
            roe=rng.uniform(0.05, 0.3),
            roce=None,
            operating_margin=rng.uniform(0.08, 0.3),
            net_margin=rng.uniform(0.03, 0.2),
            pe=pe,
            forward_pe=pe * rng.uniform(0.8, 1.1),
            pb=rng.uniform(1, 12),
            ev_ebitda=rng.uniform(5, 25),
            dividend_yield=rng.uniform(0.0, 0.03),
            promoter_holding=rng.uniform(0.3, 0.75),
            promoter_pledging=None,
            institutional_ownership=rng.uniform(0.1, 0.4),
            market_cap=eps * pe * rng.uniform(5e7, 5e8),
            source=_SOURCE,
            retrieved_at=datetime.now(timezone.utc),
        )
