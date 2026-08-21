"""Pure SIP (systematic investment plan) compound-growth math -- no DB access,
no I/O. Two inverse operations: project where a monthly SIP ends up, or
back-solve the monthly SIP needed to hit a target. Ordinary-annuity convention
(deposit at end of each month), matching how SIP maturity is conventionally
quoted in India."""


def sip_future_value(monthly_amount: float, annual_rate_pct: float, years: int) -> list[dict]:
    """Yearly series of {year, invested_cumulative, projected_value} from
    year 1 through `years`."""
    monthly_rate = annual_rate_pct / 100 / 12
    points = []
    for year in range(1, years + 1):
        months = year * 12
        invested = monthly_amount * months
        if monthly_rate == 0:
            value = invested
        else:
            value = monthly_amount * (((1 + monthly_rate) ** months - 1) / monthly_rate)
        points.append({"year": year, "invested_cumulative": round(invested, 2), "projected_value": round(value, 2)})
    return points


def required_monthly_sip(target_amount: float, annual_rate_pct: float, years: int) -> float:
    """Solves the future-value-of-annuity formula for the monthly payment
    needed to reach `target_amount` in `years` years."""
    monthly_rate = annual_rate_pct / 100 / 12
    months = years * 12
    if monthly_rate == 0:
        return round(target_amount / months, 2)
    return round(target_amount * monthly_rate / ((1 + monthly_rate) ** months - 1), 2)
