"""Investable-universe catalogue (Portfolio Intelligence Engine, P0).

`securities` is the single ISIN-keyed spine for everything a user can hold or be
suggested: NSE stocks, exchange-traded funds and mutual fund schemes. It exists
beside the legacy `instruments` table (Nifty-50 only, symbol-unique, referenced
by holdings/twin/theses) rather than replacing it; the 50 Nifty rows link back
through `instrument_id`. Everything here is reference data from public files
(NSE, NSE Indices, AMFI), never user data, and never a recommendation."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class Security(Base, UUIDPKMixin):
    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_securities_source_key"),
        Index("ix_securities_kind_active", "kind", "is_active"),
    )

    # "isin:<ISIN>" for exchange-listed rows, "amfi:<scheme code>" for fund schemes. A fund scheme's ISINs
    # are per share class, so the scheme code (not the ISIN) is its stable identity.
    source_key: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # stock | etf | mutual_fund
    isin: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    isin_reinvest: Mapped[str | None] = mapped_column(String, nullable=True)  # AMFI second ISIN (IDCW reinvestment)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # NSE symbol; null for funds
    name: Mapped[str] = mapped_column(String)
    exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    series: Mapped[str | None] = mapped_column(String, nullable=True)  # EQ | BE | BZ ...
    lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    face_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    listing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Classification. `sector` is the NSE Indices macro sector (stocks only, null = unclassified);
    # `asset_class` is equity | debt | gold | silver | commodity | international | hybrid | other.
    sector: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)  # AMFI category / ETF underlying
    # Fund-only fields.
    scheme_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    amc: Mapped[str | None] = mapped_column(String, nullable=True)
    plan: Mapped[str | None] = mapped_column(String, nullable=True)  # direct | regular | null
    option: Mapped[str | None] = mapped_column(String, nullable=True)  # growth | idcw | null
    nav: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    nav_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=True)
    source: Mapped[str] = mapped_column(String)  # nse_equity_l | nse_etf_list | amfi_navall
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CorporateAction(Base, UUIDPKMixin):
    """Raw NSE corporate action plus what we could mechanically derive. Never rewrites price history:
    `price_factor` is the multiplier to apply to prices BEFORE `ex_date` (bonus a:b -> b/(a+b); split
    from X to Y -> Y/X). Anything that cannot be turned into a factor without judgement (rights, demerger,
    scheme of arrangement, an unparseable subject) is `needs_review` with a null factor, never guessed."""

    __tablename__ = "corporate_actions"
    __table_args__ = (UniqueConstraint("symbol", "ex_date", "subject", name="uq_corporate_actions_event"),)

    symbol: Mapped[str] = mapped_column(String, index=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    ex_date: Mapped[date] = mapped_column(Date, index=True)
    subject: Mapped[str] = mapped_column(String)  # NSE free text, whitespace-normalized, kept verbatim otherwise
    kind: Mapped[str] = mapped_column(String)  # dividend | bonus | split | rights | demerger | buyback | other
    ratio_num: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # bonus a / split new face value
    ratio_den: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # bonus b / split old face value
    amount: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # dividend, rupees per share
    price_factor: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String)  # nse
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SecurityCandle(Base):
    """Daily candle exactly as the source delivered it. The source (Angel) currently delivers split/bonus-ADJUSTED
    history, but that is verified per event at read time (market/adjust.py), not assumed. One row per
    (security, trading date)."""

    __tablename__ = "security_candles"

    security_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric)
    high: Mapped[Decimal] = mapped_column(Numeric)
    low: Mapped[Decimal] = mapped_column(Numeric)
    close: Mapped[Decimal] = mapped_column(Numeric)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class CandleSync(Base):
    """Per-security backfill bookkeeping: what range is stored, when it was last fetched, and why a fetch failed."""

    __tablename__ = "candle_syncs"

    security_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), primary_key=True)
    first_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    full_refetches: Mapped[int] = mapped_column(Integer, default=0)  # times the source re-adjusted history and we replaced it


class SecuritySignal(Base):
    """One row per (security, as_of_date, method_version), inserted only if absent and NEVER updated: signals are
    point-in-time facts, the raw material for a later scoring ledger. A method change is a new `method_version`,
    never an overwrite. `origin` separates live nightly runs from any backtest-style computation over past dates
    (survivorship-biased) which must never feed that ledger."""

    __tablename__ = "security_signals"

    security_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)  # newest candle date used
    method_version: Mapped[str] = mapped_column(String, primary_key=True)
    origin: Mapped[str] = mapped_column(String, default="live")  # live | backtest
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    history_len: Mapped[int] = mapped_column(Integer)
    input_marker: Mapped[str] = mapped_column(String)  # candle_syncs.full_refetches:rows:last date:last close
    quality: Mapped[str] = mapped_column(String)  # ok | insufficient_data | stale | unreliable_window
    universe: Mapped[str] = mapped_column(String)  # kind the ranks are against: stock | etf
    rank_universe_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sma200_ratio: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    trend_state: Mapped[str | None] = mapped_column(String, nullable=True)  # above | below
    mom_12_1: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mom_6_1: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mom_12_1_rank: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    vol_60: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    vol_252: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    vol_252_rank: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    vol_ratio: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    drawdown_current: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_dd_1y: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    week52_pos: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    liquidity_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    circuit_days_20: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # reasons, policy version, adjustment notes


class SecurityForecast(Base):
    """A model forecast (Kronos) as a point-in-time, append-only fact. Stored for a future scoring ledger; it counts
    for nothing until it has proven itself out of sample."""

    __tablename__ = "security_forecasts"

    security_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    model_version: Mapped[str] = mapped_column(String, primary_key=True)
    horizon: Mapped[str] = mapped_column(String, primary_key=True)
    origin: Mapped[str] = mapped_column(String, default="live")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_marker: Mapped[str] = mapped_column(String)
    bars_used: Mapped[int] = mapped_column(Integer)
    sample_count: Mapped[int] = mapped_column(Integer)
    predicted_return: Mapped[float] = mapped_column(Numeric)  # median of the sampled paths
    p10: Mapped[float] = mapped_column(Numeric)
    p90: Mapped[float] = mapped_column(Numeric)
    direction: Mapped[str] = mapped_column(String)  # bullish | bearish | neutral (+/-1% band)
    direction_agreement: Mapped[float] = mapped_column(Numeric)
    calibrated_confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)  # null: no calibration for THIS data
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AllocationPlan(Base, UUIDPKMixin):
    """An immutable allocation proposal: the exact inputs (prices pinned with their dates), the policy version and the full
    result. Keyed by an inputs hash, so the same inputs make ONE record, not one per page load. This is the seed of a later
    shadow ledger: what was suggested, on what data, so it can be scored against what happened."""

    __tablename__ = "allocation_plans"
    __table_args__ = (UniqueConstraint("user_id", "inputs_hash", name="uq_allocation_plans_inputs"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    inputs_hash: Mapped[str] = mapped_column(String)
    policy_version: Mapped[str] = mapped_column(String)
    engine_version: Mapped[str] = mapped_column(String)
    state_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("portfolio_states.id"), nullable=True)
    valuation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("valuation_snapshots.id"), nullable=True)
    new_money: Mapped[Decimal] = mapped_column(Numeric)
    what_if_band: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)  # plan status; the engine's gate status is inside `result`
    origin: Mapped[str] = mapped_column(String, default="owner")  # owner | what_if | verification (not scored)
    params: Mapped[dict] = mapped_column(JSON)
    prices: Mapped[dict] = mapped_column(JSON)  # instrument key -> [price, as_of]
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SuggestionLog(Base, UUIDPKMixin):
    """Immutable record that a price-based observation about a held or watched security began (or was first seen), keyed by
    (fingerprint, trigger date). Written only by the worker. Seed of a later scoring ledger: it stores WHEN the observation was
    first logged (`logged_at`) separately from the date it dates from (`trigger_date`), so an outcome study cannot pretend it was
    known earlier than it was."""

    __tablename__ = "suggestion_log"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint", "trigger_date", name="uq_suggestion_log_trigger"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # trend_below | trend_above | drawdown | deep_drawdown | volatility_elevated | thin_liquidity | history_unreliable
    security_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), index=True)
    context: Mapped[str] = mapped_column(String)  # held | watched | both
    trigger_date: Mapped[date] = mapped_column(Date)
    as_of_date: Mapped[date] = mapped_column(Date)  # newest candle date of the run that logged it
    method_version: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String, default="live")
    signal_input_marker: Mapped[str | None] = mapped_column(String, nullable=True)  # the stored signal row's input marker
    metrics: Mapped[dict] = mapped_column(JSON)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerStudy(Base, UUIDPKMixin):
    """A stored retrospective study, one per (study version, data marker). Study versions are never edited: a changed design is a new
    version, and the scorecard counts how many versions have been tried."""

    __tablename__ = "ledger_studies"
    __table_args__ = (UniqueConstraint("study_version", "data_marker", name="uq_ledger_studies_version_data"),)

    study_version: Mapped[str] = mapped_column(String)
    registry_hash: Mapped[str] = mapped_column(String)
    data_marker: Mapped[str] = mapped_column(String)
    evidence: Mapped[str] = mapped_column(String, default="backtest")
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerOutcome(Base, UUIDPKMixin):
    """What actually happened after a logged signal/forecast/observation/plan leg, over a fixed horizon. INSERT-ONLY. Entry is the first
    close after the day the subject was known; the exit must exist in stored candles (never a partial horizon); a missing exit is
    recorded as `missing_exit`, not dropped. If the price history was later re-based, a new `version` row is written beside the old."""

    __tablename__ = "ledger_outcomes"
    __table_args__ = (UniqueConstraint("claim_id", "subject_key", "horizon_sessions", "version", name="uq_ledger_outcome"),)

    claim_id: Mapped[str] = mapped_column(String, index=True)
    subject_type: Mapped[str] = mapped_column(String)  # signal | forecast | suggestion | plan_leg
    subject_key: Mapped[str] = mapped_column(String)
    security_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_sessions: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String)  # scored | missing_exit
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fwd_return: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fwd_price_return: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # price-only return over the same dates (live-v2: `fwd_return` is TOTAL return)
    dividend_flags: Mapped[str | None] = mapped_column(String, nullable=True)         # dividends applied/skipped for this security's series, e.g. "applied=12;skipped=needs_review:1"
    fwd_vol: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)           # realized volatility over the horizon (the risk claim's outcome)
    universe_return: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # equal-weight average of stored stocks over the same entry/exit dates
    etf_return: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)       # NIFTYBEES over the same dates (secondary benchmark)
    feature: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)           # the signal value / predicted return being scored
    direction: Mapped[int | None] = mapped_column(Integer, nullable=True)             # +1 / -1 for observations that imply one
    origin: Mapped[str] = mapped_column(String, default="live")
    input_marker: Mapped[str | None] = mapped_column(String, nullable=True)
    full_refetches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SchemeTer(Base, UUIDPKMixin):
    """The latest AMFI total-expense-ratio row for one scheme (percent of assets per year). Raw reference data, no matching claims."""

    __tablename__ = "scheme_ter"
    __table_args__ = (UniqueConstraint("nsdl_code", name="uq_scheme_ter_code"),)

    nsdl_code: Mapped[str] = mapped_column(String)
    mf_id: Mapped[int] = mapped_column(Integer, index=True)
    amc_name: Mapped[str] = mapped_column(String)
    scheme_name: Mapped[str] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    ter_date: Mapped[date] = mapped_column(Date)
    regular_ter: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    direct_ter: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    regular_ber: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    direct_ber: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SecurityTer(Base):
    """A DEFENSIBLE match of a catalogue security to a TER scheme (see costs/ter_match.py). A security without a row has an unknown expense ratio."""

    __tablename__ = "security_ter"

    security_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), primary_key=True)
    nsdl_code: Mapped[str] = mapped_column(String)
    scheme_name: Mapped[str] = mapped_column(String)
    ter: Mapped[Decimal] = mapped_column(Numeric)        # percent per year, for the plan this security is
    plan_used: Mapped[str] = mapped_column(String)       # direct | regular | etf
    matched_via: Mapped[str] = mapped_column(String)
    ter_date: Mapped[date] = mapped_column(Date)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketHoliday(Base):
    """An NSE equity-segment (CM) trading holiday, as published. The published list covers only the current year; the calendar module applies
    holidays solely for years present here (`calendar_years` in the status), never inventing or hiding one for other years."""

    __tablename__ = "market_holidays"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    description: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SecurityScore(Base):
    """One checklist score per (security, as_of_date, method_version): inserted once, NEVER updated. `as_of_date` is the newest candle date
    of the price inputs. A change to the method is a new `method_version`, never an overwrite, so a later ledger can ask whether the score
    predicted anything. `detail` holds the components, inputs, flags and the reasons shown to the owner."""

    __tablename__ = "security_scores"

    security_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    method_version: Mapped[str] = mapped_column(String, primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    coverage: Mapped[Decimal] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String)          # eligible | below_floor | not_scored
    fundamentals_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON)
