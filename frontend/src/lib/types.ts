export interface RiskProfile {
  risk_score: number;
  risk_profile: string;
  investment_horizon_years: number;
  capital: number;
  monthly_contribution: number;
  objective: string;
  liquidity_requirement: string;
}

export interface RecommendationCard {
  id: string;
  symbol: string;
  name: string;
  recommendation: "STRONG_CANDIDATE" | "CANDIDATE" | "WATCHLIST" | "NO_RECOMMENDATION";
  confidence: number;
  score: number;
  risk_level: string;
  suggested_horizon: string;
  strengths: string[];
  risks: string[];
  rationale: string;
  evidence: Record<string, unknown>;
  model_agreement: number;
  data_quality: number;
  generated_at: string;
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

export interface JobStatus {
  id: string;
  status: "queued" | "running" | "done" | "failed";
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
    computed_at: string;
  } | null;
  kronos: {
    forecast_horizon: string;
    direction: string;
    predicted_return: number;
    confidence: number;
    generated_at: string;
  } | null;
  news: {
    sentiment_score: number;
    confidence: number;
    article_count: number;
    window_start: string;
    window_end: string;
  } | null;
  recommendation: RecommendationCard | null;
}

export interface PortfolioOut {
  method: string;
  allocations: Record<string, number>;
  expected_return: number | null;
  expected_volatility: number | null;
  sharpe: number | null;
  notes: string[];
}
