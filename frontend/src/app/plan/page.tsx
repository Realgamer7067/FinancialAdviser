"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4Budget, V4Commitment, V4Goal, V4HoldingSummary, V4Projection } from "@/lib/types";
import Card from "@/components/ui/Card";
import ConfirmButton from "@/components/ui/ConfirmButton";
import Button from "@/components/ui/Button";

const INPUT =
  "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

function rupees(v: string | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v);
  return Number.isNaN(n) ? "n/a" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const d = err.detail as { unclaimed?: string } | string | undefined;
    if (d && typeof d === "object" && d.unclaimed !== undefined) return `${err.message} (still unclaimed: ${rupees(d.unclaimed)})`;
    return err.message;
  }
  return fallback;
}

// The API takes inflation as a fraction (0.06). People think in percent, so the form says percent and converts.
const pctToFraction = (p: string): string | null => {
  const t = p.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? String(Math.round(n * 100) / 10000) : null;
};
const fractionToPct = (f: string | null): string => (f === null ? "" : String(Math.round(Number(f) * 10000) / 100));

const REASON: Record<string, string> = {
  holding_not_found: "the holding is no longer in your latest snapshot",
  value_unknown: "the holding has no known value",
  value_below_claims: "the holding is now worth less than the total claimed on it",
};

type Tone = "good" | "warn" | "bad" | "muted";
function outlook(p: V4Projection | undefined): { text: string; tone: Tone } {
  if (!p) return { text: "No projection yet", tone: "muted" };
  if (p.status === "blocked_needs_review") return { text: "Needs your review", tone: "warn" };
  if (p.status === "needs_input") return { text: `Needs more information: ${(p.missing ?? []).join(", ").replace(/_/g, " ")}`, tone: "warn" };
  if (p.assessment === "reachable_under_base") return { text: "On track under the base assumption", tone: "good" };
  if (p.assessment === "needs_higher_return_or_contribution") return { text: "Needs more than the base assumption", tone: "warn" };
  if (p.assessment === "target_needs_revision") return { text: "Target needs revising", tone: "bad" };
  return { text: "No assessment yet", tone: "muted" };
}
const TONE: Record<Tone, string> = { good: "text-positive", warn: "text-warning", bad: "text-negative", muted: "text-text-muted" };

type GoalForm = { description: string; target_amount: string; target_basis: string; target_date: string; priority: string; inflation_pct: string };
const BLANK_GOAL: GoalForm = { description: "", target_amount: "", target_basis: "future_money", target_date: "", priority: "1", inflation_pct: "" };

function GoalFields({ f, set }: { f: GoalForm; set: (f: GoalForm) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <label className="text-sm">What for<input className={INPUT} value={f.description} onChange={(e) => set({ ...f, description: e.target.value })} /></label>
      <label className="text-sm">Target (₹)<input className={INPUT} inputMode="decimal" value={f.target_amount} onChange={(e) => set({ ...f, target_amount: e.target.value })} /></label>
      <label className="text-sm">Target date<input type="date" className={INPUT} value={f.target_date} onChange={(e) => set({ ...f, target_date: e.target.value })} /></label>
      <label className="text-sm">The target amount is in
        <select className={INPUT} value={f.target_basis} onChange={(e) => set({ ...f, target_basis: e.target.value })}>
          <option value="future_money">Money of the target date</option><option value="today_money">Today&apos;s money</option>
        </select>
      </label>
      {f.target_basis === "today_money" && (
        <label className="text-sm">Expected inflation (% a year)
          <input className={INPUT} inputMode="decimal" value={f.inflation_pct} onChange={(e) => set({ ...f, inflation_pct: e.target.value })} placeholder="e.g. 6" />
        </label>
      )}
      <label className="text-sm">Priority (1 = most important)<input className={INPUT} inputMode="numeric" value={f.priority} onChange={(e) => set({ ...f, priority: e.target.value })} /></label>
    </div>
  );
}

export default function PlanPage() {
  const [goals, setGoals] = useState<V4Goal[]>([]);
  const [holdings, setHoldings] = useState<V4HoldingSummary[]>([]);
  const [commitments, setCommitments] = useState<V4Commitment[]>([]);
  const [projections, setProjections] = useState<V4Projection[]>([]);
  const [budget, setBudget] = useState<V4Budget | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [addingGoal, setAddingGoal] = useState(false);
  const [goalForm, setGoalForm] = useState<GoalForm>(BLANK_GOAL);
  const [editing, setEditing] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<GoalForm>(BLANK_GOAL);
  const [claimForm, setClaimForm] = useState<Record<string, { position_id: string; amount: string }>>({});
  const [resize, setResize] = useState<Record<string, string>>({});
  const [addingSip, setAddingSip] = useState(false);
  const [sip, setSip] = useState({ description: "", amount: "", frequency: "monthly", goal_chain_id: "", start_date: new Date().toISOString().slice(0, 10), source: "existing_user_reported", budget_interpretation: "includes_existing_commitments" });

  const load = useCallback(async () => {
    try {
      const [g, h, c, p, b] = await Promise.all([
        api.get<V4Goal[]>("/api/v4/goals"),
        api.get<V4HoldingSummary[]>("/api/v4/allocations/summary"),
        api.get<V4Commitment[]>("/api/v4/commitments"),
        api.get<V4Projection[]>("/api/v4/goals/projections"),
        api.get<V4Budget>("/api/v4/budget"),
      ]);
      setBudget(b);
      setGoals(g);
      setHoldings(h);
      setCommitments(c);
      setProjections(p);
      setLoadError(null);
    } catch (e) {
      setLoadError(errMsg(e, "Failed to load"));
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(fn: () => Promise<unknown>, fallback: string, done?: string) {
    setError(null);
    setMsg(null);
    try {
      await fn();
      await load();
      if (done) setMsg(done);
      return true;
    } catch (e) {
      setError(errMsg(e, fallback));
      if (e instanceof ApiError && e.status === 409) load();
      return false;
    }
  }

  const goalBody = (f: GoalForm, g?: V4Goal) => ({
    description: f.description.trim(),
    target_amount: f.target_amount,
    target_basis: f.target_basis,
    target_date: f.target_date,
    priority: Number(f.priority),
    flexibility: g?.flexibility ?? "flexible",
    inflation_assumption: f.target_basis === "today_money" ? pctToFraction(f.inflation_pct) : null,
  });

  async function createGoal() {
    const ok = await run(() => api.post("/api/v4/goals", goalBody(goalForm)), "Could not create goal", `Added “${goalForm.description.trim()}”.`);
    if (ok) { setGoalForm(BLANK_GOAL); setAddingGoal(false); }
  }

  function startEdit(g: V4Goal) {
    setEditing(g.chain_id);
    setEditForm({ description: g.description, target_amount: String(Number(g.target_amount)), target_basis: g.target_basis, target_date: g.target_date, priority: String(g.priority), inflation_pct: fractionToPct(g.inflation_assumption) });
  }

  async function saveEdit(g: V4Goal) {
    const ok = await run(() => api.put(`/api/v4/goals/${g.chain_id}`, { ...goalBody(editForm, g), expected_version: g.version, status: "active" }), "Could not save the goal", "Goal saved. The outlook below uses the new target.");
    if (ok) setEditing(null);
  }

  const closeGoal = (g: V4Goal) =>
    run(
      () => api.put(`/api/v4/goals/${g.chain_id}`, { ...goalBody({ description: g.description, target_amount: g.target_amount, target_basis: g.target_basis, target_date: g.target_date, priority: String(g.priority), inflation_pct: fractionToPct(g.inflation_assumption) }, g), expected_version: g.version, status: "closed" }),
      "Could not close goal",
      `Closed “${g.description}”.`
    );

  const claim = (g: V4Goal) => {
    const f = claimForm[g.chain_id];
    if (!f?.position_id || !f.amount) return;
    return run(
      () => api.post(`/api/v4/goals/${g.chain_id}/allocations`, { position_id: f.position_id, amount: f.amount, expected_goal_version: g.version }).then(() => setClaimForm({ ...claimForm, [g.chain_id]: { position_id: "", amount: "" } })),
      "Could not set money aside",
      "Set aside. The outlook now counts it."
    );
  };

  const actOnClaim = (chain_id: string, version: number, action: "confirm" | "release" | "resize", amount?: string) =>
    run(() => api.put(`/api/v4/goal-allocations/${chain_id}`, { expected_version: version, action, ...(amount ? { amount } : {}) }), "Could not update the set-aside");

  const addSip = async () => {
    const ok = await run(() => api.post("/api/v4/commitments", { ...sip, goal_chain_id: sip.goal_chain_id || null }), "Could not add contribution", "Contribution recorded in this app. Set the SIP up in Angel One yourself.");
    if (ok) { setSip({ ...sip, description: "", amount: "" }); setAddingSip(false); }
  };

  const setSipStatus = (c: V4Commitment, status: "active" | "paused" | "ended") =>
    run(
      () =>
        api.put(`/api/v4/commitments/${c.chain_id}`, {
          expected_version: c.version, goal_chain_id: c.goal_chain_id, description: c.description, amount: c.amount,
          frequency: c.frequency, start_date: c.start_date, end_date: c.end_date, source: c.source,
          budget_interpretation: c.budget_interpretation, status,
        }),
      "Could not update contribution"
    );

  const projectionFor = (g: V4Goal) => projections.find((p) => p.goal_chain_id === g.chain_id);

  if (!loaded) {
    return <div aria-busy="true"><h1 className="text-xl font-semibold text-text-primary">Goals &amp; contributions</h1><p className="text-sm text-text-muted">Loading your goals…</p></div>;
  }
  if (loadError && goals.length === 0 && commitments.length === 0) {
    return (
      <div role="alert" className="space-y-2">
        <h1 className="text-xl font-semibold text-text-primary">Goals &amp; contributions</h1>
        <p className="text-sm text-negative">Could not load your goals: {loadError}. This is a loading problem, not an empty list.</p>
        <Button size="sm" variant="secondary" onClick={() => { setLoaded(false); load(); }}>Try again</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-xl font-semibold text-text-primary">Goals &amp; contributions</h1>
          <p className="text-sm text-text-muted">
            Set money aside from a holding for a goal. One rupee can back only one goal, and if a holding changes or disappears the
            set-aside is flagged for your review, never silently moved. Outlooks are illustrations under stated assumptions, not forecasts.
          </p>
        </div>
        {!addingGoal && <Button size="sm" onClick={() => setAddingGoal(true)}>Add a goal</Button>}
      </div>
      {loadError && <p role="alert" className="text-sm text-warning">Could not refresh just now; showing what was loaded earlier. <button className="underline" onClick={load}>Try again</button></p>}
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      {msg && <p role="status" className="text-sm text-positive">{msg}</p>}

      {addingGoal && (
        <Card title="Add a goal">
          <GoalFields f={goalForm} set={setGoalForm} />
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={createGoal} disabled={!goalForm.description.trim() || !goalForm.target_amount || !goalForm.target_date}>Save goal</Button>
            <Button size="sm" variant="secondary" onClick={() => { setAddingGoal(false); setGoalForm(BLANK_GOAL); }}>Cancel</Button>
          </div>
        </Card>
      )}

      {goals.length === 0 && !addingGoal && (
        <Card>
          <p className="text-sm text-text-muted">No goals yet. A goal is something you are saving for, with an amount and a date, such as a house deposit or education. Add one to see whether your holdings and contributions are on track.</p>
        </Card>
      )}

      {goals.map((g) => {
        const p = projectionFor(g);
        const o = outlook(p);
        const mine = commitments.filter((c) => c.goal_chain_id === g.chain_id && c.status !== "ended");
        const needsReview = Number(g.needs_review_total) > 0;
        return (
          <details key={g.chain_id} className="rounded-lg border border-border bg-surface shadow-sm" open={needsReview || goals.length === 1}>
            <summary className="cursor-pointer list-none p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h2 className="font-medium text-text-primary">{g.description}</h2>
                <span className={`text-sm ${TONE[o.tone]}`}>{o.text}</span>
              </div>
              <p className="mt-1 text-xs text-text-muted">
                {rupees(g.target_amount)} ({g.target_basis === "today_money" ? "today's money" : "money of the target date"}) by {g.target_date}
                {" · "}{rupees(g.allocated_total)} set aside{p && p.status !== "needs_input" ? ` · ${rupees(p.monthly_contribution_counted)}/month counted` : ""}
                {p?.months !== undefined && ` · ${p.months} months left`}
                {needsReview && <span className="text-warning"> · {rupees(g.needs_review_total)} awaiting your review</span>}
              </p>
            </summary>

            <div className="space-y-5 border-t border-border p-4">
              {/* Outlook */}
              <section aria-label={`Outlook for ${g.description}`}>
                <h3 className="text-sm font-medium text-text-primary">Outlook</h3>
                {p?.status === "ready" && p.scenarios ? (
                  <div tabIndex={0} className="mt-2 overflow-x-auto">
                    <table className="w-full text-xs">
                      <caption className="sr-only">Scenarios for {g.description}</caption>
                      <thead><tr className="border-b border-border text-left text-text-muted">
                        <th scope="col" className="py-1 pr-3">Assumed return</th><th scope="col" className="py-1 pr-3 text-right">Projected value</th>
                        <th scope="col" className="py-1 pr-3 text-right">Shortfall</th><th scope="col" className="py-1 text-right">Monthly needed</th></tr></thead>
                      <tbody>
                        {Object.entries(p.scenarios).map(([name, s]) => (
                          <tr key={name} className="border-b border-border last:border-0">
                            <td className="py-1 pr-3">{name} ({(Number(s.annual_rate) * 100).toFixed(0)}% a year)</td>
                            <td className="py-1 pr-3 text-right tabular-nums">{rupees(s.projected_value)}</td>
                            <td className="py-1 pr-3 text-right tabular-nums">{s.funded ? "funded" : rupees(s.gap_to_target)}</td>
                            <td className="py-1 text-right tabular-nums">{rupees(s.required_monthly_contribution)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {p.assessment && (
                      <p role="status" className={`mt-2 text-sm ${TONE[o.tone]}`}>
                        {p.required_annual_return !== null && p.required_annual_return !== undefined && `Needs about ${(Number(p.required_annual_return) * 100).toFixed(1)}% a year. `}
                        {p.assessment_message}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-text-muted">{p.note} Left out: {p.limitations.join("; ")}.</p>
                  </div>
                ) : (
                  <p className="mt-1 text-sm text-text-muted">{p?.status === "blocked_needs_review" ? p.message : p?.status === "needs_input" ? `To project this goal we still need: ${(p.missing ?? []).join(", ").replace(/_/g, " ")}.` : "No projection yet."}</p>
                )}
              </section>

              {/* Funding: set-asides */}
              <section aria-label={`Money set aside for ${g.description}`}>
                <h3 className="text-sm font-medium text-text-primary">Money set aside</h3>
                {g.allocations.length === 0 ? (
                  <p className="mt-1 text-sm text-text-muted">Nothing is set aside from your holdings for this goal yet.</p>
                ) : (
                  <ul className="mt-2 space-y-2 text-sm">
                    {g.allocations.map((a) => (
                      <li key={a.chain_id} className="flex flex-wrap items-center justify-between gap-2">
                        <span>
                          {rupees(a.amount)} from {a.holding}
                          {a.status === "needs_review" && <span className="ml-2 text-warning">needs review: {REASON[a.reason ?? ""] ?? a.reason}</span>}
                        </span>
                        <span className="flex flex-wrap items-center gap-2">
                          {a.status === "needs_review" && <Button size="sm" variant="secondary" onClick={() => actOnClaim(a.chain_id, a.version, "confirm")}>Keep as is</Button>}
                          <input aria-label={`New amount for the ${a.holding} set-aside`} className="w-24 rounded-md border border-border bg-surface px-2 py-1 text-xs" inputMode="decimal" placeholder="New ₹" value={resize[a.chain_id] ?? ""} onChange={(e) => setResize({ ...resize, [a.chain_id]: e.target.value })} />
                          <Button size="sm" variant="secondary" disabled={!resize[a.chain_id]} onClick={async () => { await actOnClaim(a.chain_id, a.version, "resize", resize[a.chain_id]); setResize({ ...resize, [a.chain_id]: "" }); }}>Change</Button>
                          <ConfirmButton label="Release" consequence="Stops setting this money aside for the goal." confirmLabel="Release" onConfirm={() => actOnClaim(a.chain_id, a.version, "release")} />
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-3 flex flex-wrap items-end gap-2">
                  <label className="text-sm">Holding
                    <select className={INPUT} value={claimForm[g.chain_id]?.position_id ?? ""} onChange={(e) => setClaimForm({ ...claimForm, [g.chain_id]: { position_id: e.target.value, amount: claimForm[g.chain_id]?.amount ?? "" } })}>
                      <option value="">Choose…</option>
                      {holdings.filter((h) => h.unclaimed !== null).map((h) => (
                        <option key={h.position_ids[0]} value={h.position_ids[0]}>{h.holding} ({h.account}), {rupees(h.unclaimed)} available</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm">Amount (₹)
                    <input className={INPUT} inputMode="decimal" value={claimForm[g.chain_id]?.amount ?? ""} onChange={(e) => setClaimForm({ ...claimForm, [g.chain_id]: { position_id: claimForm[g.chain_id]?.position_id ?? "", amount: e.target.value } })} />
                  </label>
                  <Button size="sm" variant="secondary" onClick={() => claim(g)} disabled={!claimForm[g.chain_id]?.position_id || !claimForm[g.chain_id]?.amount}>Set aside</Button>
                </div>
              </section>

              {/* Funding: contributions for this goal */}
              <section aria-label={`Contributions for ${g.description}`}>
                <h3 className="text-sm font-medium text-text-primary">Regular contributions</h3>
                {mine.length === 0 ? <p className="mt-1 text-sm text-text-muted">None recorded for this goal. Record one under Contributions below.</p> : (
                  <ul className="mt-1 list-inside list-disc text-sm text-text-muted">
                    {mine.map((c) => <li key={c.chain_id}>{c.description}: {rupees(c.amount)} {c.frequency} ({c.status}{c.source === "proposed" ? ", not counted" : ""})</li>)}
                  </ul>
                )}
              </section>

              {/* Edit / close */}
              <section aria-label={`Edit ${g.description}`}>
                {editing === g.chain_id ? (
                  <div>
                    <h3 className="mb-2 text-sm font-medium text-text-primary">Edit this goal</h3>
                    <GoalFields f={editForm} set={setEditForm} />
                    <div className="mt-3 flex gap-2">
                      <Button size="sm" onClick={() => saveEdit(g)} disabled={!editForm.description.trim() || !editForm.target_amount || !editForm.target_date}>Save changes</Button>
                      <Button size="sm" variant="secondary" onClick={() => setEditing(null)}>Cancel</Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" variant="secondary" onClick={() => startEdit(g)}>Edit target or date</Button>
                    <ConfirmButton label="Close goal" consequence="Closes this goal and frees its set-aside money." confirmLabel="Close goal" onConfirm={() => closeGoal(g)} />
                  </div>
                )}
              </section>
            </div>
          </details>
        );
      })}

      {budget && (
        <Card title="Monthly budget for new investing">
          {budget.status === "unknown" ? (
            <p className="text-sm text-text-muted">Tell us how much you can invest each month in <a className="text-accent underline" href="/finances">Financial profile</a> to see this.</p>
          ) : (
            <>
              <p className="text-sm text-text-muted">
                You said you can invest {rupees(budget.stated_investable_surplus)}/month. Contributions already inside that amount:{" "}
                {rupees(budget.monthly_committed_included_in_surplus)}. Left for new investing:{" "}
                <strong className="text-text-primary">{rupees(budget.remaining_for_new_monthly)}</strong>
                {budget.over_committed && <span className="text-negative"> (your running contributions already exceed it)</span>}.
              </p>
              {Number(budget.monthly_committed_on_top_of_surplus) > 0 && (
                <p className="mt-1 text-sm text-text-muted">
                  Paid on top of it: {rupees(budget.monthly_committed_on_top_of_surplus)}/month.
                  {budget.exceeds_income_after_essentials && <span className="text-negative"> Together this is more than your income after essentials.</span>}
                </p>
              )}
            </>
          )}
        </Card>
      )}

      <Card title="Contributions (SIPs you record here)">
        <p className="mb-2 text-xs text-text-muted">These are records in this app so the outlook can count them. Starting, pausing or stopping an actual SIP happens in Angel One.</p>
        {commitments.length === 0 ? <p className="text-sm text-text-muted">None recorded.</p> : (
          <ul className="space-y-2 text-sm">
            {commitments.map((c) => (
              <li key={c.chain_id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {c.description}: {rupees(c.amount)} {c.frequency} ({rupees(c.monthly_equivalent)}/month) · {c.status}
                  {c.source === "proposed" && " · only an idea, not counted"}
                  {c.goal_chain_id ? ` · for ${goals.find((g) => g.chain_id === c.goal_chain_id)?.description ?? "a goal"}` : ""}
                </span>
                <span className="flex gap-2">
                  {c.status === "active" ? <ConfirmButton label="Pause" consequence="Marks this contribution as paused in this app only. Your SIP in Angel One is not changed." confirmLabel="Mark as paused" onConfirm={() => setSipStatus(c, "paused")} /> : c.status === "paused" ? <Button size="sm" variant="secondary" onClick={() => setSipStatus(c, "active")}>Resume</Button> : null}
                  {c.status !== "ended" && <ConfirmButton label="Stop" consequence="Marks this contribution as ended in this app only. Cancel any SIP mandate in Angel One yourself." confirmLabel="Mark as ended" onConfirm={() => setSipStatus(c, "ended")} />}
                </span>
              </li>
            ))}
          </ul>
        )}
        {!addingSip ? (
          <div className="mt-3"><Button size="sm" variant="secondary" onClick={() => setAddingSip(true)}>Record a contribution</Button></div>
        ) : (
          <>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <label className="text-sm">Name<input className={INPUT} value={sip.description} onChange={(e) => setSip({ ...sip, description: e.target.value })} placeholder="e.g. Nifty 50 index SIP" /></label>
              <label className="text-sm">Amount (₹)<input className={INPUT} inputMode="decimal" value={sip.amount} onChange={(e) => setSip({ ...sip, amount: e.target.value })} /></label>
              <label className="text-sm">How often
                <select className={INPUT} value={sip.frequency} onChange={(e) => setSip({ ...sip, frequency: e.target.value })}>
                  <option value="monthly">Monthly</option><option value="quarterly">Quarterly</option><option value="annual">Yearly</option>
                </select>
              </label>
              <label className="text-sm">For goal
                <select className={INPUT} value={sip.goal_chain_id} onChange={(e) => setSip({ ...sip, goal_chain_id: e.target.value })}>
                  <option value="">No goal</option>
                  {goals.map((g) => <option key={g.chain_id} value={g.chain_id}>{g.description}</option>)}
                </select>
              </label>
              <label className="text-sm">Is it already running?
                <select className={INPUT} value={sip.source} onChange={(e) => setSip({ ...sip, source: e.target.value })}>
                  <option value="existing_user_reported">Yes, already running</option><option value="proposed">No, only an idea</option>
                </select>
              </label>
              <label className="text-sm">Is it part of the amount you said you can invest each month?
                <select className={INPUT} value={sip.budget_interpretation} onChange={(e) => setSip({ ...sip, budget_interpretation: e.target.value })}>
                  <option value="includes_existing_commitments">Yes, included in it</option><option value="additional_to_existing_commitments">No, paid on top of it</option>
                </select>
              </label>
            </div>
            <div className="mt-3 flex gap-2">
              <Button size="sm" onClick={addSip} disabled={!sip.description.trim() || !sip.amount}>Save contribution</Button>
              <Button size="sm" variant="secondary" onClick={() => setAddingSip(false)}>Cancel</Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
