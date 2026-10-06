"use client";

import { useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { useDecision } from "@/lib/useDecision";
import type { V4Evaluation, V4Outcome, V4TimelineEntry } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import DecisionBadge from "@/components/DecisionBadge";
import { useEffect } from "react";

const METRIC: Record<string, string> = {
  largest_issuer_weight: "Biggest single company", largest_sector_weight: "Biggest sector", worst_scenario_loss_pct: "Worst stress-test fall",
  effective_positions: "Effective number of holdings", cash_months: "Cash cushion (months)", unknown_weight: "Share we cannot see into",
  goal_shortfall_base: "Goal shortfall (base case)",
};

function fmt(key: string, v: string | null): string {
  if (v === null) return "n/a";
  if (key.endsWith("weight") || key.endsWith("pct")) return `${(Number(v) * 100).toFixed(1)}%`;
  return key === "goal_shortfall_base" ? `₹${Number(v).toLocaleString("en-IN")}` : Number(v).toFixed(2);
}

export default function ActionsPage() {
  const { decision, error, busy, requestReview } = useDecision();
  const [history, setHistory] = useState<V4TimelineEntry[]>([]);
  const [opened, setOpened] = useState<V4Outcome | null>(null);
  const [evaluation, setEvaluation] = useState<V4Evaluation | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.get<V4TimelineEntry[]>("/api/v4/timeline").then(setHistory).catch(() => undefined);
  }, [decision?.outcome?.outcome_id]);

  const shown = opened ?? decision?.outcome ?? null;
  const evalId = shown?.result?.evidence.evaluation_analysis_id ?? null;

  useEffect(() => {
    setEvaluation(null);
    if (evalId) api.get<V4Evaluation>(`/api/v4/analysis/${evalId}`).then(setEvaluation).catch(() => undefined);
  }, [evalId]);

  async function open(id: string) {
    try {
      setOpened(await api.get<V4Outcome>(`/api/v4/actions/${id}`));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not open that review");
    }
  }

  const isCurrent = !opened || opened.outcome_id === decision?.outcome?.outcome_id;
  const r = shown?.result;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Actions</h1>
        <p className="text-sm text-text-muted">The latest review of your holdings, why it says what it says, and what it compared. HOLD means do nothing.</p>
      </div>
      {(error || err) && <p role="alert" className="text-sm text-negative">{error ?? err}</p>}

      {!shown ? (
        <Card><p className="text-sm text-text-muted">{decision?.message ?? "No review yet."}{" "}<Link className="text-accent underline" href="/holdings">Add holdings</Link></p></Card>
      ) : (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-2" aria-live="polite">
              <DecisionBadge status={shown.status} />
              <h2 className="text-lg font-medium text-text-primary">{shown.headline}</h2>
            </div>
            {!isCurrent && <p role="status" className="mt-1 text-sm text-warning">You are viewing an earlier review{shown.superseded ? ` (superseded: ${shown.superseded_reason})` : ""}. <button className="underline" onClick={() => setOpened(null)}>Back to current</button></p>}
            {isCurrent && decision?.status === "pending_review" && <p role="status" className="mt-1 text-sm text-warning">{decision.message} This is the last known review, not the current one.</p>}
            <p className="mt-1 text-xs text-text-muted">
              Based on snapshot v{shown.state_version}, reviewed {new Date(shown.created_at).toLocaleString("en-IN")}. {r?.headline_label}: ₹{Number(r?.known_total ?? 0).toLocaleString("en-IN")}.
            </p>
            <div className="mt-2"><Button size="sm" variant="secondary" onClick={() => requestReview(true)} loading={busy}>Review again</Button></div>
          </Card>

          {r && r.issues.length > 0 && (
            <Card title="What the review found">
              <ul className="space-y-2 text-sm">
                {r.issues.map((i) => (
                  <li key={i.kind}><strong className="text-text-primary">{i.title}</strong>{" "}<span className="text-xs text-text-muted">({i.severity})</span><br /><span className="text-text-muted">{i.detail}</span></li>
                ))}
              </ul>
            </Card>
          )}

          {r && (
            <Card title="Why this answer">
              <p className="text-sm text-text-muted">{r.explanation.why_hold ?? r.explanation.why_not_hold}</p>
              <p className="mt-1 text-sm text-text-muted">{r.explanation.compared}.</p>
              {r.explanation.next_best_alternative && <p className="mt-1 text-sm text-text-muted">Closest alternative and why it was not chosen: {r.explanation.next_best_alternative}</p>}
              {r.explanation.not_assessed_or_incomplete.length > 0 && (
                <div className="mt-2"><p className="text-xs font-medium text-text-primary">Not yet assessed or incomplete</p>
                  <ul className="list-inside list-disc text-xs text-text-muted">{r.explanation.not_assessed_or_incomplete.map((m) => <li key={m}>{m}</li>)}</ul></div>
              )}
              <div className="mt-2"><p className="text-xs font-medium text-text-primary">We will look again when</p>
                <ul className="list-inside list-disc text-xs text-text-muted">{r.explanation.triggers_to_revisit.map((m) => <li key={m}>{m}</li>)}</ul></div>
            </Card>
          )}

          {r && r.alternatives.length > 0 && (
            <Card title="What was compared with doing nothing">
              {r.alternatives.map((a) => (
                <p key={a.index} className="text-sm text-text-muted"><strong className="text-text-primary">{a.action.type === "REDUCE_PREVIEW" ? "Sell (preview only)" : a.action.type === "BUY" ? "Buy" : a.action.type === "RESERVE" ? "Set aside as reserve" : "Change contribution"} ₹{Number(a.action.amount ?? a.action.new_monthly_amount).toLocaleString("en-IN")}</strong>: {a.status.replace(/_/g, " ")}. {a.reasons.join("; ")}</p>
              ))}
              {evaluation?.alternatives[0]?.comparison_vs_hold && (
                <div tabIndex={0} className="mt-2 overflow-x-auto">
                  <table className="w-full text-xs">
                    <caption className="sr-only">Comparison with doing nothing</caption>
                    <thead><tr className="border-b border-border text-left text-text-muted"><th scope="col" className="py-1 pr-3">Measure</th><th scope="col" className="py-1 pr-3">Do nothing</th><th scope="col" className="py-1 pr-3">Option</th><th scope="col" className="py-1">Result</th></tr></thead>
                    <tbody>
                      {evaluation.alternatives[0].comparison_vs_hold.rows.map((x) => (
                        <tr key={x.metric} className="border-b border-border last:border-0"><td className="py-1 pr-3 text-text-primary">{METRIC[x.metric] ?? x.metric}</td><td className="py-1 pr-3 text-text-muted">{fmt(x.metric, x.before)}</td><td className="py-1 pr-3 text-text-muted">{fmt(x.metric, x.after)}</td><td className="py-1">{x.verdict === "improved" ? "Better" : x.verdict === "worsened" ? "Worse" : x.verdict === "within_threshold" ? "About the same" : "Cannot compare"}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="mt-2 text-xs text-text-muted">A sale is only a preview: tax cannot be estimated without purchase history, and nothing is sold by this app. <Link className="text-accent underline" href="/simulate">Try your own what-if</Link></p>
            </Card>
          )}

          {r && (
            <Card title="Evidence and audit">
              <ul className="space-y-1 text-xs text-text-muted">
                <li>Risk analysis <Link className="text-accent underline" href="/risk">open Risk</Link> (id {r.evidence.risk_analysis_id.slice(0, 8)})</li>
                {r.evidence.evaluation_analysis_id && <li>Comparison id {r.evidence.evaluation_analysis_id.slice(0, 8)}</li>}
                <li>Snapshot v{r.audit.state_version}, valuation at {new Date(r.audit.valuation_cutoff).toLocaleString("en-IN")}</li>
                <li>Rules: {Object.entries(r.audit.policy_versions).map(([k, v]) => `${k} ${v}`).join(", ")}</li>
                <li>Computed {new Date(r.audit.computed_at).toLocaleString("en-IN")}; no AI model wrote any number here ({r.audit.uses_llm ? "model used" : "deterministic"}).</li>
                <li>Valid until {new Date(r.valid.review_by).toLocaleDateString("en-IN")} or until: {r.valid.invalidated_by.join("; ")}</li>
              </ul>
              <p className="mt-2 text-xs text-text-muted">This is an educational simulation, not personalised investment advice. Limits and thresholds are unreviewed defaults.</p>
            </Card>
          )}
        </>
      )}

      {history.length > 0 && (
        <Card title="History">
          <ul className="space-y-1 text-sm">
            {history.map((h) => (
              <li key={h.outcome_id} className="flex flex-wrap items-center gap-2">
                <DecisionBadge status={h.status} />
                <button className="text-left text-text-muted underline" onClick={() => open(h.outcome_id)}>{h.headline}</button>
                <span className="text-xs text-text-muted">{new Date(h.created_at).toLocaleString("en-IN")}{h.is_current ? " · current" : h.superseded ? " · superseded" : ""}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
