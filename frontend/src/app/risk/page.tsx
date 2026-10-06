"use client";

import StaleNotice from "@/components/ui/StaleNotice";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4RiskReport, V4ScenarioCatalog, V4ScenarioResult, V4Twin } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

function rupees(v: string | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v);
  return Number.isNaN(n) ? "n/a" : `${n < 0 ? "-" : ""}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function pct(v: string | number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "n/a";
  return `${(Number(v) * 100).toFixed(digits)}%`;
}

function Bar({ weight, label }: { weight: string | null; label: string }) {
  const w = Math.max(0, Math.min(1, Number(weight ?? 0)));
  return (
    <div className="flex items-center gap-2" role="img" aria-label={`${label}: ${pct(weight)}`}>
      <div className="h-2 w-32 rounded bg-border"><div className="h-2 rounded bg-accent" style={{ width: `${w * 100}%` }} /></div>
      <span className="text-xs text-text-muted">{pct(weight)}</span>
    </div>
  );
}

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

const CLASS_LABEL: Record<string, string> = {
  equity: "Direct shares", fund_or_etf: "Funds and ETFs", cash: "Cash", deposit: "Deposits", gold: "Gold", unknown: "Other or unclassified",
};
const BUCKET_LABEL: Record<string, string> = {
  unclassified_equity: "Shares with no known sector", fund_lookthrough_unknown: "Funds and ETFs (contents not looked into)", non_equity: "Not shares (cash, deposits, gold…)",
};

export default function RiskPage() {
  const [risk, setRisk] = useState<V4RiskReport | null>(null);
  const [catalog, setCatalog] = useState<V4ScenarioCatalog | null>(null);
  const [scenario, setScenario] = useState("equity_broad_-20");
  const [result, setResult] = useState<V4ScenarioResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRisk(await api.get<V4RiskReport>("/api/v4/risk"));
      setCatalog(await api.get<V4ScenarioCatalog>("/api/v4/scenarios/catalog"));
      setError(null);
    } catch (e) {
      setError(errMsg(e, "Failed to load risk"));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run() {
    if (!risk) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post<V4ScenarioResult>("/api/v4/scenarios/evaluate", { state_id: risk.state_id, valuation_id: risk.valuation_id, scenario: { id: scenario } }));
    } catch (e) {
      setError(errMsg(e, "Scenario failed"));
    } finally {
      setBusy(false);
    }
  }

  if (error && !risk) {
    return (
      <div role="alert" className="space-y-2">
        <h1 className="text-xl font-semibold text-text-primary">Risk &amp; exposure</h1>
        <p className="text-sm text-negative">{error} If you have not added holdings yet, start in <a className="text-accent underline" href="/holdings">Holdings</a>.</p>
        <button className="text-sm text-accent underline" onClick={() => { setError(null); load(); }}>Try again</button>
      </div>
    );
  }
  if (!risk) return <div aria-busy="true"><h1 className="text-xl font-semibold text-text-primary">Risk &amp; exposure</h1><p className="text-sm text-text-muted">Loading your holdings…</p></div>;
  const v = risk.volatility;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Risk</h1>
        <p className="text-sm text-text-muted">
          What your holdings look like today, as of {new Date(risk.as_of).toLocaleString("en-IN")}. Known value {rupees(risk.known_total)}. These are
          observations about concentration and liquidity, not predictions and not a health score.
        </p>
      </div>
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}

      <Card title="What you hold">
        <table className="w-full text-sm">
          <caption className="sr-only">Asset mix</caption>
          <thead><tr className="border-b border-border text-left text-text-muted"><th scope="col" className="py-1 pr-3">Type</th><th scope="col" className="py-1 pr-3">Value</th><th scope="col" className="py-1">Share of known value</th></tr></thead>
          <tbody>
            {Object.entries(risk.asset_mix.classes).map(([c, x]) => (
              <tr key={c} className="border-b border-border last:border-0">
                <td className="py-1 pr-3 text-text-primary">{CLASS_LABEL[c] ?? c.replace(/_/g, " ")}</td><td className="py-1 pr-3 text-text-muted">{rupees(x.value)}</td>
                <td className="py-1"><Bar weight={x.weight} label={c} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-sm text-text-muted">
          Direct shares: {pct(risk.asset_mix.direct_equity_share)}.
          {risk.asset_mix.equity_share_upper_bound !== risk.asset_mix.direct_equity_share && ` Including funds and ETFs (whose contents we cannot see): up to ${pct(risk.asset_mix.equity_share_upper_bound)}.`}
        </p>
        {risk.asset_mix.warnings.map((w) => <p key={w} className="text-xs text-warning">{w}</p>)}
      </Card>

      <Card title="Concentration">
        {risk.issuer_concentration.status !== "ready" ? (
          <p className="text-sm text-text-muted">{risk.issuer_concentration.warnings.join(" ") || "Not enough identified share holdings to measure this."}</p>
        ) : (
          <>
            <p className="text-sm text-text-muted">
              Largest single company: <strong className="text-text-primary">{risk.issuer_concentration.largest_issuer}</strong> at {pct(risk.issuer_concentration.largest_issuer_weight)} of your known value;
              top five {pct(risk.issuer_concentration.top5_weight)}. Equivalent to about {risk.issuer_concentration.effective_positions_over_identified} equally-sized holdings among the
              shares we could identify ({pct(risk.issuer_concentration.coverage_fraction, 0)} of value).
            </p>
            <table className="mt-2 w-full text-sm">
              <caption className="sr-only">Holdings by company</caption>
              <thead><tr className="border-b border-border text-left text-text-muted"><th scope="col" className="py-1 pr-3">Company</th><th scope="col" className="py-1 pr-3">Accounts</th><th scope="col" className="py-1">Share</th></tr></thead>
              <tbody>
                {risk.issuer_concentration.issuers.map((i) => (
                  <tr key={i.issuer} className="border-b border-border last:border-0"><td className="py-1 pr-3 text-text-primary">{i.issuer}</td><td className="py-1 pr-3 text-text-muted">{i.accounts.join(", ")}</td><td className="py-1"><Bar weight={i.weight} label={i.issuer} /></td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <h3 className="mt-4 text-sm font-medium text-text-primary">By sector (only where the company is on the instrument list or the market sector list)</h3>
        <ul className="mt-1 space-y-1 text-sm">
          {risk.sector.buckets.map((b) => (
            <li key={b.bucket} className="flex items-center justify-between gap-2"><span className="text-text-muted">{BUCKET_LABEL[b.bucket] ?? b.bucket.replace(/_/g, " ")}</span><Bar weight={b.weight} label={b.bucket} /></li>
          ))}
        </ul>
        <p className="mt-1 text-xs text-text-muted">Unknown (unmatched shares and fund contents): {pct(risk.sector.unknown_weight)}.</p>
      </Card>

      <Card title="Cash cushion">
        {risk.liquidity.status === "insufficient_data" ? (
          <p className="text-sm text-text-muted">{(risk.liquidity.warnings ?? []).join(" ") || "Add your monthly essential expenses in Financial profile to see this."}</p>
        ) : (
          <p className="text-sm text-text-muted">
            Cash you could use now (after money set aside for goals): <strong className="text-text-primary">{rupees(risk.liquidity.accessible_cash_after_claims)}</strong>, about{" "}
            {risk.liquidity.months_of_outgo} months of essential spending. Deposits and broker margin are not counted as cash. {(risk.liquidity.warnings ?? []).join(" ")}
          </p>
        )}
      </Card>

      <Card title="How much it has moved">
        {v.status === "ready" ? (
          <p className="text-sm text-text-muted">
            Over {v.window_start} to {v.window_end} ({v.observations} trading days), your shares moved about {pct(v.annualized_volatility)} a year up or down, and the worst peak-to-trough
            fall was {pct(v.max_drawdown_in_window)}. Covers {pct(v.coverage_fraction, 0)} of known value. {(v.warnings ?? []).join(" ")}
          </p>
        ) : (
          <p className="text-sm text-text-muted">Not shown: {v.reason}</p>
        )}
        <p className="mt-2 text-xs text-text-muted">Relationships between holdings (correlation): {risk.correlation_clusters.status}, {risk.correlation_clusters.reason}.</p>
      </Card>

      <Card title="What if the market falls? (illustration only)">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-sm text-text-primary">Scenario
            <select className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm" value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {catalog?.scenarios.map((s) => <option key={s.id} value={s.id} disabled={s.status !== "supported"}>{s.label}{s.status !== "supported" ? ` (not available: ${s.reason})` : ""}</option>)}
            </select>
          </label>
          <Button size="sm" onClick={run} loading={busy}>Run</Button>
        </div>
        {result && (
          <div className="mt-3"><StaleNotice stale={result.scenario.id !== scenario}>
          <div className="space-y-2" aria-live="polite">
            <p className="text-sm text-text-muted">
              {result.label} Modeled change: <strong className="text-text-primary">{rupees(result.modeled_change)}</strong> ({pct(result.modeled_change_pct_of_known_total)} of known value).
              Outside the scenario (unknown sensitivity): {rupees(result.outside_coverage.value)}; {result.outside_coverage.note}.
            </p>
            <div tabIndex={0} className="overflow-x-auto">
              <table className="w-full text-xs">
                <caption className="sr-only">Contribution of each holding to the scenario</caption>
                <thead><tr className="border-b border-border text-left text-text-muted"><th scope="col" className="py-1 pr-3">Holding</th><th scope="col" className="py-1 pr-3">Account</th><th scope="col" className="py-1 pr-3">Value</th><th scope="col" className="py-1 pr-3">Change</th><th scope="col" className="py-1">Why</th></tr></thead>
                <tbody>
                  {result.ledger.map((r) => (
                    <tr key={r.position_id} className="border-b border-border last:border-0">
                      <td className="py-1 pr-3 text-text-primary">{r.holding}</td><td className="py-1 pr-3 text-text-muted">{r.account}</td>
                      <td className="py-1 pr-3 text-text-muted">{rupees(r.pre_shock_value)}</td>
                      <td className="py-1 pr-3 text-text-muted">{r.modeled ? rupees(r.value_change) : "not modeled"}</td><td className="py-1 text-text-muted">{r.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          </StaleNotice></div>
        )}
      </Card>
      <p className="text-xs text-text-muted">{risk.limitations.join(" · ")}</p>
    </div>
  );
}
