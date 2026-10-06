"""Annual statements from Yahoo for the quality measures the quick `.info` snapshot cannot give: total assets, operating cash flow, capex, net income.

Everything is taken from ONE fiscal year's statements (the same period end) so accruals, cash profitability and free-cash-flow yield never mix a trailing
figure with an annual one. A figure that is absent is None, never estimated. Pure function over the three statement tables: no network here."""

from datetime import date, timedelta

NI_ROWS = ("Net Income Common Stockholders", "Net Income")


def _num(df, row: str, col):
    try:
        v = df.loc[row, col]
    except (KeyError, TypeError, ValueError):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f or f in (float("inf"), float("-inf")) else f


def _first(df, rows: tuple[str, ...], col):
    for r in rows:
        v = _num(df, r, col)
        if v is not None:
            return v
    return None


def annual_from_frames(balance, cashflow, income) -> dict:
    """-> {annual_period_end, total_assets, total_assets_prior, annual_net_income, annual_operating_cash_flow, annual_capex, annual_free_cash_flow}; empty dict if nothing usable.
    The year used is the newest period end present in the balance sheet AND the cash-flow statement AND the income statement."""
    try:
        common = [c for c in balance.columns if c in cashflow.columns and c in income.columns]
    except AttributeError:
        return {}
    if not common:
        return {}
    cols = sorted(common, reverse=True)
    col = cols[0]
    end = col.date() if hasattr(col, "date") else col
    ordered = sorted(balance.columns, reverse=True)
    prior_col = next((c for c in ordered if c < col), None)
    prior_ok = prior_col is not None and 330 <= (end - (prior_col.date() if hasattr(prior_col, "date") else prior_col)).days <= 400
    ocf = _num(cashflow, "Operating Cash Flow", col)
    capex = _num(cashflow, "Capital Expenditure", col)
    fcf = _num(cashflow, "Free Cash Flow", col)
    if fcf is None and ocf is not None and capex is not None:
        fcf = ocf + capex if capex <= 0 else ocf - capex      # Yahoo reports capex as a negative outflow; a positive figure is treated as the outflow's size
    out = {"annual_period_end": end, "total_assets": _num(balance, "Total Assets", col), "total_assets_prior": _num(balance, "Total Assets", prior_col) if prior_ok else None,
           "annual_net_income": _first(income, NI_ROWS, col), "annual_operating_cash_flow": ocf, "annual_capex": capex, "annual_free_cash_flow": fcf}
    return out if any(v is not None for k, v in out.items() if k != "annual_period_end") else {}


def stale_for(end: date | None, today: date, months: int = 18) -> bool:
    return end is None or (today - end) > timedelta(days=int(months * 30.5))
