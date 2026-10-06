# Momentum selection vs a liquidity ordering (chronological, cost-aware) - 2026-10-02

Script: `backend/scripts/compare_momentum_selection.py` (run from `backend/`: `python -m scripts.compare_momentum_selection`); raw numbers in `momentum-comparison.json`.

Setup: 47 month-end dates from 2022-10-31 to 2026-08-31, about 614 eligible stocks per date (697 stocks in the panel, total return with 3,755 dividends applied). Each date: equal-weighted top 10 among stocks with 253 sessions of history and median 20-day traded value of at least Rs 1 crore at that date. Entry the close after the date, exit 21 sessions later. Cost 0.3% on every rupee bought and sold at each rebalance.

| Selection | Net mean per month | Net excess over the equal-weighted universe | 95% interval | Months beating it |
|---|---|---|---|---|
| Momentum component (12-1 and 6-1 on total return, one vote) | +3.58% | +1.38% | -0.22% to +3.03% | 29 of 47 |
| Pure liquidity ordering (10 most traded, proxy for the old selection) | +0.12% | -2.09% | -3.09% to -1.04% | 12 of 47 |
| Equal-weighted universe | +2.21% | | | |

Momentum minus liquidity: +3.47% a month, interval +1.42% to +5.51%.

Reading it: the momentum ranking did better than a plain liquidity ordering, and that gap is distinguishable from zero here. Against the whole market its excess is positive but its interval includes zero, so it is not shown to beat simply holding the universe. Turnover was 47% a month for momentum, which the 0.3% side cost already charges.

What this does NOT show: value and quality cannot be tested (no point-in-time fundamentals exist in this project), so the three-component composite is untested. Survivorship (today's listed stocks only) flatters momentum, the history is about five years of one market regime, and the baseline is a proxy for the old rule (which picked the most traded Nifty 50 stock per sector), not the identical rule.
