"use client";

import { useState } from "react";
import Link from "next/link";
import type { V4StockScreen, V4StockScreenRow } from "@/lib/types";
import Card from "@/components/ui/Card";

const STATUS: Record<V4StockScreenRow["status"], { label: string; tone: string }> = {
  picked: { label: "In this plan", tone: "bg-positive-subtle text-positive" },
  top_in_sector: { label: "Top in its sector", tone: "bg-positive-subtle text-positive" },
  not_picked: { label: "Not picked", tone: "bg-bg text-text-muted" },
  low_score: { label: "Scores low", tone: "bg-negative-subtle text-negative" },
  not_scored: { label: "Not scored", tone: "bg-bg text-text-muted" },
};
const COMPONENT_LABEL: Record<string, string> = { valuation: "Valuation", quality: "Quality", balance: "Debt", risk: "Risk" };
const num = (v: number | null, d = 1) => (v == null ? "n/a" : v.toFixed(d));

function Bar({ score, floor }: { score: number | null; floor: number }) {
  if (score == null) return <span className="text-text-muted">n/a</span>;
  return (
    <span className="inline-flex items-center gap-2" role="img" aria-label={`Score ${score.toFixed(0)} out of 100`}>
      <span className="relative h-1.5 w-16 rounded bg-border">
        <span className={`absolute inset-y-0 left-0 rounded ${score >= floor ? "bg-accent" : "bg-negative"}`} style={{ width: `${score}%` }} />
        <span aria-hidden className="absolute -top-0.5 h-2.5 w-px bg-text-muted" style={{ left: `${floor}%` }} />
      </span>
      <span className="tabular-nums text-text-primary">{score.toFixed(0)}</span>
    </span>
  );
}

const SHOWN = 12;

export default function StockChecklist({ screen, loading, error }: { screen: V4StockScreen | null; loading: boolean; error: string | null }) {
  const [all, setAll] = useState(false);
  if (error) return <Card title="Stock checklist"><p role="alert" className="text-sm text-negative">Could not load the checklist: {error}</p></Card>;
  if (loading || !screen) return <Card title="Stock checklist"><p aria-busy="true" className="text-sm text-text-muted">Scoring the Nifty 50…</p></Card>;
  const low = screen.rows.filter((r) => r.status === "low_score");
  const unscored = screen.rows.filter((r) => r.status === "not_scored");
  const main = screen.rows.filter((r) => r.status !== "low_score" && r.status !== "not_scored");
  const stale = screen.fundamentals_as_of.newest;

  return (
    <Card title="Stock checklist: how the Nifty 50 scores">
      <p className="text-sm text-text-muted">{screen.note}</p>
      <p className="mt-2 text-xs text-text-muted">
        Fundamentals as of {stale ?? "unknown"} (the provider cannot be refreshed from this connection, so P/E uses today&apos;s price over that earnings figure). Weights: valuation {screen.weights.valuation}, quality {screen.weights.quality}, debt {screen.weights.balance}, risk {screen.weights.risk}.
        The line on each bar is the floor ({screen.floor}). Unreviewed placeholders. <Link href="/scorecard" className="underline">Model evidence</Link>
      </p>

      <div tabIndex={0} className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Nifty 50 stocks by checklist score</caption>
          <thead className="text-xs text-text-muted">
            <tr>
              <th scope="col" className="py-1.5 pr-3 font-medium">Stock</th>
              <th scope="col" className="py-1.5 pr-3 font-medium">Score</th>
              <th scope="col" className="hidden py-1.5 pr-3 text-right font-medium md:table-cell">P/E</th>
              <th scope="col" className="hidden py-1.5 pr-3 text-right font-medium md:table-cell">Return on equity</th>
              <th scope="col" className="hidden py-1.5 pr-3 text-right font-medium lg:table-cell">Debt / equity</th>
              <th scope="col" className="py-1.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {(all ? main : main.slice(0, SHOWN)).map((r) => (
              <tr key={r.symbol} className="border-t border-border align-top">
                <td className="py-1.5 pr-3">
                  <Link href={`/market/${r.security_id}`} className="font-medium text-text-primary hover:text-accent hover:underline">{r.symbol}</Link>
                  <p className="max-w-[10rem] truncate text-xs text-text-muted sm:max-w-xs" title={r.name}>{r.sector}</p>
                </td>
                <td className="py-1.5 pr-3"><Bar score={r.score} floor={screen.floor} /></td>
                <td className="hidden py-1.5 pr-3 text-right tabular-nums md:table-cell">{num(r.pe)}</td>
                <td className="hidden py-1.5 pr-3 text-right tabular-nums md:table-cell">{r.roe == null ? "n/a" : `${(r.roe * 100).toFixed(0)}%`}</td>
                <td className="hidden py-1.5 pr-3 text-right tabular-nums lg:table-cell">{r.financial ? "not used" : num(r.debt_to_equity, 2)}</td>
                <td className="py-1.5"><span className={`rounded-full px-2 py-0.5 text-xs ${STATUS[r.status].tone}`}>{STATUS[r.status].label}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {main.length > SHOWN && (
        <button type="button" onClick={() => setAll((a) => !a)} aria-expanded={all} className="mt-2 text-sm font-medium text-accent hover:text-accent-hover">
          {all ? "Show fewer" : `Show all ${main.length} scored stocks`}
        </button>
      )}

      {low.length > 0 && (
        <section aria-label="Stocks that score low" className="mt-5 rounded-md border border-negative/40 bg-negative-subtle p-3">
          <h3 className="text-sm font-medium text-negative">Score low, so not picked for new money ({low.length})</h3>
          <p className="mt-1 text-xs text-text-muted">This is a statement about how these look on the checklist today, not a prediction and never a reason to sell one you hold: this app does not suggest sales.</p>
          <ul className="mt-3 space-y-3">
            {low.map((r) => (
              <li key={r.symbol} className="text-sm">
                <p className="flex flex-wrap items-center gap-2">
                  <Link href={`/market/${r.security_id}`} className="font-medium text-text-primary hover:underline">{r.symbol}</Link>
                  <span className="text-xs text-text-muted">{r.sector}</span>
                  <Bar score={r.score} floor={screen.floor} />
                </p>
                <p className="text-xs text-text-muted">
                  {Object.entries(r.components).filter(([, v]) => v != null).map(([k, v]) => `${COMPONENT_LABEL[k] ?? k} ${Math.round(v as number)}`).join(" · ")}
                </p>
                {r.reasons.length > 0 ? <ul className="list-inside list-disc text-xs text-text-primary">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="text-xs text-text-muted">{r.note}</p>}
                {r.flags.map((f) => <p key={f} className="text-xs text-warning">Data note: {f}</p>)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {unscored.length > 0 && (
        <p className="mt-4 text-xs text-text-muted">Not scored for lack of data: {unscored.map((r) => `${r.symbol} (${r.note})`).join("; ")}.</p>
      )}
    </Card>
  );
}
