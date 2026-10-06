"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";

type Item = { key: string; title: string; source: string; needs_broker_session: boolean; how_it_updates: string; last_update: string | null; detail: string; state: "current" | "behind" | "no_data"; why: string | null };
type Freshness = {
  now: string;
  market: { today_is_trading_day: boolean; holiday: string | null; last_closed_session: string; next_update: string; next_update_date: string };
  scheduler: { last_daily_close: string | null; last_ran_at: string | null; runs_in: string };
  broker_session: { valid: boolean; expires_at: string | null; text: string; daily_reconnect: string };
  items: Item[];
};

const STATE: Record<Item["state"], { label: string; tone: string }> = {
  current: { label: "Up to date", tone: "text-positive" },
  behind: { label: "Waiting for the next update", tone: "text-warning" },
  no_data: { label: "Nothing yet", tone: "text-negative" },
};

const when = (iso: string) => `${new Date(iso).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })} IST`;

export default function DataFreshnessPage() {
  const [d, setD] = useState<Freshness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => { setError(null); api.get<Freshness>("/api/v4/system/freshness").then(setD).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load")); };
  useEffect(load, []);
  const [queued, setQueued] = useState<string | null>(null);
  const refreshFundamentals = () => api.post<{ queued: boolean; already_queued: boolean }>("/api/v4/system/fundamentals/refresh", {})
    .then((r) => setQueued(r.queued ? "Queued. It takes a few minutes; reload this page to see the new dates." : "A refresh is already running."))
    .catch((e) => setQueued(e instanceof ApiError ? e.message : "Could not queue it"));

  if (error) return <div role="alert" className="space-y-2"><h1 className="text-xl font-semibold text-text-primary">Data freshness</h1><p className="text-sm text-negative">{error}</p><Button size="sm" variant="secondary" onClick={load}>Try again</Button></div>;
  if (!d) return <div aria-busy="true"><h1 className="text-xl font-semibold text-text-primary">Data freshness</h1><p className="text-sm text-text-muted">Loading…</p></div>;

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-xl font-semibold text-text-primary">Data freshness</h1>
        <p className="text-sm text-text-muted">What the app holds, how old each part is, and what will refresh it. Nothing here is live: prices update after each trading day&apos;s close.</p>
      </div>

      <Card title="When it next updates">
        <p className="text-sm text-text-primary">
          Next after-close update: <strong>{when(d.market.next_update)}</strong>
          {" "}<span className="text-text-muted">
            ({d.market.today_is_trading_day ? "today is a trading day" : d.market.holiday ? `today is an NSE holiday: ${d.market.holiday}` : "today is a weekend"}; the last closed session was {d.market.last_closed_session})
          </span>
        </p>
        <p className="mt-2 text-sm text-text-muted">{d.scheduler.last_daily_close ? `The last after-close run was for ${d.scheduler.last_daily_close}. ` : "No after-close run has happened yet. "}It runs inside the backend, checked every 10 minutes, so it only runs while the app and your computer are on.</p>
        <p className={`mt-2 text-sm ${d.broker_session.valid ? "text-positive" : "text-negative"}`}>{d.broker_session.text}.</p>
        <p className="mt-1 text-xs text-text-muted">{d.broker_session.daily_reconnect}</p>
      </Card>

      <ul className="space-y-3">
        {d.items.map((i) => {
          const s = STATE[i.state];
          return (
            <li key={i.key} className="rounded-lg border border-border bg-surface p-3 shadow-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-sm font-medium text-text-primary">{i.title}</h2>
                <span className={`text-sm ${s.tone}`}>{s.label}</span>
              </div>
              <p className="mt-1 text-sm text-text-muted">{i.detail}</p>
              {i.why && <p className="mt-1 text-xs text-warning">{i.why}</p>}
              <p className="mt-1 text-xs text-text-muted">Source: {i.source}. Updates {i.how_it_updates}.{i.needs_broker_session ? " Needs your Angel session." : ""}</p>
              {i.key === "fundamentals" && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="secondary" onClick={refreshFundamentals}>Refresh now</Button>
                  {queued && <span role="status" className="text-xs text-text-muted">{queued}</span>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
