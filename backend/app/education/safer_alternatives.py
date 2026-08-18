"""Static, curated educational content for low-risk-tolerance users
(T-Bills/FDs/debt funds/small-savings schemes). No live data provider exists
or should exist for these instruments (out of scope) -- every return figure
here is a rough historical/typical *range*, explicitly labeled as general
education, never a live quote or personalized recommendation (mirrors the
never-fabricate rule in app/providers/fundamentals.py's module docstring).
Update figures periodically by hand; do not wire this to any pricing API."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SaferAlternative:
    key: str
    name: str
    category: str  # "government_backed" | "bank_deposit" | "mutual_fund" | "small_savings_scheme"
    description: str
    indicative_return_range: str  # qualitative text, never a fake precise number
    liquidity: str
    typical_lock_in: str | None
    risk_note: str
    suited_risk_profiles: tuple[str, ...]  # subset of conservative/moderate/aggressive
    eligibility_note: str | None = None


SAFER_ALTERNATIVES: tuple[SaferAlternative, ...] = (
    SaferAlternative(
        key="tbill",
        name="Treasury Bills (T-Bills)",
        category="government_backed",
        description=(
            "Short-term (91/182/364-day) debt issued by the Government of India, sold at a "
            "discount and redeemed at face value. Backed by sovereign credit."
        ),
        indicative_return_range=(
            "Historically roughly 6-7.5% p.a., moving with RBI policy rates -- verify the "
            "current cut-off yield before investing."
        ),
        liquidity="Held to maturity for best yield; tradable on the secondary market before maturity but with some price risk.",
        typical_lock_in="91 to 364 days",
        risk_note="Sovereign credit risk is effectively nil; the main risk is price movement if sold before maturity.",
        suited_risk_profiles=("conservative", "moderate"),
    ),
    SaferAlternative(
        key="fd",
        name="Bank Fixed Deposits (FD)",
        category="bank_deposit",
        description="Fixed-tenure deposit with a scheduled commercial bank at a locked-in interest rate.",
        indicative_return_range=(
            "Typically around 6-7.5% p.a. for a 1-3 year tenure at most large banks -- rates "
            "vary by bank and tenure."
        ),
        liquidity="Premature withdrawal usually allowed with a penalty (commonly ~0.5-1% interest reduction).",
        typical_lock_in="Flexible: commonly 1-5 years",
        risk_note=(
            "DICGC insurance covers deposits only up to ₹5 lakh per depositor per bank -- "
            "concentration beyond that adds counterparty risk."
        ),
        suited_risk_profiles=("conservative", "moderate"),
    ),
    SaferAlternative(
        key="debt_mf_short_duration",
        name="Short-Duration Debt Mutual Funds",
        category="mutual_fund",
        description="Mutual funds investing in short-maturity government and high-rated corporate bonds.",
        indicative_return_range=(
            "Historically roughly 6-8% p.a. over multi-year periods, but NAV can fluctuate day "
            "to day -- not a guaranteed return."
        ),
        liquidity="High -- typically redeemable within 1-3 business days, subject to exit load in the first few months for some funds.",
        typical_lock_in=None,
        risk_note=(
            "Carries interest-rate risk (NAV falls when rates rise) and some credit risk "
            "depending on the fund's holdings -- not capital-guaranteed like a bank deposit."
        ),
        suited_risk_profiles=("conservative", "moderate"),
    ),
    SaferAlternative(
        key="liquid_fund",
        name="Liquid Mutual Funds",
        category="mutual_fund",
        description=(
            "Mutual funds investing in very short-maturity (up to ~91 days) money-market "
            "instruments -- often used as a parking spot for an emergency fund."
        ),
        indicative_return_range="Historically roughly 5-7% p.a., closely tracking short-term money-market rates.",
        liquidity="Very high -- many funds offer instant/same-day redemption up to a limit.",
        typical_lock_in=None,
        risk_note=(
            "Lowest volatility among mutual fund categories, but still market-linked (not "
            "capital-guaranteed) and not deposit-insured."
        ),
        suited_risk_profiles=("conservative", "moderate", "aggressive"),
    ),
    SaferAlternative(
        key="ppf",
        name="Public Provident Fund (PPF)",
        category="small_savings_scheme",
        description="Government-run, long-term small-savings scheme with tax-free interest and maturity proceeds (EEE tax status).",
        indicative_return_range="Government-notified rate, historically roughly 7-8% p.a., reset quarterly by the Ministry of Finance.",
        liquidity="Low -- 15-year tenure with limited partial withdrawals allowed from year 7 onward.",
        typical_lock_in="15 years (extendable in 5-year blocks)",
        risk_note="Sovereign-backed, effectively no credit risk; the trade-off is a long lock-in and an annual contribution cap.",
        suited_risk_profiles=("conservative",),
    ),
    SaferAlternative(
        key="ssy",
        name="Sukanya Samriddhi Yojana (SSY)",
        category="small_savings_scheme",
        description=(
            "Government small-savings scheme specifically for a girl child's education/marriage "
            "corpus, opened by a parent/guardian."
        ),
        indicative_return_range="Government-notified rate, historically among the higher small-savings rates, roughly 8% p.a., reset quarterly.",
        liquidity="Very low -- matures 21 years from account opening; partial withdrawal allowed after the child turns 18 or completes class 10.",
        typical_lock_in="21 years from account opening",
        risk_note="Sovereign-backed; eligibility is restricted (see note) and lock-in is long.",
        suited_risk_profiles=("conservative",),
        eligibility_note=(
            "Only for a girl child below 10 years of age at account opening; maximum two "
            "accounts per family (exceptions for multiple births)."
        ),
    ),
)


def get_safer_alternatives() -> tuple[SaferAlternative, ...]:
    return SAFER_ALTERNATIVES
