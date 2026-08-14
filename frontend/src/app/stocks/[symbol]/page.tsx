"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { StockDetail } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import RecommendationBadge from "@/components/RecommendationBadge";

function fmtPct(v: number | null) {
  return v === null || v === undefined ? "UNKNOWN" : `${(v * 100).toFixed(1)}%`;
}
function fmtNum(v: number | null) {
  return v === null || v === undefined ? "UNKNOWN" : v.toFixed(2);
}

function StockDetailInner() {
  const params = useParams<{ symbol: string }>();
  const [stock, setStock] = useState<StockDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    api
      .get<StockDetail>(`/api/stocks/${params.symbol}`)
      .then(setStock)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load stock"));
  }, [params.symbol]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!stock) return <p className="text-sm text-slate-500">Loading...</p>;

  const rec = stock.recommendation;

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
        {rec && <RecommendationBadge value={rec.recommendation} />}
      </div>

      {rec ? (
        <div className="space-y-4 rounded border bg-white p-4">
          <div className="flex gap-6 text-sm text-slate-600">
            <span>Confidence: {(rec.confidence * 100).toFixed(0)}%</span>
            <span>Risk: {rec.risk_level}</span>
            <span>Suggested horizon: {rec.suggested_horizon}</span>
          </div>

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

          <Panel title="News sentiment">
            {stock.news ? (
              <dl className="space-y-1 text-sm">
                <Row label="Sentiment" value={stock.news.sentiment_score.toFixed(2)} />
                <Row label="Confidence" value={fmtPct(stock.news.confidence)} />
                <Row label="Articles (14d)" value={String(stock.news.article_count)} />
              </dl>
            ) : (
              <p className="text-sm text-slate-400">No recent news matched.</p>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border bg-white p-4">
      <h3 className="mb-2 font-medium">{title}</h3>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

export default function StockDetailPage() {
  return (
    <RequireAuth>
      <StockDetailInner />
    </RequireAuth>
  );
}
