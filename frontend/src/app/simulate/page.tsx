"use client";

import StaleNotice from "@/components/ui/StaleNotice";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4Account, V4Alternative, V4Commitment, V4Evaluation, V4Instrument, V4Twin } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

const INPUT = "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

const STATUS: Record<V4Alternative["status"], { label: string; tone: string }> = {
  dominates_hold: { label: "Beats doing nothing on the measured points", tone: "text-positive" },
  tradeoff: { label: "A trade-off", tone: "text-warning" },
  no_material_benefit: { label: "No meaningful difference", tone: "text-text-muted" },
  worse_than_hold: { label: "Worse than doing nothing", tone: "text-negative" },
  review_required: { label: "Preview only: needs review", tone: "text-warning" },
  needs_input: { label: "Missing information", tone: "text-warning" },
  rejected: { label: "Not allowed", tone: "text-negative" },
};

const METRIC: Record<string, string> = {
  largest_issuer_weight: "Biggest single company",
  largest_sector_weight: "Biggest sector",
  worst_scenario_loss_pct: "Worst stress-test fall",
  effective_positions: "Effective number of holdings",
  cash_months: "Cash cushion (months)",
  unknown_weight: "Share we cannot see into",
  goal_shortfall_base: "Goal shortfall (base case)",
};

const GATE_MARK: Record<string, string> = { pass: "Pass", fail: "FAIL", unknown: "Unknown" };

function rupees(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v);
  return Number.isNaN(n) ? "n/a" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function fmtMetric(key: string, v: string | null): string {
  if (v === null || v === undefined) return "n/a";
  if (key.endsWith("weight") || key.endsWith("pct")) return `${(Number(v) * 100).toFixed(1)}%`;
  if (key === "goal_shortfall_base") return rupees(v);
  return Number(v).toFixed(2);
}

function describe(a: V4Alternative): string {
  const x = a.action;
  switch (x.type) {
    case "BUY": return `Buy ${rupees(x.amount as string)} of an instrument`;
    case "REDUCE_PREVIEW": return `Sell ${rupees(x.amount as string)} (preview)`;
    case "RESERVE": return `Set aside ${rupees(x.amount as string)} as reserve`;
    default: return `Change a monthly contribution to ${rupees(x.new_monthly_amount as string)}`;
  }
}

type Draft =
  | { type: "BUY"; instrument_id: string; account_id: string; amount: string; funding: "new_money" | "existing_cash" }
  | { type: "REDUCE_PREVIEW"; position_id: string; amount: string }
  | { type: "RESERVE"; amount: string }
  | { type: "ADJUST_CONTRIBUTION"; commitment_chain_id: string; new_monthly_amount: string };

export default function SimulatePage() {
  const [twin, setTwin] = useState<V4Twin | null>(null);
  const [instruments, setInstruments] = useState<V4Instrument[]>([]);
  const [accounts, setAccounts] = useState<V4Account[]>([]);
  const [commitments, setCommitments] = useState<V4Commitment[]>([]);
  const [contribution, setContribution] = useState("0");
  const [withdrawal, setWithdrawal] = useState("0");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [result, setResult] = useState<V4Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState<Draft["type"]>("BUY");
  const [resultBasis, setResultBasis] = useState("");
  const basis = JSON.stringify([contribution, withdrawal, drafts]);

  const load = useCallback(async () => {
    try {
      const [t, i, a, c] = await Promise.all([
        api.get<V4Twin>("/api/v4/state/current"),
        api.get<V4Instrument[]>("/api/v4/instruments"),
        api.get<V4Account[]>("/api/v4/accounts"),
        api.get<V4Commitment[]>("/api/v4/commitments"),
      ]);
      setTwin(t); setInstruments(i); setAccounts(a); setCommitments(c);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Arriving from the watchlist ("Compare adding some..."): start with a Buy option for that stock.
  useEffect(() => {
    const buy = new URLSearchParams(window.location.search).get("buy");
    if (!buy || instruments.length === 0 || accounts.length === 0) return;
    setDrafts((d) => (d.length > 0 || !instruments.some((i) => i.id === buy) ? d
      : [{ type: "BUY", instrument_id: buy, account_id: accounts[0].id, amount: "", funding: "new_money" }]));
  }, [instruments, accounts]);

  function addDraft() {
    const first = (arr: { id?: string; chain_id?: string }[]) => (arr[0]?.id ?? arr[0]?.chain_id ?? "");
    const valued = twin?.state?.positions ?? [];
    if (kind === "BUY") setDrafts([...drafts, { type: "BUY", instrument_id: first(instruments), account_id: first(accounts), amount: "", funding: "new_money" }]);
    else if (kind === "REDUCE_PREVIEW") setDrafts([...drafts, { type: "REDUCE_PREVIEW", position_id: valued[0]?.position_id ?? "", amount: "" }]);
    else if (kind === "RESERVE") setDrafts([...drafts, { type: "RESERVE", amount: "" }]);
    else setDrafts([...drafts, { type: "ADJUST_CONTRIBUTION", commitment_chain_id: first(commitments), new_monthly_amount: "" }]);
  }

  const update = (i: number, patch: Partial<Draft>) => setDrafts(drafts.map((d, j) => (j === i ? ({ ...d, ...patch } as Draft) : d)));

  async function run() {
    if (!twin?.state || !twin.valuation) return;
    setBusy(true); setError(null);
    try {
      setResultBasis(basis);
      setResult(await api.post<V4Evaluation>("/api/v4/actions/evaluate", {
        state_id: twin.state.id, valuation_id: twin.valuation.id,
        external_contribution: contribution || "0", external_withdrawal: withdrawal || "0", actions: drafts,
      }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Evaluation failed");
    } finally {
      setBusy(false);
    }
  }

  if (error && !twin) {
    return (
      <div role="alert" className="space-y-2">
        <h1 className="text-xl font-semibold text-text-primary">Compare a change</h1>
        <p className="text-sm text-negative">Could not load your holdings: {error}</p>
        <Button size="sm" variant="secondary" onClick={() => { setError(null); load(); }}>Try again</Button>
      </div>
    );
  }
  if (!twin) return <div aria-busy="true"><h1 className="text-xl font-semibold text-text-primary">Compare a change</h1><p className="text-sm text-text-muted">Loading your holdings…</p></div>;
  if (!twin.state || !twin.valuation) {
    return <p className="text-sm text-text-muted">Add an account and import holdings first (Holdings), then come back to compare options.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Compare a change</h1>
        <p className="text-sm text-text-muted">
          Try a what-if and see it next to doing nothing, on the same snapshot ({twin.headline_label.toLowerCase()} {rupees(twin.valuation.known_total)}). This is a simulation, not advice, and nothing is
          bought or sold. Doing nothing is always the default unless an option clearly beats it.
        </p>
      </div>
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}

      <Card title="Your what-if">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">New money you will add (₹)<input className={INPUT} inputMode="decimal" value={contribution} onChange={(e) => setContribution(e.target.value)} /></label>
          <label className="text-sm">Money you will take out (₹)<input className={INPUT} inputMode="decimal" value={withdrawal} onChange={(e) => setWithdrawal(e.target.value)} /></label>
        </div>
        <p className="mt-1 text-xs text-text-muted">The same new money and withdrawal are applied to &quot;do nothing&quot; (kept as cash) and to every option below.</p>

        <div className="mt-4 space-y-3">
          {drafts.map((d, i) => (
            <div key={i} className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between"><p className="text-sm font-medium text-text-primary">Option {i + 1}: {d.type === "BUY" ? "Buy" : d.type === "REDUCE_PREVIEW" ? "Sell (preview)" : d.type === "RESERVE" ? "Set aside as reserve" : "Change a contribution"}</p>
                <button className="text-xs text-negative hover:underline" onClick={() => setDrafts(drafts.filter((_, j) => j !== i))}>Remove</button></div>
              <div className="mt-2 grid gap-3 sm:grid-cols-4">
                {d.type === "BUY" && (<>
                  <label className="text-sm">What<select className={INPUT} value={d.instrument_id} onChange={(e) => update(i, { instrument_id: e.target.value })}>{instruments.map((x) => <option key={x.id} value={x.id}>{x.symbol} ({x.sector ?? "?"})</option>)}</select></label>
                  <label className="text-sm">In account<select className={INPUT} value={d.account_id} onChange={(e) => update(i, { account_id: e.target.value })}>{accounts.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
                  <label className="text-sm">Pay from<select className={INPUT} value={d.funding} onChange={(e) => update(i, { funding: e.target.value as "new_money" | "existing_cash" })}><option value="new_money">New money</option><option value="existing_cash">Cash I already hold</option></select></label>
                  <label className="text-sm">Amount (₹)<input className={INPUT} inputMode="decimal" value={d.amount} onChange={(e) => update(i, { amount: e.target.value })} /></label>
                </>)}
                {d.type === "REDUCE_PREVIEW" && (<>
                  <label className="text-sm sm:col-span-2">Which holding<select className={INPUT} value={d.position_id} onChange={(e) => update(i, { position_id: e.target.value })}>{twin.state!.positions.map((p) => <option key={p.position_id} value={p.position_id}>{p.display_name ?? p.raw_identifier} ({p.account_label})</option>)}</select></label>
                  <label className="text-sm">Amount to sell (₹)<input className={INPUT} inputMode="decimal" value={d.amount} onChange={(e) => update(i, { amount: e.target.value })} /></label>
                </>)}
                {d.type === "RESERVE" && <label className="text-sm">Amount (₹)<input className={INPUT} inputMode="decimal" value={d.amount} onChange={(e) => update(i, { amount: e.target.value })} /></label>}
                {d.type === "ADJUST_CONTRIBUTION" && (<>
                  <label className="text-sm sm:col-span-2">Which contribution<select className={INPUT} value={d.commitment_chain_id} onChange={(e) => update(i, { commitment_chain_id: e.target.value })}>{commitments.map((x) => <option key={x.chain_id} value={x.chain_id}>{x.description} ({rupees(x.monthly_equivalent)}/month)</option>)}</select></label>
                  <label className="text-sm">New monthly amount (₹)<input className={INPUT} inputMode="decimal" value={d.new_monthly_amount} onChange={(e) => update(i, { new_monthly_amount: e.target.value })} /></label>
                </>)}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-sm">Add an option
            <select className={INPUT} value={kind} onChange={(e) => setKind(e.target.value as Draft["type"])}>
              <option value="BUY">Buy something</option><option value="REDUCE_PREVIEW">Sell some (preview only)</option><option value="RESERVE">Set aside cash as reserve</option><option value="ADJUST_CONTRIBUTION">Change a monthly contribution</option>
            </select>
          </label>
          <Button size="sm" variant="secondary" onClick={addDraft}>Add</Button>
          <Button size="sm" onClick={run} loading={busy}>Compare with doing nothing</Button>
        </div>
      </Card>

      {result && (
        <StaleNotice stale={resultBasis !== basis}>
        <div className="space-y-4" aria-live="polite">
          <Card title="Doing nothing (the default)">
            <p className="text-sm text-text-muted">New money stays as cash. Total {rupees(result.hold.accounting.assets_before)} becomes {rupees(result.hold.accounting.assets_after)}.</p>
            <p className="mt-1 text-sm font-medium text-text-primary">{result.summary.headline}</p>
            {result.summary.why_runner_up_lost && <p className="text-xs text-text-muted">Closest option and why it did not win: {result.summary.why_runner_up_lost.join("; ")}</p>}
            <p className="mt-1 text-xs text-text-muted">{result.note} Saved as simulation {result.analysis_id.slice(0, 8)}.</p>
          </Card>

          {result.alternatives.map((a) => (
            <Card key={a.index}>
              <h3 className="font-medium text-text-primary">Option {a.index + 1}: {describe(a)}</h3>
              <p className={`text-sm font-medium ${STATUS[a.status].tone}`}>{STATUS[a.status].label}</p>
              <ul className="mt-1 list-inside list-disc text-sm text-text-muted">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              {a.notes.map((n) => <p key={n} className="mt-1 text-xs text-text-muted">{n}</p>)}
              {a.cost && <p className="mt-1 text-xs text-text-muted">Cost: {Object.entries(a.cost).filter(([k]) => ["friction", "tax", "friction_basis"].includes(k)).map(([k, v]) => `${k.replace("_", " ")}: ${v}`).join(" · ")}</p>}
              <p className="mt-1 text-xs text-text-muted">Check: after {rupees(a.accounting.assets_after)} + cost {rupees(a.accounting.friction)} = before {rupees(a.accounting.assets_before)} + added {rupees(a.accounting.external_contribution)} − taken out {rupees(a.accounting.external_withdrawal)} ({a.accounting.conserved ? "balances" : "DOES NOT BALANCE"}).</p>

              {a.comparison_vs_hold && (
                <div tabIndex={0} className="mt-3 overflow-x-auto">
                  <table className="w-full text-xs">
                    <caption className="sr-only">Option {a.index + 1} compared with doing nothing</caption>
                    <thead><tr className="border-b border-border text-left text-text-muted"><th scope="col" className="py-1 pr-3">Measure</th><th scope="col" className="py-1 pr-3">Do nothing</th><th scope="col" className="py-1 pr-3">This option</th><th scope="col" className="py-1">Result</th></tr></thead>
                    <tbody>
                      {a.comparison_vs_hold.rows.map((r) => (
                        <tr key={r.metric} className="border-b border-border last:border-0">
                          <td className="py-1 pr-3 text-text-primary">{METRIC[r.metric] ?? r.metric}</td><td className="py-1 pr-3 text-text-muted">{fmtMetric(r.metric, r.before)}</td>
                          <td className="py-1 pr-3 text-text-muted">{fmtMetric(r.metric, r.after)}</td>
                          <td className="py-1">{r.verdict === "improved" ? "Better" : r.verdict === "worsened" ? "Worse" : r.verdict === "within_threshold" ? "About the same" : "Cannot compare"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <details className="mt-3">
                <summary className="cursor-pointer text-sm text-accent">Checks this option had to pass ({a.gates.filter((g) => g.result !== "pass").length} not passed)</summary>
                <ul className="mt-2 space-y-1 text-xs">
                  {a.gates.map((g) => <li key={g.gate_id}><strong className="text-text-primary">{GATE_MARK[g.result]}</strong> · {g.gate_id.replace(/_/g, " ")}: <span className="text-text-muted">{g.reason}</span></li>)}
                </ul>
              </details>
            </Card>
          ))}
        </div>
        </StaleNotice>
      )}
    </div>
  );
}
