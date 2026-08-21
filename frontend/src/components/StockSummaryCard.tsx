import type { StockDetail } from "@/lib/types";
import { fmtNum, fmtPct } from "@/lib/format";
import RecommendationBadge from "@/components/RecommendationBadge";
import RiskTierBadge from "@/components/RiskTierBadge";
import ScoreBarChart, { type ScoreBarChartEntry } from "@/components/charts/ScoreBarChart";
import { Panel, Row } from "@/components/ui/Panel";

/** Compact per-stock card for side-by-side comparison -- a smaller subset of
 * what /stocks/[symbol] shows in full (no price chart, no news, no
 * strengths/risks prose). */
export default function StockSummaryCard({ stock }: { stock: StockDetail }) {
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
    <div className="space-y-3 rounded border bg-white p-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">{stock.symbol}</h2>
          <p className="text-xs text-slate-500">
            {stock.name} {stock.sector && `· ${stock.sector}`}
          </p>
          <p className="mt-1 text-sm">₹{stock.latest_price?.toFixed(2) ?? "UNKNOWN"}</p>
        </div>
        {rec && (
          <div className="flex flex-col items-end gap-1">
            <RecommendationBadge value={rec.recommendation} />
            <RiskTierBadge value={rec.risk_tier} />
          </div>
        )}
      </div>

      {scoreEntries.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-medium">Score breakdown</h3>
          <ScoreBarChart entries={scoreEntries} />
        </div>
      )}

      <Panel title="Fundamentals">
        {stock.fundamentals ? (
          <dl className="space-y-1 text-sm">
            <Row label="ROE" value={fmtPct(stock.fundamentals.roe)} />
            <Row label="P/E" value={fmtNum(stock.fundamentals.pe)} />
            <Row label="Debt/Equity" value={fmtNum(stock.fundamentals.debt_to_equity)} />
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
          </dl>
        ) : (
          <p className="text-sm text-slate-400">UNKNOWN</p>
        )}
      </Panel>
    </div>
  );
}
