"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { V4Event, V4Inbox, V4InboxItem } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

const TABS: { id: "open" | "snoozed" | "dismissed" | "resolved"; label: string }[] = [
  { id: "open", label: "Open" }, { id: "snoozed", label: "Snoozed" }, { id: "dismissed", label: "Dismissed" }, { id: "resolved", label: "Resolved" },
];

const NEXT: Record<string, { href: string; label: string }> = {
  reconnect_required: { href: "/holdings", label: "Reconnect your account" },
  profile_incomplete: { href: "/finances", label: "Complete Financial profile" },
  goals_missing: { href: "/plan", label: "Add a goal" },
  portfolio_empty: { href: "/allocate", label: "Plan new investment" },
  claims_need_review: { href: "/plan", label: "Review set-aside money" },
  reserve_shortfall: { href: "/finances", label: "Open Financial profile" },
  goal_needs_revision: { href: "/plan", label: "Revise the goal" },
  issuer_concentration: { href: "/simulate", label: "Compare a change" },
  sector_concentration: { href: "/risk", label: "See the breakdown" },
  stale_values: { href: "/holdings", label: "Refresh holdings" },
  sync_problem: { href: "/holdings", label: "Check accounts" },
  holdings_unusable: { href: "/holdings", label: "Add holdings" },
};

const EVENT_LABEL: Record<string, string> = {
  state_built: "Your holdings or details changed", valuation_published: "New prices were saved", import_published: "Broker holdings were refreshed",
  sync_failed: "A sync did not complete", auth_expired: "The broker session ended", scheduled_close: "Daily after-close check ran",
};

const SEV: Record<string, string> = { urgent: "Urgent", review: "Needs a look", information: "For your information", resolved: "Resolved" };

export default function InboxPage() {
  const [tab, setTab] = useState<"open" | "snoozed" | "dismissed" | "resolved">("open");
  const [data, setData] = useState<V4Inbox | null>(null);
  const [events, setEvents] = useState<V4Event[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState<Record<string, string>>({});
  const [until, setUntil] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const [i, e] = await Promise.all([api.get<V4Inbox>(`/api/v4/inbox?status=${tab}`), api.get<V4Event[]>("/api/v4/events")]);
      setData(i);
      setEvents(e);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  async function act(item: V4InboxItem, action: "dismiss" | "snooze" | "reopen") {
    setError(null);
    const body = action === "dismiss" ? { expected_version: item.version, reason: reason[item.id] ?? "" }
      : action === "snooze" ? { expected_version: item.version, until: until[item.id] } : { expected_version: item.version };
    try {
      await api.post(`/api/v4/inbox/${item.id}/${action}`, body);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
      if (e instanceof ApiError && e.status === 409) load();
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Attention</h1>
        <p className="text-sm text-text-muted">One item per issue, however many times it is re-checked. A dismissed item stays dismissed unless it gets clearly worse. An empty inbox is a good result.</p>
      </div>
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      <div role="group" aria-label="Inbox filter" className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t.id} aria-pressed={tab === t.id} onClick={() => setTab(t.id)}
            className={`rounded-md border px-3 py-1 text-sm ${tab === t.id ? "border-accent text-accent" : "border-border text-text-muted"}`}>
            {t.label}{data ? ` (${data.counts[t.id]})` : ""}
          </button>
        ))}
      </div>

      {data && data.items.length === 0 && <Card><p className="text-sm text-text-muted">Nothing here.{tab === "open" && " Nothing needs your attention right now."}</p></Card>}
      {data?.items.map((i) => (
        <Card key={i.id}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-md border border-border px-2 py-0.5 text-xs font-medium text-text-primary">{SEV[i.category]}</span>
            <h2 className="font-medium text-text-primary">{i.title}</h2>
          </div>
          <p className="mt-1 text-sm text-text-muted">{i.detail}</p>
          <p className="mt-1 text-xs text-text-muted">
            First seen {new Date(i.first_seen_at).toLocaleDateString("en-IN")}, last checked {new Date(i.last_seen_at).toLocaleString("en-IN")}
            {i.reopen_count > 0 && ` · came back ${i.reopen_count} time(s)`}
            {i.snooze_until && ` · snoozed until ${i.snooze_until}`}{i.dismissed_reason && ` · dismissed: "${i.dismissed_reason}"`}
          </p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            {NEXT[i.kind] && i.status !== "resolved" && <Link href={NEXT[i.kind].href}><Button size="sm">{NEXT[i.kind].label}</Button></Link>}
            {(i.status === "open") && (<>
              <label className="text-xs text-text-muted">Why dismiss?
                <input className="mt-1 w-48 rounded-md border border-border bg-surface px-2 py-1 text-sm" value={reason[i.id] ?? ""} onChange={(e) => setReason({ ...reason, [i.id]: e.target.value })} />
              </label>
              <Button size="sm" variant="secondary" disabled={!(reason[i.id] ?? "").trim()} onClick={() => act(i, "dismiss")}>Dismiss</Button>
              <label className="text-xs text-text-muted">Snooze until
                <input type="date" className="mt-1 rounded-md border border-border bg-surface px-2 py-1 text-sm" value={until[i.id] ?? ""} onChange={(e) => setUntil({ ...until, [i.id]: e.target.value })} />
              </label>
              <Button size="sm" variant="secondary" disabled={!until[i.id]} onClick={() => act(i, "snooze")}>Snooze</Button>
            </>)}
            {(i.status === "dismissed" || i.status === "snoozed" || i.status === "resolved") && <Button size="sm" variant="secondary" onClick={() => act(i, "reopen")}>Reopen</Button>}
          </div>
        </Card>
      ))}

      {events.length > 0 && (
        <Card title="What happened recently">
          <ul className="space-y-1 text-sm text-text-muted">
            {events.slice(0, 8).map((e, idx) => <li key={idx}>{new Date(e.received_at).toLocaleString("en-IN")}: {EVENT_LABEL[e.kind] ?? e.kind}</li>)}
          </ul>
        </Card>
      )}
    </div>
  );
}
