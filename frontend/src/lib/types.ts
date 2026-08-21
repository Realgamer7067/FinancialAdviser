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
  risk_tier: "safer" | "moderate" | "risky" | "riskiest" | null;
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
    beta: number | null;
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
  sectors: Record<string, string | null>;
  expected_return: number | null;
  expected_volatility: number | null;
  sharpe: number | null;
  notes: string[];
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
  close: number;
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
