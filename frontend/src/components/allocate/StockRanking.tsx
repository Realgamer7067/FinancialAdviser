"use client";

import { useState } from "react";
import Link from "next/link";
import type { V4RankRow, V4StockRanking } from "@/lib/types";
import Card from "@/components/ui/Card";

const STATUS: Record<V4RankRow["status"], { label: string; tone: string }> = {
  picked: { label: "In this plan", tone: "bg-positive-subtle text-positive" },
  candidate: { label: "Candidate", tone: "bg-positive-subtle text-positive" },
  not_picked: { label: "Not picked", tone: "bg-bg text-text-muted" },
  excluded: { label: "Left out", tone: "bg-warning-subtle text-warning" },
  below_floor: { label: "Below the floor", tone: "bg-negative-subtle text-negative" },
  not_ranked: { label: "Not ranked", tone: "bg-bg text-text-muted" },
};
const MEASURE: Record<string, string> = {
  earnings_yield: "Earnings yield", ebitda_ev: "EBITDA / EV", book_yield: "Book yield", fcf_yield: "FCF yield", roe: "Return on equity", net_margin: "Net margin", ebitda_margin: "EBITDA margin",
  eps_growth: "Earnings growth", revenue_growth: "Revenue growth", debt_to_equity: "Debt / equity", cash_profitability: "Cash profitability", accruals: "Accruals", payout: "Dividend payout", mom_12_1: "12-1 month return", mom_6_1: "6-1 month return",
};
const PCT_MEASURES = new Set(["earnings_yield", "ebitda_ev", "book_yield", "fcf_yield", "roe", "net_margin", "ebitda_margin", "eps_growth", "revenue_growth", "cash_profitability", "accruals", "payout", "mom_12_1", "mom_6_1"]);
const fmtMeasure = (m: string, v: number) => (PCT_MEASURES.has(m) ? `${(v * 100).toFixed(1)}%` : v.toFixed(2));
const pct = (v: number | null | undefined, d = 0) => (v == null ? "n/a" : `${(v * 100).toFixed(d)}%`);
const SHOWN = 12;

function Bar({ score, floor }: { score: number | null; floor: number }) {
  if (score == null) return <span className="text-text-muted">n/a</span>;
  return (
    <span className="inline-flex items-center gap-2" role="img" aria-label={`Score ${score.toFixed(0)} out of 100`}>
      <span className="relative h-1.5 w-14 rounded bg-border">
        <span className={`absolute inset-y-0 left-0 rounded ${score >= floor ? "bg-accent" : "bg-text-muted"}`} style={{ width: `${score}%` }} />
        <span aria-hidden className="absolute -top-0.5 h-2.5 w-px bg-text-muted" style={{ left: `${floor}%` }} />
      </span>
      <span className="tabular-nums text-text-primary">{score.toFixed(0)}</span>
    </span>
  );
}

function Detail({ r, floor }: { r: V4RankRow; floor: number }) {
  return (
    <div className="space-y-3 border-t border-border bg-bg/40 p-3 text-sm">
      <p className="text-text-muted">{r.note} <Link href={`/market/${r.security_id}`} className="font-medium text-accent hover:text-accent-hover">Open {r.symbol} in Market</Link></p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-xs font-medium text-positive">What counts for it</p>
          {r.strengths.length ? <ul className="list-inside list-disc text-xs text-text-primary">{r.strengths.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="text-xs text-text-muted">No measure stands out.</p>}
        </div>
        <div>
          <p className="text-xs font-medium text-negative">What counts against it</p>
          {r.weaknesses.length ? <ul className="list-inside list-disc text-xs text-text-primary">{r.weaknesses.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="text-xs text-text-muted">No clear weakness among the measures used.</p>}
        </div>
      </div>
      {(["value", "quality", "momentum"] as const).map((k) => {
        const c = r.components[k];
        return (
          <div key={k}>
            <p className="text-xs font-medium text-text-primary">
              <span className="capitalize">{k}</span> {c.score == null ? "(not usable)" : `${c.score.toFixed(0)}`} <span className="font-normal text-text-muted">· {c.measures_used} of {c.measures_possible} measures{k === "momentum" && r.momentum_basis ? `, on ${r.momentum_basis.replace("_", " ")}` : ""}</span>
            </p>
            <ul className="mt-0.5 grid gap-x-4 text-xs text-text-muted sm:grid-cols-2">
              {Object.entries(c.measures).map(([m, g]) => <li key={m}>{MEASURE[m] ?? m} {fmtMeasure(m, g.value)} <span className="text-text-muted">· beats {g.percentile.toFixed(0)}% of {g.peers >= 3 ? "peers" : "the group"}</span></li>)}
            </ul>
            {c.missing.length > 0 && <p className="text-xs text-warning">Missing: {c.missing.map((m) => MEASURE[m] ?? m).join(", ")}.</p>}
          </div>
        );
      })}
      {r.flags.map((f) => <p key={f} className="text-xs text-warning">Data note: {f}</p>)}
      <p className="text-xs text-text-muted">
        <strong className="text-text-primary">Risk, beside the rank (not scored):</strong>{" "}
        volatility {pct(r.risk.vol_252)} a year · worst fall in the year {pct(r.risk.max_dd_1y)} · traded about {r.risk.liquidity_value ? `₹${(r.risk.liquidity_value / 1e7).toFixed(0)} crore` : "n/a"} a day.
        {" "}Data: fundamentals as of {r.dates.fundamentals_as_of ?? "unknown"}, price as of {r.dates.price_as_of ?? "unknown"}. Coverage {Math.round(r.coverage * 100)}%. Rank {r.rank ?? "none"} of {r.rank_of}; floor {floor.toFixed(0)}.
      </p>
      {r.fit && <p className="text-xs text-text-muted"><strong className="text-text-primary">What you already hold:</strong> {r.fit.note}.</p>}
      {r.cost && (
        <p className="text-xs text-text-muted">
          <strong className="text-text-primary">Estimated cost:</strong> {r.cost.units} units at ₹{r.cost.price} = ₹{Number(r.cost.trade_value).toLocaleString("en-IN")}, plus about ₹{r.cost.assumed_charges} in assumed charges, so ₹{Number(r.cost.planned_debit).toLocaleString("en-IN")} in all. {r.cost.note}.
        </p>
      )}
    </div>
  );
}

export default function StockRanking({ ranking, loading, error }: { ranking: V4StockRanking | null; loading: boolean; error: string | null }) {
  const [all, setAll] = useState(false);
  if (error) return <Card title="Stock ranking"><p role="alert" className="text-sm text-negative">Could not load the ranking: {error}</p></Card>;
  if (loading || !ranking) return <Card title="Stock ranking"><p aria-busy="true" className="text-sm text-text-muted">Ranking the Nifty 50…</p></Card>;
  const top = ranking.rows.filter((r) => r.status === "picked" || r.status === "candidate" || r.status === "not_picked" || r.status === "excluded");
  const below = ranking.rows.filter((r) => r.status === "below_floor");
  const unranked = ranking.rows.filter((r) => r.status === "not_ranked");
  const w = ranking.weights;
  const rb = ranking.risk_beside_rank;

  return (
    <Card title="Stock ranking: value, quality and momentum">
      <p className="text-sm text-text-muted">{ranking.policy_note}</p>
      <p className="mt-2 text-xs text-text-muted">
        Weights: value {Math.round(w.value * 100)}%, quality {Math.round(w.quality * 100)}%, momentum {Math.round(w.momentum * 100)}% (equal by default, set in the configuration, not optimised). Floor {ranking.floor.toFixed(0)}. Fundamentals as of {ranking.fundamentals_as_of.newest ?? "unknown"}.
        Momentum uses total return, 12-1 and 6-1 averaged into one vote. Each measure is ranked against comparable companies; banks, NBFCs and insurers form their own group. <Link href="/scorecard" className="underline">Model evidence</Link>
      </p>
      <p className="mt-2 text-xs text-text-muted">{ranking.selection_rule}</p>
      {ranking.no_stock_reason && <p role="status" className="mt-2 rounded-md border border-border bg-bg p-2 text-sm text-text-primary">No direct stock in this plan: {ranking.no_stock_reason}.</p>}
      {ranking.inactive_note && <p className="mt-2 text-xs text-warning">{ranking.inactive_note}</p>}
      {ranking.momentum_caution && ranking.momentum_caution.state !== "unknown" && (
        <p role={ranking.momentum_caution.state === "elevated" ? "status" : undefined} className={`mt-2 text-xs ${ranking.momentum_caution.state === "elevated" ? "rounded-md border border-warning bg-warning-subtle p-2 text-warning" : "text-text-muted"}`}>
          Market state for momentum: {ranking.momentum_caution.state}. Nifty 50 {ranking.momentum_caution.market_2y !== null ? `${ranking.momentum_caution.market_2y >= 0 ? "+" : ""}${(ranking.momentum_caution.market_2y * 100).toFixed(0)}% over two years, ${(ranking.momentum_caution.market_1m ?? 0) >= 0 ? "+" : ""}${((ranking.momentum_caution.market_1m ?? 0) * 100).toFixed(0)}% over the last month` : ""}. {ranking.momentum_caution.note}
        </p>
      )}

      <ul className="mt-3 divide-y divide-border rounded-md border border-border">
        {(all ? top : top.slice(0, SHOWN)).map((r) => (
          <li key={r.symbol}>
            <details className="group">
              <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-1 p-2.5 hover:bg-bg">
                <span className="w-8 text-xs tabular-nums text-text-muted">#{r.rank ?? "-"}</span>
                <span className="min-w-[7rem] flex-1">
                  <span className="font-medium text-text-primary">{r.symbol}</span>
                  <span className="block max-w-[12rem] truncate text-xs text-text-muted sm:max-w-xs" title={r.name}>{r.sector}</span>
                </span>
                <Bar score={r.composite} floor={ranking.floor} />
                <span className="hidden gap-3 text-xs tabular-nums text-text-muted md:flex">
                  <span>V {r.components.value.score?.toFixed(0) ?? "n/a"}</span><span>Q {r.components.quality.score?.toFixed(0) ?? "n/a"}</span><span>M {r.components.momentum.score?.toFixed(0) ?? "n/a"}</span>
                </span>
                <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS[r.status].tone}`}>{STATUS[r.status].label}</span>
              </summary>
              <Detail r={r} floor={ranking.floor} />
            </details>
          </li>
        ))}
      </ul>
      {top.length > SHOWN && (
        <button type="button" onClick={() => setAll((a) => !a)} aria-expanded={all} className="mt-2 text-sm font-medium text-accent hover:text-accent-hover">{all ? "Show fewer" : `Show all ${top.length} candidates and others above the floor`}</button>
      )}

      {rb && rb.status === "ready" && (
        <section aria-label="Risk of the proposed stocks together" className="mt-4 rounded-md border border-border bg-bg p-3">
          <h3 className="text-sm font-medium text-text-primary">The proposed stocks together</h3>
          <p className="mt-1 text-xs text-text-muted">
            Held in equal parts they have moved with about {pct(rb.equal_weight_volatility, 1)} yearly volatility and an average correlation of {rb.average_pairwise_correlation?.toFixed(2)} between them (shrunk covariance, {rb.returns_used} days). {rb.note}
          </p>
          {rb.average_correlation_with_held && Object.keys(rb.average_correlation_with_held).length > 0 && (
            <p className="mt-1 text-xs text-text-muted">Average correlation with the stocks you hold: {Object.entries(rb.average_correlation_with_held).map(([s, c]) => `${s} ${c.toFixed(2)}`).join(", ")}.</p>
          )}
          {(rb.warnings ?? []).map((x) => <p key={x} className="mt-1 text-xs text-warning">{x}.</p>)}
        </section>
      )}

      {below.length > 0 && (
        <details className="mt-4 rounded-md border border-border p-3">
          <summary className="cursor-pointer text-sm font-medium text-text-primary">Below the floor, not candidates for new money ({below.length})</summary>
          <p className="mt-1 text-xs text-text-muted">A statement about how these rank today on the three components, not a prediction and never a reason to sell one you hold: this app does not suggest sales.</p>
          <ul className="mt-2 space-y-3">
            {below.map((r) => (
              <li key={r.symbol} className="text-sm">
                <p className="flex flex-wrap items-center gap-2"><Link href={`/market/${r.security_id}`} className="font-medium text-text-primary hover:underline">{r.symbol}</Link><span className="text-xs text-text-muted">#{r.rank} · {r.sector}</span><Bar score={r.composite} floor={ranking.floor} /></p>
                {r.weaknesses.length > 0 ? <ul className="list-inside list-disc text-xs text-text-primary">{r.weaknesses.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="text-xs text-text-muted">{r.note}</p>}
                {r.flags.map((f) => <p key={f} className="text-xs text-warning">Data note: {f}</p>)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {unranked.length > 0 && <p className="mt-3 text-xs text-text-muted">Not ranked, because a whole component could not be built from the data: {unranked.map((r) => `${r.symbol} (${r.note?.replace("not ranked: ", "")})`).join("; ")}.</p>}
      <p className="mt-4 rounded-md border border-border bg-bg p-2 text-xs text-text-muted">{ranking.safety_note}</p>
    </Card>
  );
}
