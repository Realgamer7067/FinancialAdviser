"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4LiveClaim, V4LiveLedger, V4Study, V4StudyClaim } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

const VERDICT: Record<string, { label: string; tone: string }> = {
  no_data: { label: "Nothing measured yet", tone: "text-text-muted" },
  too_early: { label: "Too early to say", tone: "text-text-muted" },
  underpowered: { label: "Cannot tell: the sample is too small to see an effect this size", tone: "text-warning" },
  no_evidence: { label: "No evidence of an effect", tone: "text-text-muted" },
  negative: { label: "Went the wrong way", tone: "text-negative" },
  backtest_suggestive: { label: "Suggestive in the past data (cannot earn a weight)", tone: "text-accent" },
  promising: { label: "Promising, not yet enough", tone: "text-accent" },
  earned: { label: "Earned: the owner may review a weight", tone: "text-positive" },
};
const f = (v: number | null | undefined, d = 3) => (v == null ? "n/a" : v.toFixed(d));
const ci = (c: [number, number] | null | undefined) => (c ? `${c[0].toFixed(3)} to ${c[1].toFixed(3)}` : "n/a");

function StudyClaim({ c }: { c: V4StudyClaim }) {
  const v = VERDICT[c.verdict] ?? { label: c.verdict, tone: "text-text-muted" };
  const p = c.primary;
  return (
    <li className="rounded border border-border p-3">
      <p className="text-sm font-medium text-text-primary">{c.statement}</p>
      <p className={`mt-1 text-sm ${v.tone}`}>{v.label}</p>
      <p className="mt-1 text-xs text-text-muted">{c.verdict_meaning}</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-text-muted sm:grid-cols-4">
        <div><dt>Average rank correlation</dt><dd className="text-text-primary">{f(p.mean_ic)}</dd></div>
        <div><dt>Interval (strict, over {p.n_dates} months)</dt><dd className="text-text-primary">{ci(p.ci)}</dd></div>
        <div><dt>Smallest effect it could detect</dt><dd className="text-text-primary">{f(p.minimum_detectable_ic)}</dd></div>
        <div><dt>Months with a positive result</dt><dd className="text-text-primary">{p.share_of_dates_positive == null ? "n/a" : `${(p.share_of_dates_positive * 100).toFixed(0)}%`}</dd></div>
      </dl>
      <p className="mt-1 text-xs text-text-muted">By year: {Object.entries(p.by_year_mean_ic).map(([y, v]) => `${y}: ${v.toFixed(3)}`).join(" · ")}</p>
      {c.secondary_63 && <p className="mt-1 text-xs text-text-muted">Over 3 months (descriptive only, {c.secondary_63.n_dates} non-overlapping periods): {f(c.secondary_63.mean_ic)}, interval {ci(c.secondary_63.ci_95)}.</p>}
      {c.top_quintile_minus_universe && <p className="mt-1 text-xs text-text-muted">The top fifth versus all eligible stocks, one month ahead: {c.top_quintile_minus_universe.mean == null ? "n/a" : `${(c.top_quintile_minus_universe.mean * 100).toFixed(2)} percentage points`} (95% interval {c.top_quintile_minus_universe.ci_95 ? `${(c.top_quintile_minus_universe.ci_95[0] * 100).toFixed(2)} to ${(c.top_quintile_minus_universe.ci_95[1] * 100).toFixed(2)}` : "n/a"}), before costs and tax.</p>}
    </li>
  );
}


type Plain = { key: string; live?: string; study?: string; title: string; claim: string; kind: "return" | "risk" | "model" };
const CLAIMS: Plain[] = [
  { key: "trend", live: "L1_trend_return", study: "C1_trend_return", title: "Trend", claim: "Stocks trading above their 200-day average do better over the next month.", kind: "return" },
  { key: "momentum", live: "L2_momentum_return", study: "C2_momentum_return", title: "Momentum", claim: "Stocks that rose more over the past year (leaving out the last month) keep doing better.", kind: "return" },
  { key: "calm", live: "L3_lowvol_return", study: "C3_lowvol_return", title: "Calm stocks", claim: "Stocks with calmer prices do better over the next month.", kind: "return" },
  { key: "jumpy", live: "L4_vol_persistence", study: "C4_vol_persistence", title: "Jumpiness lasts", claim: "A stock that has been jumpy keeps being jumpy. This describes risk; it makes no claim about returns.", kind: "risk" },
  { key: "rank", live: "L9_rank_return", title: "Stock ranking (value, quality, momentum)", claim: "Nifty 50 stocks that rank higher on value, quality and momentum together do better over the next month. This is the ranking that steers which stocks a plan picks.", kind: "return" },
  { key: "checklist", live: "L8_checklist_return", title: "Stock checklist score", claim: "Nifty 50 stocks with a higher checklist score (cheaper, better quality, less debt, calmer) do better over the next month. This is the score that steers which stock a plan picks.", kind: "return" },
  { key: "kronos", live: "L5_kronos_ic", title: "Price-forecast model", claim: "The forecast model puts stocks in the right order (it is shown relative to other forecasts, never as a number).", kind: "model" },
  { key: "break", live: "L6_trend_break_held", title: "Trend breaks", claim: "After a stock falls below its trend, it keeps doing worse than the market for a while.", kind: "return" },
];

function pastPlain(c: V4StudyClaim | undefined): { text: string; tone: string } {
  if (!c) return { text: "Not tested on past data", tone: "text-text-muted" };
  switch (c.verdict) {
    case "backtest_suggestive": return { text: "Held up in past data", tone: "text-accent" };
    case "underpowered": return { text: "Cannot tell: five years is too little to see an effect this small", tone: "text-warning" };
    case "no_evidence": return { text: "No sign of an effect", tone: "text-text-muted" };
    case "negative": return { text: "Went the wrong way", tone: "text-negative" };
    default: return { text: VERDICT[c.verdict]?.label ?? c.verdict, tone: "text-text-muted" };
  }
}

function livePlain(c: V4LiveClaim | undefined): { text: string; tone: string; done: number; need: number } {
  if (!c) return { text: "Not tracked live", tone: "text-text-muted", done: 0, need: 0 };
  const need = c.dates_needed_for_earned ?? 24;
  const done = c.n_dates_used ?? 0;
  const v = c.verdict ? VERDICT[c.verdict] : null;
  if (c.verdict === "no_data" || c.scored === 0) {
    return { text: `Waiting: ${c.logged} logged, none old enough to score${c.first_results_expected ? ` (first results around ${c.first_results_expected})` : ""}`, tone: "text-text-muted", done, need };
  }
  return { text: v?.label ?? c.verdict ?? "", tone: v?.tone ?? "text-text-muted", done, need };
}

function Meter({ done, need, label }: { done: number; need: number; label: string }) {
  const pct = need > 0 ? Math.min(100, Math.round((done / need) * 100)) : 0;
  return (
    <div role="img" aria-label={`${label}: ${done} of ${need} separate dates measured`} className="mt-1 flex items-center gap-2 text-xs text-text-muted">
      <div className="h-1.5 w-28 rounded bg-border"><div className="h-1.5 rounded bg-accent" style={{ width: `${pct}%` }} /></div>
      {done} of {need} dates
    </div>
  );
}

export default function ScorecardPage() {
  const [study, setStudy] = useState<V4Study | null>(null);
  const [live, setLive] = useState<V4LiveLedger | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadFailed, setLoadFailed] = useState<{ study: boolean; live: boolean }>({ study: false, live: false });
  const load = () => {
    api.get<V4Study>("/api/v4/ledger/study").then((r) => { setStudy(r); setLoadFailed((f) => ({ ...f, study: false })); })
      .catch((e) => { setLoadFailed((f) => ({ ...f, study: true })); setMsg(e instanceof ApiError ? e.message : "Could not load the study"); });
    api.get<V4LiveLedger>("/api/v4/ledger/live").then((r) => { setLive(r); setLoadFailed((f) => ({ ...f, live: false })); })
      .catch(() => setLoadFailed((f) => ({ ...f, live: true })));
  };
  useEffect(load, []);
  async function run() {
    setBusy(true); setMsg(null);
    try { const r = await api.post<{ queued: boolean }>("/api/v4/ledger/study/run"); setMsg(r.queued ? "The study was queued. It takes about a minute; reload then." : "A study is already queued."); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : "Could not queue the study"); } finally { setBusy(false); }
  }
  const earned = live?.claims.filter((c) => c.verdict === "earned") ?? [];
  const liveById = new Map((live?.claims ?? []).map((c) => [c.id, c]));
  const studyById = new Map((study?.claims ?? []).map((c) => [c.id, c]));
  const logged = (live?.claims ?? []).filter((c) => c.type !== "accounting").reduce((n, c) => n + c.logged, 0);
  const firstResults = (live?.claims ?? []).map((c) => c.first_results_expected).filter(Boolean).sort()[0] ?? null;
  const sample = (live?.claims ?? []).find((c) => c.dates_needed_for_earned);
  const need = sample?.dates_needed_for_earned ?? 24;
  const horizon = sample?.horizon_sessions ?? 21;
  const years = (Math.round(((need * horizon) / 250) * 10) / 10).toString();
  const heldRisk = (study?.claims ?? []).filter((c) => c.verdict === "backtest_suggestive" && c.kind === "risk").length;
  const held = (study?.claims ?? []).filter((c) => c.verdict === "backtest_suggestive").length;
  const cannotTell = (study?.claims ?? []).filter((c) => c.verdict === "underpowered").length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Model evidence</h1>
        <p className="text-sm text-text-muted">
          The trend, momentum, calm-price and forecast checks you see on Market are descriptions of past prices, and momentum is also one third of the stock ranking on Plan new investment. This page
          shows how much each has proved itself. It measures the method, not your own returns.
        </p>
      </div>

      {(loadFailed.live || loadFailed.study) && (
        <p role="alert" className="text-sm text-warning">Part of this page could not be loaded just now, so what is missing is not zero. <button className="underline" onClick={load}>Try again</button></p>
      )}
      {msg && <p role="status" className="text-sm text-text-muted">{msg}</p>}

      <section aria-label="In short" className="rounded-lg border border-border bg-surface p-4 shadow-sm">
        <h2 className="text-sm font-semibold text-text-primary">In short</h2>
        <ul className="mt-2 space-y-2 text-sm text-text-muted">
          <li>
            <strong className="text-text-primary">Counted in your plans today: the stock ranking, which includes momentum.</strong>{" "}
            {earned.length > 0 ? `${earned.length} check(s) have earned a review of whether to give them a weight. ` : "No price signal has earned a weight on its own proof: trend, volatility and the forecast stay information only, and momentum is in the ranking as a policy choice, not as a proven one. "}
            The one thing that does steer a plan is the stock ranking on Plan new investment: it decides which Nifty 50 stocks a plan picks. It combines value, quality and momentum with equal weights (an unvalidated policy, not an optimised strategy), it is a screen and not a forecast, and it has not been tested against later prices yet. Only its momentum part can be tested on past data (it beat a plain liquidity ordering but not the whole market with any confidence). Each ranking is saved with its date so the whole thing can be tested.
          </li>
          <li>
            <strong className="text-text-primary">Proof from now on:</strong>{" "}
            {live ? `${logged.toLocaleString("en-IN")} signals are saved and waiting to be scored against what prices do next${firstResults ? `; the first results arrive around ${firstResults}` : ""}. A check needs ${need} separate measured dates, which at one date per ${horizon} trading days is about ${years} years of tracking, before it can earn anything.` : "Loading…"}
          </li>
          <li>
            <strong className="text-text-primary">What the last five years say:</strong>{" "}
            {study?.status === "ready" ? `${held} of ${study.claims?.length ?? 0} claims held up${held > 0 && held === heldRisk ? " (a description of risk, not of returns)" : ""}, ${cannotTell} could not be judged because the history is too short, and none can earn a weight because past tests are flattered by survivors and ignore costs.` : study?.status === "none" ? "No study has been run yet." : "Loading…"}
          </li>
        </ul>
        <p className="mt-3 text-xs text-text-muted">What to do with this: read the signals as context for your own decisions, not as a reason to buy or sell.</p>
      </section>

      <section aria-label="Each claim in plain words" className="space-y-3">
        <h2 className="text-sm font-semibold text-text-primary">Each claim, in plain words</h2>
        <ul className="space-y-3">
          {CLAIMS.map((c) => {
            const lv = livePlain(liveById.get(c.live ?? ""));
            const past = pastPlain(c.study ? studyById.get(c.study) : undefined);
            return (
              <li key={c.key} className="rounded-lg border border-border bg-surface p-3 shadow-sm">
                <p className="text-sm font-medium text-text-primary">{c.title}{c.kind === "risk" && <span className="ml-2 rounded-full bg-bg px-2 py-0.5 text-xs font-normal text-text-muted">risk, not returns</span>}</p>
                <p className="mt-0.5 text-sm text-text-muted">{c.claim}</p>
                <div className="mt-2 grid gap-3 text-sm sm:grid-cols-2">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-text-muted">In past data</p>
                    <p className={past.tone}>{past.text}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-text-muted">Tracked live</p>
                    <p className={lv.tone}>{lv.text}</p>
                    {lv.need > 0 && <Meter done={lv.done} need={lv.need} label={c.title} />}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        <p className="text-xs text-text-muted">Past-data results are flattered because only today&apos;s listed companies are tested, they leave out costs and tax, and they cover about one market regime. They can never earn a weight.</p>
      </section>

      <details className="rounded-lg border border-border bg-surface p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-medium text-text-primary">Expert detail: the statistics, the registered method and the study controls</summary>
        <div className="mt-4 space-y-6">
      <Card title="Live results: signals and observations scored after the fact">
        <p className="mb-2 text-xs text-text-muted">Each signal, forecast and observation is saved when it is made, then scored against the prices that follow once its full horizon has passed. Entry is the next close after it was known. Only this kind of evidence can ever earn a weight.</p>
        {!live ? <p className="text-sm text-text-muted">Loading…</p> : (
          <ul className="space-y-2">
            {live.claims.map((c) => {
              const v = c.verdict ? VERDICT[c.verdict] : null;
              return (
                <li key={c.id} className="rounded border border-border p-2 text-sm">
                  <p className="font-medium text-text-primary">{c.id.replace(/_/g, " ")} <span className="text-xs font-normal text-text-muted">{c.horizon_sessions}-session horizon</span></p>
                  {c.type === "accounting" ? <p className="text-xs text-warning">{c.label}: {(c.note ?? "").replace(/^ACCOUNTING, not skill evidence: /, "")}</p> : v && <p className={`text-xs ${v.tone}`}>{v.label}</p>}
                  <p className="text-xs text-text-muted">{c.logged} logged · {c.scored} scored · {c.pending} waiting for their horizon{c.missing_exit ? ` · ${c.missing_exit} with no exit price` : ""}
                    {c.first_results_expected ? ` · first results expected around ${c.first_results_expected}` : ""}</p>
                  {c.type === "accounting" && c.scored > 0 && <p className="text-xs text-text-muted">Purchases returned {f((c.plan_weighted_return ?? 0) * 100, 2)}% against {f((c.market_etf_average_return_same_dates ?? 0) * 100, 2)}% for the market ETF over the same dates. That is arithmetic, not evidence of skill.</p>}
                  {c.verdict && c.type !== "accounting" && <p className="text-xs text-text-muted">{c.n_dates_used ?? 0} of {c.dates_needed_for_earned} separate dates needed{c.mean != null ? ` · average ${f(c.mean)}` : ""}.</p>}
                </li>
              );
            })}
          </ul>
        )}
        {live && <p className="mt-2 text-xs text-text-muted">{live.rule}</p>}
      </Card>

      <Card title="Backtest: what the stored five-year history says">
        <div className="mb-3 rounded border border-warning p-2 text-xs text-warning">
          <p className="font-medium">Read these numbers with these caveats beside them:</p>
          <ul className="mt-1 list-inside list-disc text-text-muted">{(study?.biases ?? []).map((b) => <li key={b}>{b}</li>)}</ul>
          <p className="mt-1 text-text-muted">A backtest can never earn a weight, whatever it shows.</p>
        </div>
        {!study ? <p className="text-sm text-text-muted">Loading…</p> : study.status === "none" ? (
          <div>
            <p className="text-sm text-text-muted">{study.message}</p>
            <Button className="mt-2" size="sm" onClick={run} loading={busy}>Run the registered study</Button>
          </div>
        ) : (
          <>
            <p className="mb-2 text-xs text-text-muted">
              {study.dates?.n} month-end dates from {study.dates?.first} to {study.dates?.last}, about {study.names_per_date?.median} eligible stocks each ({study.panel?.securities} stocks in all).
              Study version {study.study_version}; {study.versions_tried} version(s) tried. The design was frozen before any result was seen (hash {study.registry_hash.slice(0, 12)}…{study.frozen_hash_matches_code ? ", matches the code" : ", DOES NOT match the code"}).
              The strictness is corrected for testing {study.k} claims at once.
            </p>
            <ul className="space-y-3">{study.claims?.map((c) => <StudyClaim key={c.id} c={c} />)}</ul>
          </>
        )}
      </Card>
        </div>
      </details>
    </div>
  );
}
