"""Sync the Nifty50 seed universe from two live, official sources (Section 66:
verify current docs before implementing -- both URLs below were confirmed
live and cross-checked against each other at build time):

  - NSE's official Nifty50 constituent list (name/symbol/ISIN/sector):
    https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv
  - Upstox's instrument master (symbol -> instrument_key mapping):
    https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz

Writes data/processed/nifty50_instruments.json, which app/providers/nifty50_seed.py
loads at runtime. Re-run this periodically -- NSE rebalances Nifty50 semi-annually
(Jan 31 / Jul 31 cutoffs), so the constituent list drifts over time.

Usage: python scripts/sync_instruments.py
"""

import csv
import gzip
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

NIFTY50_LIST_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
UPSTOX_INSTRUMENT_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "nifty50_instruments.json"

HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_nifty50_constituents() -> list[dict]:
    resp = httpx.get(NIFTY50_LIST_URL, headers=HEADERS, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def fetch_upstox_equity_instruments() -> dict[str, dict]:
    resp = httpx.get(UPSTOX_INSTRUMENT_MASTER_URL, headers=HEADERS, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    data = json.loads(gzip.decompress(resp.content))
    return {
        d["trading_symbol"]: d
        for d in data
        if d.get("segment") == "NSE_EQ" and d.get("instrument_type") == "EQ"
    }


def main() -> None:
    constituents = fetch_nifty50_constituents()
    instruments_by_symbol = fetch_upstox_equity_instruments()

    result = []
    missing = []
    for row in constituents:
        symbol = row["Symbol"].strip()
        instrument = instruments_by_symbol.get(symbol)
        if instrument is None:
            missing.append(symbol)
            continue
        nse_isin = row["ISIN Code"].strip()
        if instrument["isin"] != nse_isin:
            print(f"WARNING: ISIN mismatch for {symbol}: NSE={nse_isin} Upstox={instrument['isin']}", file=sys.stderr)
        result.append(
            {
                "symbol": symbol,
                "name": row["Company Name"].strip(),
                "isin": instrument["isin"],
                "sector": row["Industry"].strip(),
                "instrument_key": instrument["instrument_key"],
            }
        )

    if missing:
        print(f"WARNING: {len(missing)} Nifty50 symbols not found in Upstox instrument master: {missing}", file=sys.stderr)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_nifty50_list": NIFTY50_LIST_URL,
                "source_instrument_master": UPSTOX_INSTRUMENT_MASTER_URL,
                "instruments": result,
            },
            indent=2,
        )
    )
    print(f"Wrote {len(result)} instruments to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
