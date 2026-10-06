"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useDecision } from "@/lib/useDecision";
import type { V4Event, V4Inbox, V4Projection, V4TimelineEntry, V4Twin } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import DecisionBadge from "@/components/DecisionBadge";
import AngelSessionBanner from "@/components/AngelSessionBanner";

function rupees(v: string | null | undefined): string {
  if (v === null || v === undefined) return "unknown";
  const n = Number(v);
  return Number.isNaN(n) ? "unknown" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

const DIM_LABEL: Record<string, string> = {
  account_coverage_status: "All accounts added",
  holdings_status: "Holdings imported",
  valuation_status: "Values known",
  identity_status: "Instruments matched",
  suitability_status: "Profile and goals",
};

const NEXT_STEP: Record<string, { href: string; label: string }> = {
  holdings_unusable: { href: "/holdings", label: "Add holdings" },
  valuation_unusable: { href: "/holdings", label: "Add values" },
  portfolio_empty: { href: "/allocate", label: "Plan new investment" },
  profile_incomplete: { href: "/finances", label: "Complete Financial profile" },
  goals_missing: { href: "/plan", label: "Add a goal" },
  sync_problem: { href: "/holdings", label: "Check your accounts" },
  stale_values: { href: "/holdings", label: "Refresh your holdings" },
  claims_need_review: { href: "/plan", label: "Review set-aside money" },
  reserve_shortfall: { href: "/finances", label: "Open Financial profile" },
  goal_needs_revision: { href: "/plan", label: "Revise the goal" },
  issuer_concentration: { href: "/simulate", label: "Compare a change" },
  sector_concentration: { href: "/risk", label: "See the breakdown" },
};

export default function OverviewPage() {
  const { decision, error, busy, requestReview } = useDecision();
  const [twin, setTwin] = useState<V4Twin | null>(null);
  const [projections, setProjections] = useState<V4Projection[]>([]);
  const [history, setHistory] = useState<V4TimelineEntry[]>([]);
  const [inbox, setInbox] = useState<V4Inbox | null>(null);
  const [events, setEvents] = useState<V4Event[]>([]);

  // A failed request must never look like "nothing here": the portfolio and goals sections track their own failure,
  // keep what was last loaded, and offer a retry. Only a successful answer with no state shows first-time setup.
  const [loaded, setLoaded] = useState(false);
  const [twinFailed, setTwinFailed] = useState(false);
  const [goalsFailed, setGoalsFailed] = useState(false);

  const load = useCallback(async () => {
    const [t, p, h, ib, ev] = await Promise.allSettled([
      api.get<V4Twin>("/api/v4/state/current"),
      api.get<V4Projection[]>("/api/v4/goals/projections"),
      api.get<V4TimelineEntry[]>("/api/v4/timeline"),
      api.get<V4Inbox>("/api/v4/inbox"),
      api.get<V4Event[]>("/api/v4/events"),
    ]);
    setTwinFailed(t.status === "rejected");
    if (t.status === "fulfilled") setTwin(t.value);
    setGoalsFailed(p.status === "rejected");
    if (p.status === "fulfilled") setProjections(p.value);
    if (h.status === "fulfilled") setHistory(h.value);
    if (ib.status === "fulfilled") setInbox(ib.value);
    if (ev.status === "fulfilled") setEvents(ev.value);
    setLoaded(true);
  }, []);

  useEffect(() => {
    load();
  }, [load, decision?.outcome?.outcome_id]);

  const o = decision?.outcome;
  const v = twin?.valuation;
  const noState = loaded && !twinFailed && !twin?.state;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Overview</h1>
        <p className="text-sm text-text-muted">Does anything need your attention? Doing nothing is a normal, valid answer.</p>
      </div>
      <AngelSessionBanner />
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}

      <Card title="Where things stand">
        {decision?.status === "none" || !o ? (
          <p className="text-sm text-text-muted" aria-busy={!loaded}>{decision?.message ?? (loaded ? "Preparing your first review…" : "Loading your latest review…")}</p>
        ) : (
          <div className="space-y-2" aria-live="polite">
            <div className="flex flex-wrap items-center gap-2">
              <DecisionBadge status={o.status} />
              <span className="text-sm font-medium text-text-primary">{o.headline}</span>
            </div>
            {decision.status === "pending_review" && (
              <p role="status" className="text-sm text-warning">{decision.message} Showing the last review until the new one is ready.</p>
            )}
            {decision.since_previous?.nothing_material_changed && <p className="text-xs text-text-muted">Nothing material has changed since the previous review.</p>}
            {decision.valuation_newer && <p className="text-xs text-text-muted">Newer prices exist; this review used the earlier valuation.</p>}
            <ul className="space-y-1 text-sm">
              {(o.result?.issues ?? []).filter((i) => i.severity !== "information" && !o.headline.startsWith(i.title)).slice(0, 3).map((i) => (
                <li key={i.kind} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-text-muted">{i.title}</span>
                  {NEXT_STEP[i.kind] && <Link className="text-accent underline" href={NEXT_STEP[i.kind].href}>{NEXT_STEP[i.kind].label}</Link>}
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2 pt-1">
              <Link href="/actions"><Button size="sm">Read the review</Button></Link>
              <Link href="/inbox"><Button size="sm" variant="secondary">Attention{inbox ? ` (${inbox.counts.open})` : ""}</Button></Link>
              <Button size="sm" variant="secondary" onClick={() => requestReview(false)} loading={busy}>Review again</Button>
            </div>
            <p className="text-xs text-text-muted">Reviewed {new Date(o.created_at).toLocaleString("en-IN")}. This is a simulation-based review, not investment advice.</p>
          </div>
        )}
      </Card>

      {!loaded ? (
        <p aria-busy="true" className="text-sm text-text-muted">Loading your latest review and holdings…</p>
      ) : noState ? (
        <Card title="Set up your financial picture">
          <ol className="list-inside list-decimal space-y-1 text-sm text-text-muted">
            <li><Link className="text-accent underline" href="/holdings">Add an account and your holdings</Link> (CSV, by hand, or connect Angel One)</li>
            <li><Link className="text-accent underline" href="/finances">Tell us about your income, expenses and reserve</Link></li>
            <li><Link className="text-accent underline" href="/plan">Add a goal</Link></li>
          </ol>
          <p className="mt-2 text-xs text-text-muted">A review runs by itself once there is something to look at. Nothing is bought or sold by this app.</p>
        </Card>
      ) : twinFailed && !twin ? (
        <Card>
          <p role="alert" className="text-sm text-negative">Your holdings could not be loaded just now. This is a loading problem, not an empty portfolio.</p>
          <div className="mt-2"><Button size="sm" variant="secondary" onClick={load}>Try again</Button></div>
        </Card>
      ) : (
        <Card>
          {twinFailed && <p role="alert" className="mb-2 text-xs text-warning">Could not refresh just now; showing what was loaded earlier. <button className="underline" onClick={load}>Try again</button></p>}
          <p className="text-xs text-text-muted">{twin?.headline_label}</p>
          <p className="text-3xl font-semibold tabular-nums text-text-primary">{v ? rupees(v.known_total) : "unknown"}</p>
          <p className="text-xs text-text-muted">
            {v?.coverage.latest_as_of ? `Values as of ${v.coverage.latest_as_of}` : "Value date unknown"}
            {v && ` · ${v.unknown_value_count} without a value · ${v.coverage.fresh_value_share ? `${(Number(v.coverage.fresh_value_share) * 100).toFixed(0)}% fresh` : "freshness unknown"}`}
          </p>
        </Card>
      )}

      {goalsFailed && projections.length === 0 && (
        <p role="alert" className="text-sm text-warning">Your goals could not be loaded just now. <button className="underline" onClick={load}>Try again</button></p>
      )}

      {projections.length > 0 && (
        <Card title="Your goals">
          <ul className="space-y-1 text-sm">
            {projections.map((p) => (
              <li key={p.goal_chain_id} className="flex flex-wrap justify-between gap-2">
                <span className="text-text-primary">{p.description}</span>
                <span className="text-text-muted">
                  {p.status === "blocked_needs_review" ? "needs your review" : p.status === "needs_input" ? "needs more information"
                    : p.assessment === "reachable_under_base" ? "reachable under the base assumption"
                    : p.assessment === "needs_higher_return_or_contribution" ? "needs more than the base assumption" : "target needs revising"}
                </span>
              </li>
            ))}
          </ul>
          <Link className="mt-2 inline-block text-sm text-accent underline" href="/plan">Open goals</Link>
        </Card>
      )}

      {twin && (
        <details className="rounded-lg border border-border bg-surface p-4 shadow-sm">
          <summary className="cursor-pointer text-sm font-medium text-text-primary">
            Data readiness{Object.values(twin.readiness).some((r) => r.status !== "complete") ? " · some items need attention" : " · all complete"}
          </summary>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {Object.entries(twin.readiness).map(([dim, r]) => (
              <li key={dim} className="rounded-md border border-border p-2 text-xs">
                <p className="font-medium text-text-primary">{DIM_LABEL[dim] ?? dim}</p>
                <p className="text-text-muted">{r.status === "complete" ? "Complete" : r.status === "partial" ? "Partial" : "Not available"}</p>
                {r.missing.length > 0 && <p className="text-text-muted">{r.missing.join("; ")}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {events.length > 0 && (
        <p className="text-xs text-text-muted">Last activity: {new Date(events[0].received_at).toLocaleString("en-IN")} ({events[0].kind.replace(/_/g, " ")}). <Link className="text-accent underline" href="/inbox">See recent activity</Link></p>
      )}

      {history.length > 0 && (
        <Card title="Recent reviews">
          <ul className="space-y-1 text-sm">
            {history.slice(0, 3).map((h) => (
              <li key={h.outcome_id} className="flex flex-wrap items-center gap-2">
                <DecisionBadge status={h.status} /><span className="text-text-muted">{h.headline}</span>
                <span className="text-xs text-text-muted">{new Date(h.created_at).toLocaleDateString("en-IN")}{h.superseded ? " · superseded" : h.is_current ? " · current" : ""}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
