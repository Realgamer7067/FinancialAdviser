"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { V4Suggestions } from "@/lib/types";
import Card from "@/components/ui/Card";
import SuggestionLines from "@/components/SuggestionLines";

export default function SuggestionsPanel() {
  const [s, setS] = useState<V4Suggestions | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.get<V4Suggestions>("/api/v4/suggestions").then(setS).catch((e) => setErr(e instanceof ApiError ? e.message : "Could not load")); }, []);
  if (err) return <Card title="What changed in what you hold"><p role="alert" className="text-sm text-negative">Could not load price signals: {err}. Nothing is implied about your holdings.</p></Card>;
  if (!s) return <Card title="What changed in what you hold"><p aria-busy="true" className="text-sm text-text-muted">Checking price history…</p></Card>;
  const withNews = s.held.filter((i) => i.observations.length > 0);
  return (
    <Card title="What changed in what you hold">
      <p className="mb-2 text-xs text-text-muted">{s.note} Price signals as of {s.as_of ?? "n/a"}; the thresholds are unreviewed placeholders chosen so the typical stock changes state fewer than two times a year (measured on {s.policy.measured_flip_rates.stocks} stocks).</p>
      {s.portfolio.length > 0 && (
        <ul className="mb-3 space-y-1">
          {s.portfolio.map((p) => (
            <li key={p.kind + (p.bucket ?? "")} className="rounded border border-border p-2">
              <p className="text-sm text-text-primary">{p.title}</p>
              <p className="text-xs text-text-muted">{p.detail}</p>
              {p.href && !p.options && <Link href={p.href} className="text-xs text-accent underline">Go there</Link>}
              {p.options && <ul className="mt-1 list-inside list-disc text-xs text-text-muted">{p.options.map((o) => <li key={o.id}>{o.href ? <Link href={o.href} className="text-accent underline">{o.text}</Link> : o.text}</li>)}</ul>}
            </li>
          ))}
        </ul>
      )}
      {s.held.length === 0 ? <p className="text-sm text-text-muted">No held stock or ETF could be matched to a price history yet.</p> : withNews.length === 0
        ? <p className="text-sm text-text-muted">Nothing unusual in the price history of the {s.held.length} stock(s) and ETF(s) you hold.</p>
        : (
          <ul className="space-y-3">
            {withNews.map((i) => (
              <li key={i.security_id}>
                <p className="mb-1 text-sm font-medium text-text-primary">{i.symbol} <span className="text-xs font-normal text-text-muted">{i.name}{i.context === "both" ? " · also on your watchlist" : ""}</span></p>
                <SuggestionLines item={i} />
              </li>
            ))}
          </ul>
        )}
      {s.held.filter((i) => i.observations.length === 0 && i.note).map((i) => <p key={i.security_id} className="mt-2 text-xs text-text-muted">{i.symbol}: {i.note}</p>)}
      {s.funds_without_price_signals.length > 0 && <p className="mt-2 text-xs text-text-muted">No price signals for mutual funds ({s.funds_without_price_signals.join(", ")}): they have a daily NAV, not a traded price history here.</p>}
      {s.unresolved_holdings > 0 && <p className="mt-1 text-xs text-warning">{s.unresolved_holdings} holding(s) could not be matched to the catalogue by ISIN, so nothing can be said about them.</p>}
    </Card>
  );
}
