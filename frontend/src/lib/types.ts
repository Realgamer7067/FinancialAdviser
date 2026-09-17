export interface RiskProfile {
  risk_score: number;
  risk_profile: string;
  investment_horizon_years: number;
  capital: number;
  monthly_contribution: number;
  objective: string;
  liquidity_requirement: string;
}

export type ConfidenceBand = "high" | "medium" | "low";

export type CouncilRole = "planner" | "bull" | "bear" | "fundamental" | "quant" | "risk" | "judge";

// content's shape varies per role -- see app/council/schemas.py on the
// backend. Narrow it per-role at render time rather than typing it here.
export interface CouncilRoleOutput {
  role: CouncilRole;
  content: Record<string, unknown>;
  model_name: string;
  model_version: string;
  prompt_version: string;
  created_at: string;
}

export interface RiskTierBreakdown {
  volatility_30d?: number;
  drawdown_1y?: number;
  beta?: number;
  debt_to_equity?: number;
}

export interface RecommendationCard {
  id: string;
  symbol: string;
  name: string;
  recommendation: "STRONG_CANDIDATE" | "CANDIDATE" | "WATCHLIST" | "NO_RECOMMENDATION";
  confidence: number;
  confidence_band: ConfidenceBand | null;
  score: number;
  risk_level: string;
  risk_tier: "safer" | "moderate" | "risky" | "riskiest" | null;
  risk_tier_score: number | null;
  risk_tier_breakdown: RiskTierBreakdown | null;
  suggested_horizon: string;
  strengths: string[];
  risks: string[];
  rationale: string;
  evidence: Record<string, unknown>;
  fundamental_score: number | null;
  technical_score: number | null;
  kronos_score: number | null;
  news_score: number | null;
  portfolio_score: number | null;
  risk_score: number | null;
  model_agreement: number;
  data_quality: number;
  generated_at: string;
  council_outputs: CouncilRoleOutput[];
}

export interface CouncilRunSummary {
  id: string;
  status: string;
  market_regime: string;
  universe_size: number;
  candidates_after_screen: number;
  candidates_after_kronos_news: number;
  candidates_to_council: number;
  plan: Record<string, unknown>;
  started_at: string;
  completed_at: string | null;
  recommendations: RecommendationCard[];
}

export interface JobStageDetail {
  current_symbol: string | null;
  index: number | null;
  total: number | null;
}

export interface JobStatus {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string | null;
  progress_pct: number | null;
  stage_detail: JobStageDetail | null;
  error: string | null;
  result_council_run_id: string | null;
}

export interface DashboardOut {
  market_status: string;
  nifty_price: number | null;
  nifty_is_stale: boolean;
  has_profile: boolean;
  risk_profile: string | null;
  latest_run_status: string | null;
  top_recommendation_count: number;
  strong_or_candidate_count: number;
}

export interface StockDetail {
  symbol: string;
  name: string;
  sector: string | null;
  latest_price: number | null;
  price_as_of: string | null;
  evidence_is_legacy: boolean;
  fundamentals: {
    as_of_date: string;
    roe: number | null;
    revenue_growth: number | null;
    debt_to_equity: number | null;
    pe: number | null;
    net_margin: number | null;
    market_cap: number | null;
    source: string;
  } | null;
  technicals: {
    rsi_14: number | null;
    trend: string | null;
    volatility_30d: number | null;
    drawdown_1y: number | null;
    macd_hist: number | null;
    beta: number | null;
    // Latest-snapshot reference values, not a historical series -- see
    // KronosHorizonChart/CandlestickChart notes on why overlay LINES are
    // computed client-side from history points instead.
    sma_20: number | null;
    sma_50: number | null;
    sma_200: number | null;
    ema_12: number | null;
    ema_26: number | null;
    bb_upper: number | null;
    bb_lower: number | null;
    computed_at: string;
  } | null;
  kronos: KronosForecast | null;
  kronos_horizons: KronosForecast[];
  news: {
    sentiment_score: number;
    confidence: number;
    article_count: number;
    window_start: string;
    window_end: string;
  } | null;
  recommendation: RecommendationCard | null;
}

export interface KronosForecast {
  forecast_horizon: "7d" | "30d" | "90d";
  direction: "bullish" | "neutral" | "bearish";
  predicted_return: number;
  predicted_return_p10: number;
  predicted_return_p90: number;
  direction_agreement: number;
  sample_count: number;
  confidence: number | null;
  generated_at: string;
}

export interface PortfolioOut {
  method: string;
  allocations: Record<string, number>;
  unallocated_cash: number;
  sectors: Record<string, string | null>;
  expected_return: number | null;
  expected_volatility: number | null;
  sharpe: number | null;
  notes: string[];
  has_allocation: boolean;
  reason: string | null;
}

export interface StockAllocation {
  symbol: string;
  weight: number;
  rupee_amount: number;
  last_price: number | null;
  shares: number | null;
}

export interface AllocateOut {
  amount: number;
  total_allocated: number;
  cash_remainder: number;
  allocations: StockAllocation[];
}

export interface SipProjectionPoint {
  year: number;
  invested_cumulative: number;
  projected_value: number;
}

export interface SipProjectionOut {
  monthly_amount: number;
  years: number;
  annual_rate_pct: number;
  assumed_return: boolean;
  points: SipProjectionPoint[];
}

export interface GoalSipOut {
  target_amount: number;
  years: number;
  annual_rate_pct: number;
  assumed_return: boolean;
  required_monthly_sip: number;
}

export interface NewsArticle {
  title: string;
  url: string;
  source: string;
  published_at: string;
  sentiment: number;
  event_type: string;
  confidence: number;
}

export interface NewsArticlesOut {
  symbol: string;
  articles: NewsArticle[];
}

export interface PriceHistoryPoint {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PriceHistoryOut {
  symbol: string;
  interval: string;
  points: PriceHistoryPoint[];
}

export interface SaferAlternative {
  key: string;
  name: string;
  category: string;
  description: string;
  indicative_return_range: string;
  liquidity: string;
  typical_lock_in: string | null;
  risk_note: string;
  suited_risk_profiles: string[];
  eligibility_note: string | null;
}

export interface SaferAlternativesOut {
  disclaimer: string;
  items: SaferAlternative[];
}

// ---------------------------------------------------------------------------
// Financial inputs: holdings, goals, commitments (V3 Phase 03/05,
// backend/app/api/financial_inputs.py). Money fields are SQLAlchemy Numeric /
// pydantic Decimal server-side, which pydantic v2 serializes as JSON
// STRINGS (verified directly against the backend's response_model with
// FastAPI's TestClient -- not a guess), so every amount below is typed
// `string` and must be parsed with Number(...) before formatting/arithmetic.
// ---------------------------------------------------------------------------

export interface HoldingRowIn {
  raw_identifier_text: string | null;
  instrument_id: string | null;
  account_label: string | null;
  units: string | null;
  amount: string;
  valuation_date: string;
  valuation_source: string;
  cost_basis: string | null;
  locked: boolean;
  lock_reason: string | null;
  ownership: string;
  include_in_planning: boolean;
}

export interface DuplicateCandidate {
  row_index: number;
  raw_identifier_text: string | null;
  reason: "duplicate_within_batch" | "matches_existing_snapshot";
}

export interface UnresolvedIdentifier {
  row_index: number;
  raw_identifier_text: string | null;
}

export interface HoldingsPreviewResponse {
  rows: HoldingRowIn[];
  duplicate_candidates: DuplicateCandidate[];
  unresolved_identifiers: UnresolvedIdentifier[];
}

export interface HoldingPositionOut {
  id: string;
  instrument_id: string | null;
  raw_identifier_text: string | null;
  account_label: string | null;
  units: string | null;
  amount: string;
  valuation_date: string;
  valuation_source: string;
  cost_basis: string | null;
  locked: boolean;
  lock_reason: string | null;
  ownership: string;
  include_in_planning: boolean;
  identification_confidence: "high" | "low" | "unresolved";
}

export interface HoldingsSnapshotOut {
  id: string;
  source: string;
  import_hash: string | null;
  idempotency_key: string;
  created_at: string;
  positions: HoldingPositionOut[];
}

export interface GoalOut {
  id: string;
  description: string;
  target_amount: string;
  target_basis: "today_money" | "future_money";
  target_date: string;
  priority: number;
  flexibility: "fixed" | "flexible";
  inflation_assumption: string | null;
  inflation_assumption_version: string | null;
  version: number;
  superseded_at: string | null;
  created_at: string;
  earmarked_total: string;
  remaining_unearmarked_target: string;
}

export interface EarmarkOut {
  id: string;
  goal_id: string;
  holding_position_id: string;
  amount: string;
  created_at: string;
}

export interface CommitmentOut {
  id: string;
  instrument_id: string | null;
  category: string | null;
  amount: string;
  frequency: "monthly" | "quarterly" | "annual";
  start_date: string;
  end_date: string | null;
  contribution_timing: "start_of_period" | "end_of_period";
  step_up_rule: Record<string, unknown> | null;
  status: "active" | "paused" | "ended";
  goal_id: string | null;
  source: "existing_user_reported" | "proposed";
  budget_interpretation: "includes_existing_commitments" | "additional_to_existing_commitments" | null;
  created_at: string;
}

// V3 4.1 product families (backend/app/models/catalogue.py).
export type ProductType =
  | "direct_listed_equity"
  | "equity_index_fund"
  | "equity_index_etf"
  | "bank_fd"
  | "bank_rd"
  | "treasury_bill"
  | "govt_security"
  | "liquid_debt_fund"
  | "gold_fund_etf"
  | "locked_account"
  | "hybrid_fund"
  | "other";

export type SupportLevel = "education_only" | "holdings_only" | "category_planning" | "instrument_planning";

export interface ProductCatalogEntryOut {
  id: string;
  external_ids: Record<string, unknown>;
  parent_exposure_id: string | null;
  product_type: ProductType | string;
  issuer_or_amc: string;
  currency: string;
  status: "active" | "inactive";
  support_level: SupportLevel | string; // stored hint, not authoritative
  resolved_support_level: SupportLevel | string; // authoritative -- use this one
  exposure_vector: Record<string, number>;
  exposure_as_of: string;
  valuation_method: string;
  valuation_date: string | null;
  eligible_contribution_methods: string[];
  minimum_initial: string | null;
  minimum_additional: string | null;
  increment: string | null;
  quantity_granularity: "whole_unit" | "fractional" | "amount";
  settlement_delay_days: number | null;
  maturity_or_lock_rule: string | null;
  fee_assumptions: Record<string, unknown> | null;
  eligibility_predicates: Record<string, unknown> | null;
  source_ids: string[];
  source_freshness: string;
  is_synthetic: boolean;
  created_at: string;
}

// Research (V3 Phase 08, extended 2026-09-16 with search + synthesis --
// see backend/app/api/research.py). A session reaching "ready_to_publish"
// has real, verified evidence but synthesis (turning it into an actual
// written CompanyAssessment) may or may not have succeeded -- check
// `report`/`synthesis_error`, never assume "ready_to_publish" alone means
// a finished report. Only `state === "published"` with a non-null `report`
// is a real, synthesized result.
export type ResearchBranchStatus = "pending" | "running" | "complete" | "partial" | "unavailable" | "failed" | "cancelled";

export interface ResearchBranchOut {
  id: string;
  branch_type: string;
  status: ResearchBranchStatus;
  gap_reason: string | null;
  fact_ids: string[];
}

export interface ResearchVerificationOut {
  total_material_claims: number;
  supported_count: number;
  unsupported_count: number;
  unknown_count: number;
  contradicted_count: number;
  unresolved_critical_claim_ids: string[];
  fully_verifiable: boolean;
}

export interface ClaimReference {
  fact_id: string;
  text: string;
  support_status: string;
}

export interface CompanyAssessment {
  entity: string;
  short_assessment: string;
  business_explanation: string;
  strongest_supporting_evidence: ClaimReference[];
  strongest_opposing_evidence: ClaimReference[];
  financial_context: ClaimReference[];
  valuation_assumptions: string[];
  risks: string[];
  catalysts: string[];
  missing_facts: string[];
  conditions_that_would_change_assessment: string[];
  manifest_version: string;
  generated_at: string;
}

export interface ResearchSessionOut {
  id: string;
  state: string;
  question: string;
  named_gaps: string[];
  branches: ResearchBranchOut[];
  verification: ResearchVerificationOut | null;
  contradictions: Record<string, unknown>[];
  stopped_reason: string | null;
  report: CompanyAssessment | null;
  synthesis_error: string | null;
}
