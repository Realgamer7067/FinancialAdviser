"use client";

import StockChecklist from "@/components/allocate/StockChecklist";
import StockRanking from "@/components/allocate/StockRanking";
import StaleNotice from "@/components/ui/StaleNotice";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { V4Funds, V4StockRanking, V4StockScreen, V4AllocationPlan } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

const INPUT = "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
const BUCKET_COLOR: Record<string, string> = { equity_india: "bg-accent", equity_intl: "bg-warning", gold: "bg-positive", debt: "bg-text-muted" };
const STATUS: Record<string, { label: string; tone: string }> = {
  ready: { label: "Ready to review", tone: "border-positive text-positive" },
  needs_input: { label: "Needs more from you", tone: "border-warning text-warning" },
  blocked: { label: "Blocked by a safety check", tone: "border-negative text-negative" },
  nothing_to_do: { label: "Nothing to do right now", tone: "border-border text-text-muted" },
};
const ROLE: Record<string, string> = { core: "Core index fund", satellite: "Direct stock", safe: "Safe bucket" };
const BUCKET_ROLE: Record<string, string> = { gold: "Gold ETF", debt: "Liquid ETF (safe bucket)" };
const METRIC: Record<string, string> = {
  largest_issuer_weight: "Largest single company", largest_sector_weight: "Largest single sector", worst_scenario_loss_pct: "Worst modeled market fall",
  effective_positions: "Effective number of positions", cash_months: "Months of expenses in cash", unknown_weight: "Value the checker cannot look inside", goal_shortfall_base: "Goal shortfall",
};

const money = (v: string | null | undefined) => (v == null ? "n/a" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const pct = (v: string | null | undefined) => (v == null ? "n/a" : `${(Number(v) * 100).toFixed(0)}%`);

export default function AllocatePage() {
  const [amount, setAmount] = useState("");
  const [whatIf, setWhatIf] = useState<"" | "conservative" | "moderate" | "aggressive">("");
  const [plan, setPlan] = useState<V4AllocationPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planBasis, setPlanBasis] = useState("");
  const [funds, setFunds] = useState<V4Funds | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [fundsMsg, setFundsMsg] = useState<string | null>(null);
  const loadFunds = () => api.get<V4Funds>("/api/v4/connections/angel/funds").then(setFunds).catch(() => setFunds(null));
  useEffect(() => { loadFunds(); }, []);
  // Read Angel again: queue a sync (it fetches the funds report with the holdings) and wait for it, up to about a minute.
  async function refreshFunds() {
    if (!funds?.account_id) return;
    setRefreshing(true); setFundsMsg(null);
    try {
      const job = await api.post<{ id: string; status: string }>(`/api/v4/accounts/${funds.account_id}/sync`, { idempotency_key: crypto.randomUUID() });
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const j = await api.get<{ status: string }>(`/api/v4/jobs/${job.id}`);
        if (j.status === "done" || j.status === "failed") break;
      }
      await loadFunds();
    } catch (e) { setFundsMsg(e instanceof ApiError ? e.message : "Could not read Angel just now"); }
    finally { setRefreshing(false); }
  }
  const [screen, setScreen] = useState<V4StockScreen | null>(null);
  const [screenError, setScreenError] = useState<string | null>(null);
  const [ranking, setRanking] = useState<V4StockRanking | null>(null);
  const [rankingError, setRankingError] = useState<string | null>(null);
  useEffect(() => { api.get<V4StockRanking>("/api/v4/allocation/stock-ranking").then(setRanking).catch((e) => setRankingError(e instanceof ApiError ? e.message : "failed")); }, []);
  useEffect(() => { api.get<V4StockScreen>("/api/v4/allocation/stock-scores").then(setScreen).catch((e) => setScreenError(e instanceof ApiError ? e.message : "failed")); }, []);
  const basis = `${amount}|${whatIf}`;

  async function build() {
    setBusy(true); setError(null);
    try {
      setPlanBasis(basis);
      setPlan(await api.post<V4AllocationPlan>("/api/v4/allocation/plan", { new_money: amount || "0", ...(whatIf ? { what_if_band: whatIf } : {}) }));
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not build the plan"); }
    finally { setBusy(false); }
  }

  const st = plan ? STATUS[plan.status] : null;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Invest new money</h1>
        <p className="text-sm text-text-muted">
          A proposal for how to spread money across stocks, gold and safe debt, worked out by fixed rules from your own answers and public market data. It is for your own money: you place any order yourself in Angel One.
          It only ever suggests buying. It never suggests selling, because the tax on a sale cannot be worked out without your purchase records. The rules are unreviewed placeholders, shown below the plan.
        </p>
      </div>

      {funds && (
        <Card title="Your Angel account funds">
          {funds.available != null ? (
            <>
              <p className="text-sm text-text-primary">
                Angel&apos;s funds report shows <strong className="tabular-nums">{money(funds.available)}</strong> available cash
                <span className="text-text-muted"> (read {funds.as_of ? new Date(funds.as_of).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "at an unknown time"}{funds.age_minutes != null ? `, ${funds.age_minutes < 60 ? `${funds.age_minutes} min` : `${Math.round(funds.age_minutes / 60)} h`} ago` : ""}{funds.account_label ? `, ${funds.account_label}` : ""}).</span>
              </p>
              {funds.stale && <p role="status" className="mt-1 text-xs text-warning">This reading is old or your Angel session has ended, so it may be out of date. Read it again after reconnecting.</p>}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={() => setAmount(String(Math.floor(Number(funds.available))))} disabled={Number(funds.available) <= 0}>Use {money(funds.available)} as the amount</Button>
                <Button size="sm" variant="secondary" onClick={refreshFunds} loading={refreshing}>Read it again from Angel</Button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-text-muted">Angel&apos;s funds report is not available yet.</p>
              {funds.account_id && <div className="mt-2"><Button size="sm" variant="secondary" onClick={refreshFunds} loading={refreshing}>Read it from Angel</Button></div>}
            </>
          )}
          {fundsMsg && <p role="alert" className="mt-1 text-xs text-negative">{fundsMsg}</p>}
          <p className="mt-2 text-xs text-text-muted">{funds.note}</p>
        </Card>
      )}

      <Card title="How much new money?">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm text-text-primary">Amount (₹)
            <input className={INPUT} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} placeholder="e.g. 50000" />
          </label>
          <label className="text-sm text-text-primary">Risk level to preview
            <select className={INPUT} value={whatIf} onChange={(e) => setWhatIf(e.target.value as typeof whatIf)}>
              <option value="">Use my own answers</option>
              <option value="conservative">What if: conservative</option><option value="moderate">What if: moderate</option><option value="aggressive">What if: aggressive</option>
            </select>
          </label>
          <Button onClick={build} loading={busy} disabled={!amount || Number(amount) <= 0}>Build the plan</Button>
        </div>
        <p className="mt-2 text-xs text-text-muted">A "what if" only previews a mix; the safety checks still use your real answers, so it stays marked as needing your input until you give them in <Link href="/finances" className="text-accent underline">Financial profile</Link>.</p>
      </Card>

      {error && <p role="alert" className="text-sm text-negative">{error}</p>}

      <StockRanking ranking={plan?.stock_ranking ?? ranking} loading={!ranking && !rankingError} error={rankingError} />
      <details className="rounded-lg border border-border bg-surface p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-medium text-text-primary">Earlier checklist score (information only: it no longer picks stocks)</summary>
        <div className="mt-3"><StockChecklist screen={screen} loading={!screen && !screenError} error={screenError} /></div>
      </details>

      {plan && st && (
        <StaleNotice stale={planBasis !== basis}>
        <div className="space-y-6">
          <section aria-label="Plan status" className={`rounded-md border p-3 ${st.tone}`}>
            <p className="text-sm font-medium">{st.label}</p>
            <ul className="mt-1 list-inside list-disc text-xs text-text-muted">{plan.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </section>

          {plan.small_amount && (
            <Card title={`Starting small: ${money(plan.new_money)}`}>
              <p className="text-sm text-text-muted">{plan.small_amount.message}</p>
              <ul className="mt-3 space-y-3">
                {plan.small_amount.options.map((o) => (
                  <li key={o.kind} className="rounded-md border border-border p-3">
                    <p className="text-sm font-medium text-text-primary">{o.title}{o.adds_risk && <span className="ml-2 rounded-full bg-warning-subtle px-2 py-0.5 text-xs font-normal text-warning">adds risk</span>}</p>
                    <p className="mt-1 text-sm text-text-muted">{o.detail}</p>
                    <p className="mt-1 text-xs text-text-muted">NAV {money(o.fund.nav)} on {o.fund.nav_date}. Bought in the Angel One app, not here.</p>
                  </li>
                ))}
              </ul>
              {plan.small_amount.single_units.length > 0 && (
                <div className="mt-3">
                  <p className="text-sm font-medium text-text-primary">Single units you could afford</p>
                  <p className="text-xs text-text-muted">{plan.small_amount.single_units_note}</p>
                  <ul className="mt-1 list-inside list-disc text-sm text-text-muted">
                    {plan.small_amount.single_units.map((u) => <li key={u.symbol}>{u.symbol} <span className="text-xs">({u.name}) · one unit {money(u.price)} as of {u.price_as_of}</span></li>)}
                  </ul>
                </div>
              )}
              <p className="mt-3 text-xs text-text-muted">{plan.small_amount.stocks_note} <Link href="/market" className="text-accent underline">Open Market</Link></p>
            </Card>
          )}

          <Card title="Where your money would sit">
            <p className="mb-2 text-xs text-text-muted">After this plan your investments would total {money(plan.base_total_after_plan)}{Number(plan.cash_not_counted) > 0 ? ` (your ${money(plan.cash_not_counted)} of bank cash is not counted)` : ""}. A bucket within 5 points of its target needs no move.</p>
            <ul className="space-y-2">
              {plan.drift.map((d) => (
                <li key={d.bucket}>
                  <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                    <span className="text-text-primary">{d.label}</span>
                    <span className="text-xs text-text-muted">target {pct(d.target_weight)} · now {d.current_weight == null ? "nothing held yet" : pct(d.current_weight)}{d.outside_band ? ` · ${d.direction}` : ""}</span>
                  </div>
                  <div className="mt-1 h-2 rounded bg-border" role="img" aria-label={`${d.label}: target ${pct(d.target_weight)}, now ${pct(d.current_weight)}`}>
                    <div className={`h-2 rounded ${BUCKET_COLOR[d.bucket] ?? "bg-accent"}`} style={{ width: `${Math.min(100, Number(d.target_weight) * 100)}%` }} />
                  </div>
                  {d.note && <p className="mt-1 text-xs text-text-muted">{d.note}</p>}
                </li>
              ))}
            </ul>
            {Number(plan.unknown_value) > 0 && <p className="mt-2 text-xs text-warning">{money(plan.unknown_value)} of what you hold ({pct(plan.unknown_share)}) could not be placed in a bucket and is left out of these numbers.</p>}
          </Card>

          <Card title={plan.legs.length ? `What to buy (${plan.legs.length} purchase${plan.legs.length > 1 ? "s" : ""})` : "What to buy"}>
            {plan.legs.length === 0 ? <p className="text-sm text-text-muted">No purchase is suggested.</p> : (
              <div tabIndex={0} className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <caption className="sr-only">Suggested purchases</caption>
                  <thead className="text-xs text-text-muted"><tr><th scope="col" className="p-2">Instrument</th><th scope="col" className="p-2 text-right">Units</th><th scope="col" className="p-2 text-right">Price</th><th scope="col" className="p-2 text-right">Cost incl. charges</th></tr></thead>
                  <tbody>
                    {plan.legs.map((l) => (
                      <tr key={l.instrument_id} className="border-t border-border align-top">
                        <td className="p-2">
                          <p className="font-medium text-text-primary">{l.symbol} <span className="text-xs font-normal text-text-muted">{BUCKET_ROLE[l.bucket] ?? ROLE[l.role] ?? l.role}{l.sector ? ` · ${l.sector}` : ""}</span></p>
                          <p className="max-w-md text-xs text-text-muted">{l.why}</p>
                        </td>
                        <td className="p-2 text-right">{l.units}</td>
                        <td className="p-2 text-right">{money(l.price)}<p className="text-[11px] text-text-muted">as of {l.price_as_of}</p></td>
                        <td className="p-2 text-right">{money(l.planned_debit)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="text-xs text-text-muted"><tr className="border-t border-border"><td className="p-2" colSpan={3}>Total spent (charges are an assumed 0.3%, not a quote) · left over as cash</td><td className="p-2 text-right text-text-primary">{money(plan.spent)} · {money(plan.leftover_cash)}</td></tr></tfoot>
                </table>
              </div>
            )}
            <p className="mt-2 text-xs text-text-muted">{plan.liquid_note}</p>
          </Card>

          {plan.warnings.length > 0 && (
            <Card title="Things to know">
              <ul className="list-inside list-disc space-y-1 text-xs text-text-muted">{plan.warnings.map((w) => <li key={w}>{w}</li>)}<li>{plan.satellite_note}</li></ul>
            </Card>
          )}

          {plan.engine && (
            <Card title="Safety checks (the same ones the action lab uses)">
              <p className="text-sm text-text-primary">Result: {plan.engine.status === "gates_pass" ? "every check passes on every purchase and on the final portfolio" : plan.engine.status === "needs_input" ? "some checks need information from you" : "a check failed"}.</p>
              <ul className="mt-1 list-inside list-disc text-xs text-text-muted">{plan.engine.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              <p className="mt-2 text-xs text-text-muted">Money check: {money(plan.engine.accounting.assets_before)} + {money(plan.engine.accounting.external_contribution)} new = {money(plan.engine.accounting.assets_after)} invested or held + {money(plan.engine.accounting.friction)} charges. {plan.engine.accounting.conserved ? "It balances to the paisa." : "It does NOT balance."}</p>
              <details className="mt-2 text-xs text-text-muted">
                <summary className="cursor-pointer text-text-primary">Compared with leaving the money in cash</summary>
                <p className="mt-1">{plan.engine.comparison_caveat}</p>
                <ul className="mt-1 space-y-0.5">{plan.engine.comparison_vs_hold.rows.filter((r) => r.before !== null && r.after !== null).map((r) => <li key={r.metric}>{METRIC[r.metric] ?? r.metric}: {Number(r.before).toFixed(2)} to {Number(r.after).toFixed(2)} ({r.verdict.replace("_", " ")})</li>)}</ul>
              </details>
              <details className="mt-2 text-xs text-text-muted">
                <summary className="cursor-pointer text-text-primary">Each check, purchase by purchase</summary>
                {plan.engine.legs.map((leg) => (
                  <div key={leg.index} className="mt-1">
                    <p className="text-text-primary">{plan.legs[leg.index]?.symbol}</p>
                    <ul className="list-inside list-disc">{leg.gates.map((g) => <li key={g.gate_id}>{g.gate_id.replace(/_/g, " ")}: {g.result}. {g.reason}</li>)}</ul>
                  </div>
                ))}
                <div className="mt-1"><p className="text-text-primary">Whole portfolio after the plan</p><ul className="list-inside list-disc">{plan.engine.final_gates.map((g) => <li key={g.gate_id}>{g.gate_id.replace(/_/g, " ")}: {g.result}. {g.reason}</li>)}</ul></div>
              </details>
            </Card>
          )}

          {plan.fund_alternatives.length > 0 && (
            <Card title="If you would rather do a monthly SIP">
              <p className="text-xs text-text-muted">{plan.fund_note}</p>
              <ul className="mt-1 list-inside list-disc text-sm text-text-primary">{plan.fund_alternatives.map((f) => <li key={f.scheme_code}>{f.name} <span className="text-xs text-text-muted">({f.amc}; NAV {money(f.nav)} on {f.nav_date}; {f.ter_percent == null ? "expense ratio unknown" : `expense ratio ${f.ter_percent.toFixed(2)}% a year`})</span></li>)}</ul>
            </Card>
          )}

          <details className="text-xs text-text-muted">
            <summary className="cursor-pointer text-text-primary">The rules behind this plan ({plan.policy_version}, unreviewed)</summary>
            <pre tabIndex={0} className="mt-1 overflow-x-auto rounded border border-border bg-surface p-2">{JSON.stringify(plan.policy, null, 2)}</pre>
          </details>
          <p className="text-xs text-text-muted">{plan.disclaimer} Plan {plan.plan_id.slice(0, 8)} was saved ({plan.created ? "new" : "the same inputs as an earlier plan"}) so it can be checked against what happened later.</p>
        </div>
        </StaleNotice>
      )}
    </div>
  );
}
