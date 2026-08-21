"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { NewsArticlesOut, PriceHistoryOut, StockDetail } from "@/lib/types";
import { fmtNum, fmtPct } from "@/lib/format";
import RecommendationBadge from "@/components/RecommendationBadge";
import RiskTierBadge from "@/components/RiskTierBadge";
import PriceHistoryChart from "@/components/charts/PriceHistoryChart";
import ScoreBarChart, { type ScoreBarChartEntry } from "@/components/charts/ScoreBarChart";
import { Panel, Row } from "@/components/ui/Panel";

function sentimentColor(s: number): string {
  if (s > 0.1) return "bg-green-500";
  if (s < -0.1) return "bg-red-500";
  return "bg-slate-400";
}

function StockDetailInner() {
  const params = useParams<{ symbol: string }>();
  const [stock, setStock] = useState<StockDetail | null>(null);
  const [history, setHistory] = useState<PriceHistoryOut | null>(null);
  const [news, setNews] = useState<NewsArticlesOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    api
      .get<StockDetail>(`/api/stocks/${params.symbol}`)
      .then(setStock)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load stock"));
    api
      .get<PriceHistoryOut>(`/api/stocks/${params.symbol}/history`)
      .then(setHistory)
      .catch(() => setHistory(null));
    api
      .get<NewsArticlesOut>(`/api/stocks/${params.symbol}/news`)
      .then(setNews)
      .catch(() => setNews(null));
  }, [params.symbol]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!stock) return <p className="text-sm text-slate-500">Loading...</p>;

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
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{stock.symbol}</h1>
          <p className="text-sm text-slate-500">
            {stock.name} {stock.sector && `· ${stock.sector}`}
          </p>
          <p className="mt-1 text-lg">₹{stock.latest_price?.toFixed(2) ?? "UNKNOWN"}</p>
        </div>
        {rec && (
          <div className="flex flex-col items-end gap-1">
            <RecommendationBadge value={rec.recommendation} />
            <RiskTierBadge value={rec.risk_tier} />
          </div>
        )}
      </div>

      <div className="rounded border bg-white p-4">
        <h3 className="mb-2 font-medium">Price history</h3>
        <PriceHistoryChart points={history?.points ?? []} />
      </div>

      {rec ? (
        <div className="space-y-4 rounded border bg-white p-4">
          <div className="flex gap-6 text-sm text-slate-600">
            <span>Confidence: {(rec.confidence * 100).toFixed(0)}%</span>
            <span>Risk: {rec.risk_level}</span>
            <span>Suggested horizon: {rec.suggested_horizon}</span>
          </div>

          {scoreEntries.length > 0 && (
            <div>
              <h3 className="mb-2 font-medium">Score breakdown</h3>
              <ScoreBarChart entries={scoreEntries} />
            </div>
          )}

          <div>
            <h3 className="font-medium">Why we like it</h3>
            <ul className="mt-1 list-inside list-disc text-sm text-slate-700">
              {rec.strengths.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
              {rec.strengths.length === 0 && <li className="text-slate-400">No strong supporting evidence found.</li>}
            </ul>
          </div>

          <div>
            <h3 className="font-medium">Things to watch</h3>
            <ul className="mt-1 list-inside list-disc text-sm text-slate-700">
              {rec.risks.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
              {rec.risks.length === 0 && <li className="text-slate-400">No specific risks flagged.</li>}
            </ul>
          </div>

          <p className="text-sm italic text-slate-500">{rec.rationale}</p>
        </div>
      ) : (
        <p className="text-sm text-slate-500">No recommendation generated for this stock yet.</p>
      )}

      <div className="rounded border bg-white p-4">
        <h3 className="mb-2 font-medium">News</h3>
        {stock.news && (
          <dl className="mb-3 space-y-1 text-sm">
            <Row label="Sentiment" value={stock.news.sentiment_score.toFixed(2)} />
            <Row label="Confidence" value={fmtPct(stock.news.confidence)} />
            <Row label="Articles (14d)" value={String(stock.news.article_count)} />
          </dl>
        )}
        {news && news.articles.length > 0 ? (
          <ul className="space-y-3">
            {news.articles.map((a) => (
              <li key={a.url} className="flex items-start gap-2 border-t pt-2 first:border-t-0 first:pt-0">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${sentimentColor(a.sentiment)}`} />
                <div className="min-w-0">
                  <a href={a.url} target="_blank" rel="noreferrer" className="text-sm font-medium text-brand-700 hover:underline">
                    {a.title}
                  </a>
                  <p className="text-xs text-slate-500">
                    {a.source} · {new Date(a.published_at).toLocaleDateString("en-IN", { month: "short", day: "numeric" })} ·{" "}
                    <span className="capitalize">{a.event_type}</span>
                  </p>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">No recent articles matched to this stock.</p>
        )}
      </div>

      <button onClick={() => setShowAdvanced((s) => !s)} className="text-sm text-brand-700 underline">
        {showAdvanced ? "Hide" : "Show"} advanced analysis
      </button>

      {showAdvanced && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Panel title="Fundamentals">
            {stock.fundamentals ? (
              <dl className="space-y-1 text-sm">
                <Row label="ROE" value={fmtPct(stock.fundamentals.roe)} />
                <Row label="Revenue growth" value={fmtPct(stock.fundamentals.revenue_growth)} />
                <Row label="Debt/Equity" value={fmtNum(stock.fundamentals.debt_to_equity)} />
                <Row label="P/E" value={fmtNum(stock.fundamentals.pe)} />
                <Row label="Net margin" value={fmtPct(stock.fundamentals.net_margin)} />
                <Row label="Source" value={stock.fundamentals.source} />
              </dl>
            ) : (
              <p className="text-sm text-slate-400">UNKNOWN</p>
            )}
          </Panel>

          <Panel title="Technicals">
            {stock.technicals ? (
              <dl className="space-y-1 text-sm">
                <Row label="Trend" value={stock.technicals.trend ?? "UNKNOWN"} />
                <Row label="RSI (14)" value={fmtNum(stock.technicals.rsi_14)} />
                <Row label="30d volatility" value={fmtPct(stock.technicals.volatility_30d)} />
                <Row label="1y drawdown" value={fmtPct(stock.technicals.drawdown_1y)} />
                <Row label="Beta (vs NIFTY50)" value={fmtNum(stock.technicals.beta)} />
              </dl>
            ) : (
              <p className="text-sm text-slate-400">UNKNOWN</p>
            )}
          </Panel>

          <Panel title="Kronos forecast">
            {stock.kronos ? (
              <dl className="space-y-1 text-sm">
                <Row label="Horizon" value={stock.kronos.forecast_horizon} />
                <Row label="Direction" value={stock.kronos.direction} />
                <Row label="Predicted return" value={fmtPct(stock.kronos.predicted_return)} />
                <Row label="Model confidence" value={fmtPct(stock.kronos.confidence)} />
              </dl>
            ) : (
              <p className="text-sm text-slate-400">No forecast available.</p>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}

export default function StockDetailPage() {
  return <StockDetailInner />;
}
