"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { motion } from "framer-motion";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { NewsArticlesOut, PriceHistoryOut, StockDetail } from "@/lib/types";
import { fmtNum, fmtPct } from "@/lib/format";
import { useApiData } from "@/lib/useApiData";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import RecommendationBadge from "@/components/RecommendationBadge";
import RiskTierBadge from "@/components/RiskTierBadge";
import CandlestickChart from "@/components/charts/CandlestickChart";
import ScoreBarChart, { type ScoreBarChartEntry } from "@/components/charts/ScoreBarChart";
import KronosHorizonChart from "@/components/charts/KronosHorizonChart";
import CouncilTranscript from "@/components/charts/CouncilTranscript";
import NewsSentimentTimeline from "@/components/charts/NewsSentimentTimeline";
import { Panel, Row } from "@/components/ui/Panel";
import Card from "@/components/ui/Card";
import RiskGauge from "@/components/ui/RiskGauge";
import ProgressBar from "@/components/ui/ProgressBar";
import { SkeletonCard, SkeletonChart } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";

const CONFIDENCE_BAND_CLASS: Record<string, string> = {
  high: "bg-positive-subtle text-positive",
  medium: "bg-warning-subtle text-warning",
  low: "bg-negative-subtle text-negative",
};

function sentimentColor(s: number): string {
  if (s > 0.1) return "bg-positive";
  if (s < -0.1) return "bg-negative";
  return "bg-text-muted";
}

function StockDetailInner() {
  const params = useParams<{ symbol: string }>();
  const { data: stock, error } = useApiData<StockDetail>(`/api/stocks/${params.symbol}`, [params.symbol]);
  const { data: history } = useApiData<PriceHistoryOut>(`/api/stocks/${params.symbol}/history`, [params.symbol]);
  const { data: news } = useApiData<NewsArticlesOut>(`/api/stocks/${params.symbol}/news`, [params.symbol]);
  const [showAdvanced, setShowAdvanced] = useState(false);

  if (error) return <EmptyState icon={ChevronDown} title="Could not load this stock" message={error} />;
  if (!stock) {
    return (
      <div className="space-y-4">
        <SkeletonCard className="h-24" />
        <SkeletonChart />
      </div>
    );
  }

  const rec = stock.recommendation;
  const scoreEntries: ScoreBarChartEntry[] = rec
    ? [
        { label: "Fundamental", value: rec.fundamental_score },
        { label: "Technical", value: rec.technical_score },
        { label: "Kronos", value: rec.kronos_score },
        { label: "News", value: rec.news_score },
        { label: "Portfolio", value: rec.portfolio_score },
        { label: "Risk fit", value: rec.risk_score },
      ].filter((e): e is ScoreBarChartEntry => e.value !== null)
    : [];

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp} className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text-primary">{stock.symbol}</h1>
          <p className="text-sm text-text-muted">
            {stock.name} {stock.sector && `· ${stock.sector}`}
          </p>
          <p className="mt-1 text-lg text-text-primary">₹{stock.latest_price?.toFixed(2) ?? "UNKNOWN"}</p>
          {stock.price_as_of && (
            <p className="text-xs text-text-muted">as of {new Date(stock.price_as_of).toLocaleString()}</p>
          )}
        </div>
        {rec && (
          <div className="flex flex-col items-end gap-1">
            <RecommendationBadge value={rec.recommendation} />
            <RiskTierBadge value={rec.risk_tier} />
            <p className="text-xs text-text-muted">
              recommendation generated {new Date(rec.generated_at).toLocaleString()}
            </p>
            {stock.evidence_is_legacy && (
              <p className="text-xs text-warning">
                legacy report -- evidence below is most-recent, not pinned to what this recommendation saw
              </p>
            )}
          </div>
        )}
      </motion.div>

      {/* Each panel below (price, fundamentals, technicals, kronos, recommendation)
          is independently fetched at its own latest vintage -- they are not
          guaranteed to be from the same moment (docs/V2-RETHINK.md P1). Every
          "as of" timestamp here is shown explicitly rather than presenting the
          page as one coherent snapshot. */}

      <motion.div variants={fadeInUp}>
        <Card title="Price history">
          <CandlestickChart points={history?.points ?? []} forecasts={stock.kronos_horizons} />
        </Card>
      </motion.div>

      {rec ? (
        <motion.div variants={fadeInUp}>
          <Card>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-text-muted">
              {/* Deterministic heuristic (signal agreement + evidence coverage),
                  not a calibrated probability of correctness (docs/V2-RETHINK.md P1). */}
              <span>Confidence (heuristic): {(rec.confidence * 100).toFixed(0)}%</span>
              {rec.confidence_band && (
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${CONFIDENCE_BAND_CLASS[rec.confidence_band]}`}>
                  {rec.confidence_band} confidence
                </span>
              )}
              <span>Risk: {rec.risk_level}</span>
              <span>Suggested horizon: {rec.suggested_horizon}</span>
            </div>

            {scoreEntries.length > 0 && (
              <div className="mt-4">
                <h3 className="mb-2 font-medium text-text-primary">Score breakdown</h3>
                <ScoreBarChart entries={scoreEntries} />
              </div>
            )}

            <div className="mt-4">
              <h3 className="font-medium text-text-primary">Why we like it</h3>
              <ul className="mt-1 list-inside list-disc text-sm text-text-muted">
                {rec.strengths.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
                {rec.strengths.length === 0 && <li className="text-text-muted/60">No strong supporting evidence found.</li>}
              </ul>
            </div>

            <div className="mt-4">
              <h3 className="font-medium text-text-primary">Things to watch</h3>
              <ul className="mt-1 list-inside list-disc text-sm text-text-muted">
                {rec.risks.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
                {rec.risks.length === 0 && <li className="text-text-muted/60">No specific risks flagged.</li>}
              </ul>
            </div>

            <p className="mt-4 text-sm italic text-text-muted">{rec.rationale}</p>
          </Card>
        </motion.div>
      ) : (
        <motion.div variants={fadeInUp}>
          <EmptyState icon={ChevronDown} title="No recommendation generated for this stock yet" />
        </motion.div>
      )}

      {rec?.risk_tier_score !== null && rec?.risk_tier_score !== undefined && (
        <motion.div variants={fadeInUp}>
          <Card title="Objective risk tier">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <RiskGauge value={Math.round(rec.risk_tier_score)} label="Riskiness (0=safer, 100=riskiest)" tone="tier" />
              {rec.risk_tier_breakdown && (
                <div className="flex-1 space-y-1.5">
                  {Object.entries(rec.risk_tier_breakdown).map(([k, v]) => (
                    <ProgressBar key={k} label={k.replace(/_/g, " ")} value={v as number} colorClass="bg-text-muted" />
                  ))}
                </div>
              )}
            </div>
          </Card>
        </motion.div>
      )}

      <motion.div variants={fadeInUp}>
        <Card title="Forecast comparison (Kronos)">
          <KronosHorizonChart horizons={stock.kronos_horizons} />
        </Card>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="Council reasoning">
          <CouncilTranscript outputs={rec?.council_outputs ?? []} />
        </Card>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="News">
          {stock.news && (
            <dl className="mb-3 space-y-1 text-sm">
              <Row label="Sentiment" value={stock.news.sentiment_score.toFixed(2)} />
              <Row label="Confidence" value={fmtPct(stock.news.confidence)} />
              <Row label="Articles (14d)" value={String(stock.news.article_count)} />
            </dl>
          )}
          {news && news.articles.length > 0 ? (
            <>
              <NewsSentimentTimeline articles={news.articles} />
              <ul className="mt-3 space-y-3">
                {news.articles.map((a) => (
                  <li key={a.url} className="flex items-start gap-2 border-t border-border pt-2 first:border-t-0 first:pt-0">
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${sentimentColor(a.sentiment)}`} />
                    <div className="min-w-0">
                      <a href={a.url} target="_blank" rel="noreferrer" className="text-sm font-medium text-accent hover:underline">
                        {a.title}
                      </a>
                      <p className="text-xs text-text-muted">
                        {a.source} · {new Date(a.published_at).toLocaleDateString("en-IN", { month: "short", day: "numeric" })} ·{" "}
                        <span className="capitalize">{a.event_type}</span>
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-text-muted">No recent articles matched to this stock.</p>
          )}
        </Card>
      </motion.div>

      <motion.button
        variants={fadeInUp}
        onClick={() => setShowAdvanced((s) => !s)}
        className="flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover"
      >
        {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        {showAdvanced ? "Hide" : "Show"} advanced analysis
      </motion.button>

      {showAdvanced && (
        <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <motion.div variants={fadeInUp}>
            <Panel title="Fundamentals">
              {stock.fundamentals ? (
                <dl className="space-y-1 text-sm">
                  <Row label="ROE" value={fmtPct(stock.fundamentals.roe)} />
                  <Row label="Revenue growth" value={fmtPct(stock.fundamentals.revenue_growth)} />
                  <Row label="Debt/Equity" value={fmtNum(stock.fundamentals.debt_to_equity)} />
                  <Row label="P/E" value={fmtNum(stock.fundamentals.pe)} />
                  <Row label="Net margin" value={fmtPct(stock.fundamentals.net_margin)} />
                  <Row label="Source" value={stock.fundamentals.source} />
                  <Row label="As of" value={stock.fundamentals.as_of_date} />
                </dl>
              ) : (
                <p className="text-sm text-text-muted">UNKNOWN</p>
              )}
            </Panel>
          </motion.div>

          <motion.div variants={fadeInUp}>
            <Panel title="Technicals">
              {stock.technicals ? (
                <dl className="space-y-1 text-sm">
                  <Row label="Trend" value={stock.technicals.trend ?? "UNKNOWN"} />
                  <Row label="RSI (14)" value={fmtNum(stock.technicals.rsi_14)} />
                  <Row label="30d volatility" value={fmtPct(stock.technicals.volatility_30d)} />
                  <Row label="1y drawdown" value={fmtPct(stock.technicals.drawdown_1y)} />
                  <Row label="Beta (vs NIFTY50)" value={fmtNum(stock.technicals.beta)} />
                  <Row label="SMA 20 / 50 / 200" value={`${fmtNum(stock.technicals.sma_20)} / ${fmtNum(stock.technicals.sma_50)} / ${fmtNum(stock.technicals.sma_200)}`} />
                  <Row label="Bollinger band" value={`${fmtNum(stock.technicals.bb_lower)} – ${fmtNum(stock.technicals.bb_upper)}`} />
                  <Row label="Computed" value={new Date(stock.technicals.computed_at).toLocaleString()} />
                </dl>
              ) : (
                <p className="text-sm text-text-muted">UNKNOWN</p>
              )}
            </Panel>
          </motion.div>

          <motion.div variants={fadeInUp}>
            <Panel title="Kronos forecast (30d)">
              {stock.kronos ? (
                <dl className="space-y-1 text-sm">
                  <Row label="Horizon" value={stock.kronos.forecast_horizon} />
                  <Row label="Direction" value={stock.kronos.direction} />
                  <Row label="Predicted return" value={fmtPct(stock.kronos.predicted_return)} />
                  <Row label="Model confidence" value={stock.kronos.confidence == null ? "not yet calibrated" : fmtPct(stock.kronos.confidence)} />
                  <Row label="Generated" value={new Date(stock.kronos.generated_at).toLocaleString()} />
                </dl>
              ) : (
                <p className="text-sm text-text-muted">No forecast available.</p>
              )}
            </Panel>
          </motion.div>
        </motion.div>
      )}
    </motion.div>
  );
}

export default function StockDetailPage() {
  return <StockDetailInner />;
}
