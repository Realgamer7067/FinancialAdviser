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

// --- Portfolio Intelligence Engine, /api/v4 (Phase 01) ---

export interface V4Account {
  id: string;
  source_type: string;
  label: string;
  included: boolean;
  status: string;
  version: number;
  created_at: string;
  latest_import: { id: string; created_at: string; row_count: number } | null;
}

export interface V4Position {
  display_name?: string | null;
  identity?: string | null;
  security_id?: string | null;
  row_ordinal: number;
  asset_type: string;
  raw_identifier: string | null;
  isin: string | null;
  symbol: string | null;
  instrument_id: string | null;
  resolution: "resolved" | "ambiguous" | "unresolved" | "not_applicable";
  resolution_note: string | null;
  units: string | null;
  value: string | null;
  valuation_date: string;
  cost_basis: string | null;
  locked: boolean;
  ownership: string;
}

export interface V4AccountPositions {
  account_id: string;
  import_id: string | null;
  imported_at: string | null;
  positions: V4Position[];
}

export interface V4Coverage {
  version: number;
  status: "complete" | "partial" | "unknown";
  missing_account_types: string[];
  confirmed_at: string | null;
}

export interface V4PreviewRow {
  ordinal: number;
  asset_type: string;
  raw_identifier: string | null;
  units: string | null;
  value: string | null;
  valuation_date: string;
  resolution: V4Position["resolution"];
  resolution_note: string | null;
}

export interface V4ImportChange {
  identifier: string;
  asset_type: string;
  before_units: string | null;
  after_units: string | null;
  before_value: string | null;
  after_value: string | null;
  goal_claims: number;
}

export interface V4Reconcile {
  previous_import_at: string | null;
  previous_row_count: number;
  added: V4ImportChange[];
  removed: V4ImportChange[];
  changed: V4ImportChange[];
  unchanged: number;
  goal_claims_affected: number;
}

export interface V4Preview {
  account_id: string;
  row_count: number;
  rows: V4PreviewRow[];
  errors: { row: number; field: string; message: string }[];
  conflicts: { row: number; kind: string; detail: string }[];
  unresolved_count: number;
  content_hash: string | null;
  can_confirm: boolean;
  reconcile: V4Reconcile | null;
}

export interface V4Import {
  id: string;
  account_id: string;
  created_at: string;
  row_count: number;
  content_hash: string;
  replayed: boolean;
  positions: V4Position[];
}

// --- Phase 02: Angel connection + typed jobs ---

export interface V4AngelStatus {
  api_key_configured: boolean;
  fingerprint_key_configured: boolean;
  session: "connected" | "reconnect_required" | "not_connected";
  session_expires_at: string | null;
  accounts: {
    id: string;
    label: string;
    masked_external_id: string | null;
    status: string;
    last_sync_at: string | null;
    last_error: string | null;
  }[];
  reconnect_instructions: string | null;
}

export interface V4Job {
  id: string;
  kind: string;
  account_id: string | null;
  status: "queued" | "running" | "done" | "failed";
  error_code: string | null;
  error: string | null;
  result_import_id: string | null;
  result_import_status: string | null;
  created_at: string;
  completed_at: string | null;
}

// --- Phase 03: Portfolio Twin ---

export interface V4Readiness {
  [dimension: string]: { status: "complete" | "partial" | "unusable"; missing: string[] };
}

export interface V4TwinPosition {
  display_name?: string;
  in_catalogue?: boolean;
  security_id?: string | null;
  identity?: string;
  position_id: string;
  account_id: string;
  account_label: string | null;
  asset_type: string;
  raw_identifier: string | null;
  isin: string | null;
  resolution: "resolved" | "ambiguous" | "unresolved" | "not_applicable";
  units: string | null;
  locked: boolean;
}

export interface V4Selection {
  position_id: string;
  value: string | null;
  source: string | null;
  as_of: string;
  quality: "fresh" | "stale" | "unvalued";
}

export interface V4Twin {
  state: {
    id: string;
    version: number;
    created_at: string;
    coverage: { status: "complete" | "partial" | "unknown"; missing_account_types: string[] };
    accounts: { account_id: string; label: string; source_type: string; status: string; position_count: number }[];
    positions: V4TwinPosition[];
  } | null;
  valuation: {
    id: string;
    cutoff: string;
    known_total: string;
    unknown_value_count: number;
    coverage: {
      valued_count: number;
      identity_resolved_value_share: string | null;
      fresh_value_share: string | null;
      earliest_as_of: string | null;
      latest_as_of: string | null;
    };
    selections: V4Selection[];
  } | null;
  readiness: V4Readiness;
  headline_label: string;
  is_stale: boolean;
}

// --- Phase 04a: personal facts ---

export interface V4Facts {
  monthly_income: string | null;
  income_stability: "stable" | "variable" | "uncertain" | null;
  monthly_essential_expenses: string | null;
  dependents: number | null;
  emergency_reserve_amount: string | null;
  emergency_reserve_months_target: string | null;
  monthly_investable_surplus: string | null;
  one_time_available: string | null;
  near_term_obligations: { description: string; amount: string; due_date: string }[] | null;
  employer_exposure: string | null;
  knowledge_level: "beginner" | "intermediate" | "advanced" | null;
  tolerance_answers: {
    portfolio_drop_20pct_reaction: string | null;
    priority: string | null;
    loss_tolerance: string | null;
  };
}

export interface V4Profile {
  version: number;
  facts: V4Facts;
  missing_fields: string[];
  tolerance: { status: "ready" | "unknown"; score: number | null; band: string | null; missing: string[]; note?: string };
  capacity: {
    status: string;
    missing: string[];
    monthly_essential_outgo: string | null;
    reserve_coverage_months: string | null;
    reserve_target_amount: string | null;
    computed_monthly_surplus: string | null;
    debt_service_ratio: string | null;
    stated_surplus_exceeds_computed: boolean | null;
    debt_payments_incomplete: boolean;
    near_term_obligations_12m: string | null;
    binding_constraints: { rule: string; detail: string }[];
    blocks_risk_increasing_actions: boolean;
    policy_version: string;
  };
}

export interface V4Liability {
  chain_id: string;
  version: number;
  kind: string;
  outstanding_amount: string;
  as_of: string;
  monthly_payment: string | null;
  rate_type: string;
  annual_rate: string | null;
  next_reset_date: string | null;
  maturity_date: string | null;
  status: string;
  rate_sensitivity_known: boolean;
}

export interface V4Preference {
  chain_id: string;
  version: number;
  kind: string;
  value: string;
  expires_on: string | null;
}

// --- Phase 04b: goals, claims, commitments ---

export interface V4Allocation {
  chain_id: string;
  version: number;
  goal_chain_id: string;
  holding: string;
  amount: string;
  status: "active" | "needs_review" | "released";
  reason: string | null;
}

export interface V4Goal {
  chain_id: string;
  version: number;
  description: string;
  target_amount: string;
  target_basis: "today_money" | "future_money";
  target_date: string;
  priority: number;
  flexibility: string;
  inflation_assumption: string | null;
  allocated_total: string;
  needs_review_total: string;
  allocations: V4Allocation[];
}

export interface V4HoldingSummary {
  account: string;
  holding: string;
  asset_type: string;
  position_ids: string[];
  value: string | null;
  claimed: string;
  unclaimed: string | null;
}

export interface V4Commitment {
  chain_id: string;
  version: number;
  goal_chain_id: string | null;
  description: string;
  amount: string;
  frequency: string;
  start_date: string;
  end_date: string | null;
  status: string;
  source: string;
  budget_interpretation: string | null;
  monthly_equivalent: string;
}

export interface V4Projection {
  goal_chain_id: string;
  description: string;
  status: "ready" | "needs_input" | "blocked_needs_review";
  message?: string;
  missing?: string[];
  months?: number;
  starting_value: string;
  monthly_contribution_counted: string;
  limitations: string[];
  required_annual_return?: string | null;
  assessment?: "reachable_under_base" | "needs_higher_return_or_contribution" | "target_needs_revision";
  assessment_message?: string;
  scenarios?: Record<string, { annual_rate: string; projected_value: string; gap_to_target: string | null; required_monthly_contribution: string | null; funded: boolean }>;
  note?: string;
}

export interface V4Budget {
  status: "known" | "unknown";
  missing?: string[];
  stated_investable_surplus: string | null;
  computed_monthly_surplus: string | null;
  monthly_committed_included_in_surplus: string;
  monthly_committed_on_top_of_surplus: string;
  remaining_for_new_monthly: string | null;
  over_committed?: boolean;
  exceeds_income_after_essentials?: boolean | null;
  excluded_streams: { chain_id: string; description: string; monthly_equivalent: string; status: string; source: string }[];
}

export interface V4RiskConstraints {
  policy_version: string;
  risk_increasing_allowed: boolean;
  limiting_factors: string[];
  ceilings: { source: string; status: string; detail?: string; band?: string; blocks_risk_increasing: boolean }[];
  note: string;
}

// --- Phase 05: risk and scenarios ---

export interface V4RiskReport {
  analysis_id: string;
  state_id: string;
  valuation_id: string;
  as_of: string;
  known_total: string;
  asset_mix: {
    status: string;
    classes: Record<string, { value: string; weight: string | null; classification_basis: Record<string, string> }>;
    direct_equity_share: string | null;
    equity_share_upper_bound: string | null;
    unvalued_positions: number;
    warnings: string[];
  };
  issuer_concentration: {
    status: string;
    largest_issuer?: string;
    largest_issuer_weight?: string | null;
    top5_weight?: string | null;
    effective_positions_over_identified?: string;
    coverage_fraction?: string | null;
    issuers: { issuer: string; value: string; weight: string | null; accounts: string[] }[];
    warnings: string[];
  };
  sector: { buckets: { bucket: string; value: string; weight: string | null }[]; unknown_weight: string | null };
  account_concentration: { account: string; value: string; weight: string | null }[];
  coverage: { fresh_value_share: string | null; identity_resolved_value_share: string | null; unvalued_count: number; earliest_as_of: string | null; latest_as_of: string | null };
  liquidity: { status: string; accessible_cash_after_claims: string; months_of_outgo: string | null; ratio_to_12m_need: string | null; warnings?: string[] };
  volatility: {
    status: string;
    reason?: string;
    annualized_volatility?: number;
    max_drawdown_in_window?: number;
    window_start?: string;
    window_end?: string;
    observations?: number;
    coverage_fraction: string | null;
    warnings?: string[];
  };
  correlation_clusters: { status: string; reason: string };
  limitations: string[];
}

export interface V4ScenarioResult {
  analysis_id: string;
  scenario: { id: string; label: string; shock: string };
  label: string;
  known_total: string;
  modeled_value: string;
  modeled_change: string;
  modeled_change_pct_of_known_total: string | null;
  outside_coverage: { value: string; share_of_known_total: string | null; unvalued_positions: number; note: string };
  ledger: { position_id: string; account: string; holding: string; pre_shock_value: string | null; modeled_return: string | null; value_change: string | null; modeled: boolean; reason: string }[];
  reconciles: boolean;
}

export interface V4ScenarioCatalog {
  scenarios: { id: string; label: string; status: "supported" | "unsupported"; reason?: string }[];
}

// --- Phase 06: counterfactual lab ---

export interface V4Gate {
  gate_id: string;
  result: "pass" | "fail" | "unknown";
  observed: unknown;
  allowed: unknown;
  data_source: string;
  reason: string;
}

export interface V4Alternative {
  index: number;
  action: Record<string, string | number | null>;
  status: "dominates_hold" | "tradeoff" | "no_material_benefit" | "worse_than_hold" | "review_required" | "needs_input" | "rejected";
  reasons: string[];
  gates: V4Gate[];
  notes: string[];
  cost: Record<string, string | number> | null;
  metrics_after: Record<string, string | null>;
  comparison_vs_hold: { rows: { metric: string; before: string | null; after: string | null; delta: string | null; verdict: string }[] } | null;
  candidate_state_hash: string;
  accounting: { assets_before: string; external_contribution: string; external_withdrawal: string; assets_after: string; friction: string; residual: string; conserved: boolean };
  designated_reserve: string | null;
}

export interface V4Evaluation {
  analysis_id: string;
  published: boolean;
  default: string;
  note: string;
  flows: { external_contribution: string; external_withdrawal: string; fee_pct: string };
  hold: { metrics: Record<string, string | null>; accounting: { assets_before: string; assets_after: string; conserved: boolean; note: string } };
  alternatives: V4Alternative[];
  summary: { best_alternative_index: number | null; runner_up_index: number | null; headline: string; why_runner_up_lost: string[] | null };
}

export interface V4Instrument { id: string; symbol: string; name: string; sector: string | null; lot_size: number }

// --- Phase 07: decisions ---

export interface V4Issue {
  kind: string;
  severity: "urgent" | "review" | "information";
  title: string;
  detail: string;
}

export interface V4Outcome {
  outcome_id: string;
  status: "HOLD" | "REVIEW" | "NEEDS_INPUT";
  headline: string;
  state_id: string;
  state_version: number;
  valuation_id: string;
  policy_version: string;
  created_at: string;
  superseded: boolean;
  superseded_reason: string | null;
  result?: {
    issues: V4Issue[];
    explanation: {
      current_issues: string[];
      not_assessed_or_incomplete: string[];
      compared: string;
      next_best_alternative: string | null;
      triggers_to_revisit: string[];
      why_hold?: string;
      why_not_hold?: string;
    };
    readiness: Record<string, { status: string; missing: string[] }>;
    known_total: string;
    headline_label: string;
    alternatives: { index: number; action: Record<string, string | number | null>; status: string; reasons: string[] }[];
    evidence: { risk_analysis_id: string; evaluation_analysis_id: string | null; state_id: string; valuation_id: string };
    audit: { state_version: number; computed_at: string; code_version: string; uses_llm: boolean; policy_versions: Record<string, string>; valuation_cutoff: string };
    valid: { review_by: string; invalidated_by: string[] };
  };
}

export interface V4CurrentDecision {
  status: "current" | "pending_review" | "none";
  outcome: V4Outcome | null;
  valuation_newer?: boolean;
  review_overdue?: boolean;
  since_previous?: { previous_outcome_id: string | null; nothing_material_changed: boolean; new_issues: string[]; resolved_issues: string[] };
  pending_review: { job_id: string; status: string } | null;
  message: string | null;
}

export interface V4TimelineEntry extends Omit<V4Outcome, "result"> { is_current: boolean }

// --- Phase 08: inbox and events ---

export interface V4InboxItem {
  id: string;
  fingerprint: string;
  kind: string;
  category: "urgent" | "review" | "information" | "resolved";
  severity: "urgent" | "review" | "information";
  title: string;
  detail: string;
  status: "open" | "snoozed" | "dismissed" | "resolved";
  first_seen_at: string;
  last_seen_at: string;
  snooze_until: string | null;
  dismissed_reason: string | null;
  reopen_count: number;
  version: number;
}

export interface V4Inbox {
  counts: Record<"open" | "snoozed" | "dismissed" | "resolved", number>;
  items: V4InboxItem[];
}

export interface V4Event { kind: string; occurred_at: string; received_at: string }

// --- Phase 09: theses ---

export interface V4Assessment {
  assessment_id: string;
  thesis_chain_id: string;
  thesis_version: number;
  status: "supported" | "mixed" | "weakened" | "insufficient";
  change_log: string;
  review_status: "pending" | "acknowledged";
  created_at: string;
  portfolio_effect: string;
  per_condition?: { condition_id: string; text: string; kind: string; verdict: string; cited_fact_ids: string[]; note: string; independent_sources: number; lineages: string[]; dropped: string[] }[];
  evidence?: Record<string, { text: string; supporting: { url: string; lineage: string; location: string | null; publication_time: string | null }[]; independent_sources: number; support_status: string }>;
  gaps?: string[];
  contradictions?: { reason?: string }[];
  verification?: { total_material_claims: number; supported_count: number; fully_verifiable: boolean; caveat?: string } | null;
  model_info?: { used: boolean; model: string | null; error: string | null };
}

export interface V4Thesis {
  chain_id: string;
  version: number;
  instrument_id: string;
  symbol: string;
  ownership: "owned" | "considered";
  reason: string;
  conditions: { id: string; text: string; kind: "supports" | "invalidates" }[];
  status: "active" | "closed";
  latest_assessment: V4Assessment | null;
  note: string;
  events?: { kind: string; observed: Record<string, unknown>; occurred_at: string; effect_on_thesis: string }[];
}

// --- Watchlist (Angel One market data) ---

export interface V4WatchQuote {
  ltp: string;
  prev_close: string | null;
  day_change_pct: string | null;
  high: string | null;
  low: string | null;
  week52_high: string | null;
  week52_low: string | null;
  position_in_52w_range: number | null;
  retrieved_at: string;
  exchange_time: string | null;
  freshness: "live" | "delayed" | "last_session" | "none";
}

export interface V4WatchItem {
  item_id: string;
  broker_instrument_id: string;
  security_id: string | null;
  instrument_id: string | null;
  symbol: string;
  name: string;
  note: string | null;
  why_watching: string | null;
  quote: V4WatchQuote | null;
  context: {
    owned: boolean;
    owned_weight: string | null;
    owned_value: string;
    accounts: string[];
    sector: string | null;
    sector_weight_now: string | null;
    context_available: boolean;
    facts: string[];
    restriction_conflicts: string[];
    issuer_room_rupees?: string;
    sector_room_rupees?: string;
  };
  alerts: { id: string; kind: string; threshold: string; triggered: boolean; text: string }[];
}

export interface V4Watchlists {
  lists: { id: string; name: string; items: V4WatchItem[] }[];
  market: { open: boolean; label: string; ist_time: string };
  broker_session: "connected" | "not_connected";
  context_basis: string;
}

export interface V4SearchResult { broker_instrument_id: string; symbol: string; name: string; in_universe: boolean }

// --- Market page (securities catalogue) ---

export interface V4SecurityPrice {
  ltp: string;
  prev_close: string | null;
  percent_change: string | null;
  week52_high: string | null;
  week52_low: string | null;
  volume: number | null;
  as_of: string;
  exchange_time: string | null;
  freshness: "live" | "delayed" | "last_session" | "none";
}

export interface V4Security {
  id: string;
  kind: "stock" | "etf" | "mutual_fund";
  symbol: string | null;
  isin: string | null;
  name: string;
  sector: string | null;
  asset_class: string | null;
  category: string | null;
  series: string | null;
  is_active: boolean;
  tradable_in_angel: boolean;
  broker_instrument_id: string | null;
  instrument_id: string | null;
  // funds
  scheme_code?: string;
  amc?: string | null;
  plan?: "direct" | "regular" | null;
  option?: "growth" | "idcw" | null;
  nav?: string | null;
  nav_date?: string | null;
  // stocks / ETFs
  price?: V4SecurityPrice;
  signals?: V4SignalsBrief;
  ter?: { percent: string; plan: string; as_of: string; scheme: string; source: string };
}

export interface V4SecurityList { total: number; limit: number; offset: number; items: V4Security[] }

export interface V4Facets {
  kinds: Record<string, number>;
  sectors: { value: string; count: number }[];
  asset_classes: { value: string; count: number }[];
  fund_categories: { value: string; count: number }[];
  unclassified_stocks: number;
}

export interface V4Movers { as_of: string | null; gainers: V4Security[]; losers: V4Security[]; most_traded: V4Security[] }

export interface V4QuoteRefresh {
  refreshed: boolean;
  reason: string | null;
  items: V4Security[];
  market: { open: boolean; label: string; ist_time: string };
}

export interface V4CorporateActionRow { ex_date: string; kind: string; subject: string; amount: string | null; price_factor: string | null; needs_review: boolean }

export interface V4SecurityDetail extends V4Security {
  face_value: string | null;
  lot_size: number | null;
  listing_date: string | null;
  isin_reinvest: string | null;
  source: string;
  seen_at: string;
  corporate_actions: V4CorporateActionRow[];
}

export interface V4History {
  status: "ready" | "none" | "queued" | "unsupported";
  message?: string;
  tradable_in_angel?: boolean;
  coverage: { first_date: string | null; last_date: string | null; rows: number; fetched_at: string; last_error: string | null; full_refetches: number } | null;
  adjustment: {
    applied: number;
    audit: { ex_date: string; kind: string; factor: string | null; ratio: string | null; status: string }[];
    unreliable: { date: string; reason: string }[];
  } | null;
  candles: { d: string; o: string; h: string; l: string; c: string; v: number | null }[];
}

export interface V4MarketJobs {
  market_snapshot: { status: string; error_code: string | null; created_at: string; completed_at: string | null; result: Record<string, unknown> | null } | null;
  candle_backfill: { status: string; error_code: string | null; created_at: string; completed_at: string | null; result: Record<string, unknown> | null } | null;
  candle_securities: number;
  quotes: number;
}

// --- Signals (descriptions of past prices; never advice) ---

export interface V4SignalsBrief {
  as_of: string;
  quality: "ok" | "insufficient_data" | "stale" | "unreliable_window";
  trend_state: "above" | "below" | null;
  mom_12_1_rank: number | null;
  vol_252: number | null;
  drawdown_current: number | null;
  liquidity: "ok" | "thin" | "unknown";
}

export interface V4Family { state: string; vote: number; text: string }

export interface V4SecuritySignals {
  status: "ready" | "none";
  kind: string;
  message?: string;
  note?: string;
  latest: {
    as_of: string; computed_at: string; method_version: string; origin: string; quality: string; universe: string; rank_universe_size: number | null;
    history_len: number; trend_state: string | null; circuit_days_20: number | null;
    sma200_ratio: number | null; mom_12_1: number | null; mom_6_1: number | null; mom_12_1_rank: number | null; vol_60: number | null; vol_252: number | null;
    vol_252_rank: number | null; vol_ratio: number | null; drawdown_current: number | null; max_dd_1y: number | null; week52_pos: number | null; liquidity_value: number | null;
    detail: { reasons?: string[]; unreliable?: { date: string; reason: string }[] } | null;
  } | null;
  families?: { policy_version: string; trend: V4Family; risk: V4Family; liquidity: V4Family; forecast: V4Family; net_vote: number };
  forecast?: {
    as_of: string; horizon: string; direction: string; predicted_return: number; p10: number; p90: number; direction_agreement: number;
    relative_rank: number | null; peers_on_date: number; bias_warning: string; counts_toward_checks: boolean;
  } | null;
  history: { as_of: string; quality: string; trend_state: string | null; mom_12_1_rank: number | null; vol_252: number | null; drawdown_current: number | null }[];
}

// --- Allocation plan (a proposal for new money; never advice, never a sale) ---

export interface V4PlanLeg {
  bucket: string; role: string; underlying: string | null; instrument_id: string; symbol: string; name: string; kind: string; isin: string | null;
  units: number; price: string; price_as_of: string; planned_debit: string; sector: string | null; why: string | null;
}

export interface V4Gate { gate_id: string; result: "pass" | "fail" | "unknown"; observed: unknown; allowed: unknown; reason: string }

export interface V4RankComponent {
  score: number | null; coverage: number; measures_used: number; measures_possible: number; missing: string[]; inactive: string[];
  measures: Record<string, { value: number; percentile: number; peers: number }>;
}
export interface V4RankRow {
  symbol: string; name: string; sector: string | null; financial: boolean; rank: number | null; rank_of: number; composite: number | null;
  status: "picked" | "candidate" | "not_picked" | "excluded" | "below_floor" | "not_ranked"; note: string | null;
  components: Record<"value" | "quality" | "momentum", V4RankComponent>; coverage: number; strengths: string[]; weaknesses: string[]; flags: string[];
  risk: { vol_252?: number | null; max_dd_1y?: number | null; liquidity_value?: number | null; circuit_days_20?: number | null };
  dates: { fundamentals_as_of: string | null; price_as_of: string | null }; momentum_basis: string | null;
  fit: { direct: number; lookthrough: number; total: number; note: string } | null;
  cost: { units: number; price: string; price_as_of: string; trade_value: string; planned_debit: string; assumed_charges: string; note: string } | null;
  price: number | null; security_id: string;
}
export interface V4StockRanking {
  version: string; weights: Record<string, number>; floor: number; policy_note: string; fundamentals_as_of: { oldest: string | null; newest: string | null };
  rows: V4RankRow[]; candidates: number; inactive_measures: string[]; inactive_note: string | null; momentum_caution?: { state: "elevated" | "watch" | "normal" | "unknown"; market_2y: number | null; market_1m: number | null; note: string } | null; selection_rule: string; no_stock_reason: string | null; safety_note: string;
  risk_beside_rank?: {
    status: string; reason?: string; method: string; stocks?: string[]; equal_weight_volatility?: number; average_pairwise_correlation?: number; shrinkage_intensity?: number;
    stand_alone_volatility?: Record<string, number>; average_correlation_with_held?: Record<string, number>; warnings?: string[]; note?: string; returns_used?: number;
  } | null;
}

export interface V4Funds {
  available: string | null; as_of: string | null; age_minutes: number | null; account_id: string | null; account_label: string | null;
  fields: Record<string, string>; stale: boolean; note: string;
}

export interface V4StockScreenRow {
  symbol: string; name: string; sector: string | null; financial: boolean; score: number | null; coverage: number;
  status: "picked" | "top_in_sector" | "not_picked" | "low_score" | "not_scored"; note: string | null;
  reasons: string[]; flags: string[]; missing: string[]; pe: number | null; pb: number | null; roe: number | null; debt_to_equity: number | null; volatility_1y: number | null;
  components: Record<string, number | null>; price: number | null; trend: string | null; momentum_rank: number | null; security_id: string;
}
export interface V4StockScreen {
  version: string; floor: number; weights: Record<string, number>; fundamentals_as_of: { oldest: string | null; newest: string | null }; rows: V4StockScreenRow[]; note: string;
}

export interface V4SmallAmount {
  threshold: string; message: string; version: number;
  options: { kind: "liquid_fund" | "index_fund"; title: string; adds_risk: boolean; detail: string; fund: { name: string; amc: string | null; scheme_code: string; nav: string | null; nav_date: string | null; ter_percent: number | null; ter_as_of: string | null } }[];
  single_units: { symbol: string; name: string; kind: string; price: string; price_as_of: string; why: string | null }[];
  single_units_note: string; stocks_note: string;
}

export interface V4AllocationPlan {
  plan_id: string; created: boolean; created_at: string; policy_version: string;
  status: "ready" | "needs_input" | "blocked" | "nothing_to_do";
  reasons: string[]; warnings: string[];
  mix: { source: string; band: string | null; needs_input: boolean };
  new_money: string; classified_total: string; unknown_value: string; unknown_share: string; cash_not_counted: string; base_total_after_plan: string;
  target: Record<string, { weight: string; value: string }>;
  drift: { bucket: string; label: string; target_weight: string; current_weight: string | null; current_value: string; target_value: string; outside_band: boolean; direction: string | null; note: string | null }[];
  legs: V4PlanLeg[]; spent: string; leftover_cash: string;
  no_sales_note: string; satellite_note: string; liquid_note: string; disclaimer: string;
  policy: Record<string, unknown>;
  engine: null | {
    status: "gates_pass" | "blocked" | "needs_input"; reasons: string[]; comparison_caveat: string;
    legs: { index: number; action: Record<string, string>; gates: V4Gate[]; notes: string[]; failed: boolean }[];
    final_gates: V4Gate[];
    comparison_vs_hold: { rows: { metric: string; before: string | null; after: string | null; verdict: string }[] };
    accounting: { assets_before: string; external_contribution: string; assets_after: string; friction: string; residual: string; conserved: boolean };
  };
  fund_alternatives: { name: string; amc: string | null; scheme_code: string; nav: string | null; nav_date: string | null; ter_percent: number | null; ter_as_of: string | null }[];
  small_amount: V4SmallAmount | null;
  stock_screen?: V4StockScreen;
  stock_ranking?: V4StockRanking;
  fund_note: string;
}

// --- Suggestions: what changed for what you hold or watch (descriptions of past prices, never advice) ---

export interface V4SuggestionOption { id: string; text: string; href?: string }

export interface V4Observation {
  kind: string; severity: "information"; attention: "look" | "context"; title: string; detail: string;
  since: string | null; sessions_since: number | null; measure: number | null; options: V4SuggestionOption[];
  recent_change?: boolean; changes_1y?: number; raw_crossings_1y?: number;
}

export interface V4SuggestionItem {
  security_id: string; symbol: string | null; name: string; isin: string | null; kind: string; context: "held" | "watched" | "both";
  instrument_id: string | null; position_ids: string[]; watchlists: string[]; quality: string; signal_as_of: string | null; note?: string; observations: V4Observation[];
}

export interface V4PortfolioSuggestion { kind: string; title: string; detail: string; href?: string; options?: V4SuggestionOption[]; bucket?: string }

export interface V4Suggestions {
  generated_at: string; as_of: string | null; note: string;
  policy: { policy_version: string; status: string; note: string; measured_flip_rates: { stocks: number; trend_plain_crossings_per_year: { median: number }; trend_rule_changes_per_year: { median: number } } };
  held: V4SuggestionItem[]; watched: V4SuggestionItem[]; portfolio: V4PortfolioSuggestion[]; funds_without_price_signals: string[]; unresolved_holdings: number;
}

// --- Scorecard: has any signal earned a weight? ---

export interface V4StudyClaim {
  id: string; statement: string; kind: "return" | "risk"; verdict: string; verdict_meaning: string;
  primary: { horizon: number; n_dates: number; mean_ic: number | null; sd: number | null; t: number | null; p_two_sided: number | null; ci: [number, number] | null;
             ci_95_unadjusted: [number, number] | null; bootstrap_ci_corrected: [number, number] | null; minimum_detectable_ic: number | null; share_of_dates_positive: number | null; by_year_mean_ic: Record<string, number> };
  secondary_63?: { horizon: number; n_dates: number; mean_ic: number | null; ci_95: [number, number] | null };
  top_quintile_minus_universe?: { mean: number | null; ci_95: [number, number] | null; note: string };
}

export interface V4Study {
  status: "ready" | "none"; message?: string; versions_tried: number; study_version?: string; registry_hash: string; frozen_hash_matches_code?: boolean; created_at?: string;
  dates?: { n: number; first: string | null; last: string | null }; names_per_date?: { min: number | null; median: number | null; max: number | null };
  claims?: V4StudyClaim[]; biases?: string[]; alpha_per_claim?: number; k?: number; panel?: { securities: number; sessions: number; first: string; last: string };
}

export interface V4LiveClaim {
  id: string; type: string; horizon_sessions: number; logged: number; scored: number; missing_exit: number; pending: number; first_results_expected: string | null;
  verdict: string | null; verdict_meaning?: string; n_dates_used?: number; mean?: number | null; ci_corrected?: [number, number] | null; minimum_detectable_ic?: number | null;
  net_of_cost_lower_bound?: number | null; dates_needed_for_earned?: number; unit?: string; label?: string; note?: string; plan_weighted_return?: number | null; market_etf_average_return_same_dates?: number | null;
}

export interface V4LiveLedger { claims: V4LiveClaim[]; outcomes_scored: number; rule: string; k: number; alpha_per_claim: number; registry_hash: string }
