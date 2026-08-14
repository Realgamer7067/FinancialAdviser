"""Curated Nifty50 seed universe (Section 15/Section 5 note in the build plan).

This is a hand-picked subset (not the full 50) of large, unambiguous constituents
whose ISIN/instrument identity is well-established public information -- kept
deliberately small rather than guessing ISINs for names we're not certain of,
per the "never invent data" hard rule (Section 43).

Replace/extend this with a sync against Upstox's official instrument master
(https://upstox.com/developer/api-documentation/instruments/ -- verify the exact
download URL at implementation time, it was not confirmed during this build) via
`scripts/sync_instruments.py` before treating this as a production universe.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedInstrument:
    symbol: str
    name: str
    isin: str
    sector: str

    @property
    def instrument_key(self) -> str:
        # Upstox equity instrument_key convention: "NSE_EQ|<ISIN>"
        return f"NSE_EQ|{self.isin}"

    @property
    def yfinance_ticker(self) -> str:
        return f"{self.symbol}.NS"


NIFTY50_SEED: list[SeedInstrument] = [
    SeedInstrument("RELIANCE", "Reliance Industries", "INE002A01018", "Energy"),
    SeedInstrument("TCS", "Tata Consultancy Services", "INE467B01029", "IT"),
    SeedInstrument("HDFCBANK", "HDFC Bank", "INE040A01034", "Financials"),
    SeedInstrument("ICICIBANK", "ICICI Bank", "INE090A01021", "Financials"),
    SeedInstrument("INFY", "Infosys", "INE009A01021", "IT"),
    SeedInstrument("HINDUNILVR", "Hindustan Unilever", "INE030A01027", "FMCG"),
    SeedInstrument("ITC", "ITC Limited", "INE154A01025", "FMCG"),
    SeedInstrument("SBIN", "State Bank of India", "INE062A01020", "Financials"),
    SeedInstrument("BHARTIARTL", "Bharti Airtel", "INE397D01024", "Telecom"),
    SeedInstrument("KOTAKBANK", "Kotak Mahindra Bank", "INE237A01028", "Financials"),
    SeedInstrument("LT", "Larsen & Toubro", "INE018A01030", "Industrials"),
    SeedInstrument("AXISBANK", "Axis Bank", "INE238A01034", "Financials"),
    SeedInstrument("ASIANPAINT", "Asian Paints", "INE021A01026", "Consumer Durables"),
    SeedInstrument("MARUTI", "Maruti Suzuki", "INE585B01010", "Automobile"),
    SeedInstrument("SUNPHARMA", "Sun Pharmaceutical", "INE044A01036", "Pharma"),
    SeedInstrument("TITAN", "Titan Company", "INE280A01028", "Consumer Durables"),
    SeedInstrument("ULTRACEMCO", "UltraTech Cement", "INE481G01011", "Cement"),
    SeedInstrument("BAJFINANCE", "Bajaj Finance", "INE296A01024", "Financials"),
    SeedInstrument("WIPRO", "Wipro", "INE075A01022", "IT"),
    SeedInstrument("NESTLEIND", "Nestle India", "INE239A01016", "FMCG"),
]
