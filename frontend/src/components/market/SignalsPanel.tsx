"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4Family, V4SecuritySignals } from "@/lib/types";

const pct = (v: number | null | undefined, d = 1) => (v == null ? "n/a" : `${(v * 100).toFixed(d)}%`);
const signed = (v: number | null | undefined) => (v == null ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const STATE_LABEL: Record<string, string> = { positive: "Positive", negative: "Negative", mixed: "Mixed", unavailable: "Not enough clean history", ok: "Fine", thin: "Thin", unknown: "Unknown" };
const QUALITY: Record<string, string> = {
  insufficient_data: "Less than a year of price history, so the one-year measures are not shown.",
  stale: "The newest stored price is out of date, so these are not ranked.",
  unreliable_window: "A corporate action in the last year was not adjusted automatically, so these are not ranked.",
};

function Family({ title, f, hint }: { title: string; f: V4Family; hint: string }) {
  return (
    <div className="rounded border border-border p-2">
      <p className="text-xs font-medium text-text-primary">{title}: <span className={f.state === "positive" ? "text-positive" : f.state === "negative" ? "text-negative" : "text-text-muted"}>{STATE_LABEL[f.state] ?? f.state}</span></p>
      <p className="text-xs text-text-muted">{f.text}</p>
      <p className="mt-1 text-[11px] text-text-muted">{hint}</p>
    </div>
  );
}

export default function SignalsPanel({ id }: { id: string }) {
  const [s, setS] = useState<V4SecuritySignals | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.get<V4SecuritySignals>(`/api/v4/catalogue/securities/${id}/signals`).then(setS).catch((e) => setErr(e instanceof ApiError ? e.message : "Could not load signals")); }, [id]);

  if (err) return <p role="alert" className="text-sm text-negative">{err}</p>;
  if (!s) return null;
  if (s.status === "none" || !s.latest) return <p className="text-sm text-text-muted">{s.message ?? "No signals stored yet."}</p>;
  const l = s.latest, f = s.families, fc = s.forecast;
  return (
    <section aria-label="Signals" className="space-y-2">
      <p className="text-xs font-medium text-text-primary">What its price history says (as of {l.as_of}; descriptions, not predictions)</p>
      {QUALITY[l.quality] && <p className="rounded border border-warning p-2 text-xs text-warning">{QUALITY[l.quality]}{l.detail?.reasons?.length ? ` (${l.detail.reasons.join("; ")})` : ""}</p>}
      {f && (
        <div className="grid gap-2 sm:grid-cols-3">
          <Family title="Trend" f={f.trend} hint="Price against its 200-day average, and 12-1 month momentum. These two move together, so they are one check, not two." />
          <Family title="Risk" f={f.risk} hint="How jumpy its price has been over the last year (volatility only: distance from the 52-week high is shown below but is not counted, because it just repeats the trend)." />
          <Family title="Tradability" f={f.liquidity} hint="A filter, not a vote: can a small order go through without moving the price?" />
        </div>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-text-muted sm:grid-cols-4">
        <div><dt>vs 200-day average</dt><dd className="text-text-primary">{signed(l.sma200_ratio)}</dd></div>
        <div><dt>12-1 month return</dt><dd className="text-text-primary">{signed(l.mom_12_1)}{l.mom_12_1_rank != null ? ` (stronger than ${l.mom_12_1_rank.toFixed(0)}% of ${l.rank_universe_size} peers)` : ""}</dd></div>
        <div><dt>Volatility, 1 yr / 60 days</dt><dd className="text-text-primary">{pct(l.vol_252)} / {pct(l.vol_60)}</dd></div>
        <div><dt>From 52-week high</dt><dd className="text-text-primary">{signed(l.drawdown_current)}</dd></div>
        <div><dt>Worst fall in the last year</dt><dd className="text-text-primary">{signed(l.max_dd_1y)}</dd></div>
        <div><dt>Median daily turnover</dt><dd className="text-text-primary">{l.liquidity_value == null ? "n/a" : `₹${(l.liquidity_value / 1e7).toFixed(2)} crore`}</dd></div>
        <div><dt>Locked-at-limit days (last 20)</dt><dd className="text-text-primary">{l.circuit_days_20 ?? "n/a"}</dd></div>
        <div><dt>Sessions of history</dt><dd className="text-text-primary">{l.history_len}</dd></div>
      </dl>
      {fc && (
        <div className="rounded border border-border p-2">
          <p className="text-xs font-medium text-text-primary">Model forecast (Kronos, {fc.horizon}): stored for later scoring, counted in no check</p>
          <p className="text-xs text-text-muted">
            {fc.relative_rank != null
              ? `Against the other forecasts made the same day, this one is more upbeat than ${fc.relative_rank.toFixed(0)}% of ${fc.peers_on_date}.`
              : "Too few forecasts were made that day to compare, so nothing is shown."}
          </p>
          <p className="mt-1 text-[11px] text-warning">{fc.bias_warning} For that reason the raw figure is not displayed.</p>
        </div>
      )}
      <p className="text-[11px] text-text-muted">{s.note} Method {l.method_version}; thresholds are unreviewed placeholders ({f?.policy_version}).</p>
    </section>
  );
}
