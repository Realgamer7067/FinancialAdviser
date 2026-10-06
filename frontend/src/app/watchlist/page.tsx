"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { V4SearchResult, V4Suggestions, V4SuggestionItem, V4WatchItem, V4Watchlists } from "@/lib/types";
import SuggestionLines from "@/components/SuggestionLines";
import Card from "@/components/ui/Card";
import ConfirmButton from "@/components/ui/ConfirmButton";
import Button from "@/components/ui/Button";

const INPUT = "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
const FRESH: Record<string, string> = { live: "live", delayed: "a little delayed", last_session: "last session", none: "no price yet" };
const ALERT_KINDS: [string, string][] = [["price_above", "Price at or above ₹"], ["price_below", "Price at or below ₹"], ["day_move_up", "Up today by % or more"], ["day_move_down", "Down today by % or more"]];

function errMsg(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message;
  return fallback;
}

function rupees(v: string | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v);
  return Number.isNaN(n) ? "n/a" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function Row({ it, sug, onChanged, setError }: { it: V4WatchItem; sug?: V4SuggestionItem; onChanged: () => void; setError: (m: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const [alert, setAlert] = useState({ kind: "price_above", threshold: "" });
  const [note, setNote] = useState({ note: it.note ?? "", why: it.why_watching ?? "" });
  const q = it.quote;
  const chg = q?.day_change_pct != null ? Number(q.day_change_pct) : null;

  async function run(fn: () => Promise<unknown>, fallback: string) {
    setError(null);
    try { await fn(); onChanged(); } catch (e) { setError(errMsg(e, fallback)); }
  }

  return (
    <li className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-medium text-text-primary">{it.security_id ? <Link href={`/market/${it.security_id}`} className="hover:text-accent hover:underline">{it.symbol}</Link> : it.symbol} <span className="text-xs font-normal text-text-muted">{it.name}</span></p>
          {it.context.owned && <p className="text-xs text-text-muted">You hold {rupees(it.context.owned_value)} ({(Number(it.context.owned_weight) * 100).toFixed(1)}% of your portfolio)</p>}
        </div>
        <div className="text-right">
          <p className="text-lg font-semibold text-text-primary">{q ? rupees(q.ltp) : "no price yet"}</p>
          <p className="text-xs text-text-muted">
            {q ? `${FRESH[q.freshness]} · ${new Date(q.retrieved_at).toLocaleString("en-IN")}` : "Press Refresh prices"}
          </p>
        </div>
        <div className="min-w-24 text-right">
          {chg !== null ? <p className={`text-sm font-medium ${chg >= 0 ? "text-positive" : "text-negative"}`}>{chg >= 0 ? "▲ up" : "▼ down"} {Math.abs(chg).toFixed(2)}% today</p> : <p className="text-sm text-text-muted">day change n/a</p>}
          {q?.position_in_52w_range != null && (
            <div className="mt-1 flex items-center justify-end gap-2" role="img" aria-label={`Price is ${(q.position_in_52w_range * 100).toFixed(0)}% of the way from its 52-week low to its high`}>
              <span className="text-[11px] text-text-muted">52-wk range</span>
              <div className="h-1.5 w-24 rounded bg-border"><div className="h-1.5 rounded bg-accent" style={{ width: `${q.position_in_52w_range * 100}%` }} /></div>
            </div>
          )}
        </div>
      </div>

      {sug && sug.observations.length === 0 && sug.note && <p className="mt-2 text-xs text-warning">Price history: {sug.note}</p>}
      {sug && sug.observations.length > 0 && (
        <p className="mt-2 text-xs text-text-muted">
          Price history: {sug.observations.length} thing{sug.observations.length > 1 ? "s" : ""} to know. {sug.observations[0].title}
          {sug.observations.length > 1 ? ` (and ${sug.observations.length - 1} more in the details)` : ""}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {it.alerts.map((a) => (
          <span key={a.id} className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${a.triggered ? "border-warning text-warning" : "border-border text-text-muted"}`}>
            {a.triggered ? "Triggered: " : "Alert: "}{a.text}
            <button aria-label={`Remove alert ${a.text}`} className="underline" onClick={() => run(() => api.del(`/api/v4/watchlists/alerts/${a.id}`), "Could not remove the alert")}>remove</button>
          </span>
        ))}
        <Button size="sm" variant="secondary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? "Hide details" : "Details, alerts & notes"}</Button>
        {it.instrument_id && <Link href={`/simulate?buy=${it.instrument_id}`} className="text-xs text-accent underline">Compare adding some with doing nothing</Link>}
        <Link href={it.instrument_id ? `/theses?instrument=${it.instrument_id}` : "/theses"} className="text-xs text-accent underline">Write a rationale</Link>
        <button className="text-xs text-negative underline" onClick={() => run(() => api.del(`/api/v4/watchlists/items/${it.item_id}`), "Could not remove")}>Remove</button>
      </div>

      {open && (
        <div className="mt-3 space-y-3 border-t border-border pt-3">
          {sug && (
            <div>
              <p className="text-xs font-medium text-text-primary">What its price history says (descriptions of the past, never advice)</p>
              <SuggestionLines item={sug} />
            </div>
          )}
          {it.context.facts.length > 0 && (
            <div>
              <p className="text-xs font-medium text-text-primary">In your portfolio&apos;s terms (facts, not advice)</p>
              <ul className="list-inside list-disc text-xs text-text-muted">{it.context.facts.map((f) => <li key={f}>{f}</li>)}</ul>
            </div>
          )}
          {q && <p className="text-xs text-text-muted">Day range {rupees(q.low)} to {rupees(q.high)} · 52-week {rupees(q.week52_low)} to {rupees(q.week52_high)} · previous close {rupees(q.prev_close)}</p>}
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-text-muted">New alert
              <select className={INPUT} value={alert.kind} onChange={(e) => setAlert({ ...alert, kind: e.target.value })}>{ALERT_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            </label>
            <label className="text-xs text-text-muted">Level
              <input className={INPUT} inputMode="decimal" value={alert.threshold} onChange={(e) => setAlert({ ...alert, threshold: e.target.value })} />
            </label>
            <Button size="sm" variant="secondary" disabled={!alert.threshold.trim()} onClick={() => run(() => api.post(`/api/v4/watchlists/items/${it.item_id}/alerts`, alert).then(() => setAlert({ ...alert, threshold: "" })), "Could not add the alert")}>Add alert</Button>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs text-text-muted">Why you are watching it<input className={INPUT} value={note.why} onChange={(e) => setNote({ ...note, why: e.target.value })} /></label>
            <label className="text-xs text-text-muted">Note<input className={INPUT} value={note.note} onChange={(e) => setNote({ ...note, note: e.target.value })} /></label>
          </div>
          <Button size="sm" variant="secondary" onClick={() => run(() => api.put(`/api/v4/watchlists/items/${it.item_id}`, { note: note.note || null, why_watching: note.why || null }), "Could not save")}>Save notes</Button>
        </div>
      )}
    </li>
  );
}

export default function WatchlistPage() {
  const [data, setData] = useState<V4Watchlists | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<V4SearchResult[]>([]);
  const [needsMaster, setNeedsMaster] = useState(false);
  const [sort, setSort] = useState<"added" | "symbol" | "change" | "weight">("added");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [sugs, setSugs] = useState<Record<string, V4SuggestionItem>>({});

  useEffect(() => {
    api.get<V4Suggestions>("/api/v4/suggestions").then((s) => setSugs(Object.fromEntries(s.watched.map((i) => [i.security_id, i])))).catch(() => undefined);
  }, [data?.lists.length]);

  const load = useCallback(async () => {
    try {
      const d = await api.get<V4Watchlists>("/api/v4/watchlists");
      setData(d);
      setActive((a) => (a && d.lists.some((l) => l.id === a) ? a : d.lists[0]?.id ?? null));
    } catch (e) {
      setError(errMsg(e, "Failed to load watchlists"));
    }
  }, []);

  const refresh = useCallback(async (force = false, quiet = false) => {
    if (!quiet) setBusy(true);
    try {
      const r = await api.post<{ throttled: boolean; refreshed: number; unfetched: string[] }>(`/api/v4/watchlist/refresh?force=${force}`);
      if (!quiet) setInfo(r.throttled ? "Prices were refreshed a moment ago." : `Updated ${r.refreshed} price(s)${r.unfetched?.length ? `; ${r.unfetched.length} could not be fetched` : ""}.`);
      setError(null);
    } catch (e) {
      if (!quiet || !(e instanceof ApiError && e.status === 409)) setError(errMsg(e, "Could not refresh prices"));
    } finally {
      setBusy(false);
      load();
    }
  }, [load]);

  useEffect(() => { load(); }, [load]);

  // While the market is open and the broker session is live, refresh every 30s (the server coalesces and rate-limits).
  useEffect(() => {
    if (!data?.market.open || data.broker_session !== "connected") return;
    const id = setInterval(() => { if (document.visibilityState === "visible") refresh(false, true); }, 30000);
    return () => clearInterval(id);
  }, [data?.market.open, data?.broker_session, refresh]);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (query.trim().length < 2) { setResults([]); return; }
    timer.current = setTimeout(() => {
      api.get<{ needs_master: boolean; results: V4SearchResult[] }>(`/api/v4/market/search?q=${encodeURIComponent(query.trim())}`)
        .then((r) => { setResults(r.results); setNeedsMaster(r.needs_master); }).catch(() => undefined);
    }, 300);
  }, [query]);

  async function run(fn: () => Promise<unknown>, fallback: string) {
    setError(null);
    try { await fn(); await load(); } catch (e) { setError(errMsg(e, fallback)); }
  }

  const list = data?.lists.find((l) => l.id === active) ?? null;
  const items = [...(list?.items ?? [])].sort((a, b) => {
    if (sort === "symbol") return a.symbol.localeCompare(b.symbol);
    if (sort === "change") return Math.abs(Number(b.quote?.day_change_pct ?? 0)) - Math.abs(Number(a.quote?.day_change_pct ?? 0));
    if (sort === "weight") return Number(b.context.owned_weight ?? 0) - Number(a.context.owned_weight ?? 0);
    return 0;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Watchlist</h1>
        <p className="text-sm text-text-muted">
          Stocks you want to keep an eye on, with Angel One prices shown next to what you already hold and how much room you have under your own limits. No buy or sell
          signals, no target prices: just facts, your notes and alerts that land in your Attention list.
        </p>
      </div>
      {data && (
        <p className="text-xs text-text-muted" role="status">
          {data.market.label} · Angel One {data.broker_session === "connected" ? "connected (read-only)" : "not connected: showing the last saved prices"}
          {data.broker_session === "not_connected" && <> · <Link href="/holdings" className="text-accent underline">how to reconnect</Link></>}
        </p>
      )}
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      {info && <p role="status" className="text-sm text-text-muted">{info}</p>}

      {data && data.lists.length === 0 && (
        <Card><p className="text-sm text-text-muted">No watchlists yet. Create one below, then search for a stock to add.</p></Card>
      )}

      {data && data.lists.length > 0 && (
        <>
          <div role="group" aria-label="Watchlists" className="flex flex-wrap items-center gap-2">
            {data.lists.map((l) => (
              <button key={l.id} aria-pressed={active === l.id} onClick={() => setActive(l.id)} className={`rounded-md border px-3 py-1 text-sm ${active === l.id ? "border-accent text-accent" : "border-border text-text-muted"}`}>{l.name} ({l.items.length})</button>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Button size="sm" onClick={() => refresh(true)} loading={busy}>Refresh prices</Button>
            <label className="text-xs text-text-muted">Sort by
              <select className={INPUT} value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
                <option value="added">Order added</option><option value="symbol">Name</option><option value="change">Biggest move today</option><option value="weight">Largest holding</option>
              </select>
            </label>
            {list && <ConfirmButton label="Delete this list" consequence={`Deletes "${list.name}" and its alerts.`} confirmLabel="Delete list" onConfirm={() => run(() => api.del(`/api/v4/watchlists/${list.id}`), "Could not delete")} />}
          </div>

          <Card title="Add a stock">
            <label className="text-sm text-text-primary">Search by name or symbol
              <input className={INPUT} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. reliance" />
            </label>
            {needsMaster && (
              <p className="mt-2 text-sm text-text-muted">Angel&apos;s stock list has not been loaded yet. <Button size="sm" variant="secondary" onClick={() => run(() => api.post("/api/v4/market/instrument-master/refresh"), "Could not load the stock list")}>Load it now</Button></p>
            )}
            {results.length > 0 && list && (
              <ul className="mt-2 space-y-1 text-sm">
                {results.map((r) => (
                  <li key={r.broker_instrument_id} className="flex items-center justify-between gap-2">
                    <span className="text-text-primary">{r.symbol} <span className="text-xs text-text-muted">{r.name}{r.in_universe ? "" : " · limited portfolio context"}</span></span>
                    <Button size="sm" variant="secondary" onClick={() => run(() => api.post(`/api/v4/watchlists/${list.id}/items`, { broker_instrument_id: r.broker_instrument_id }).then(() => { setQuery(""); setResults([]); }), "Could not add")}>Add</Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {items.length === 0 ? <p className="text-sm text-text-muted">This list is empty.</p> : (
            <ul className="space-y-3" aria-label={`Stocks in ${list?.name}`}>
              {items.map((it) => <Row key={it.item_id} it={it} sug={it.security_id ? sugs[it.security_id] : undefined} onChanged={load} setError={setError} />)}
            </ul>
          )}
        </>
      )}

      <Card title="New watchlist">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-sm">Name<input className={INPUT} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Banks to study" /></label>
          <Button size="sm" disabled={!newName.trim()} onClick={() => run(() => api.post("/api/v4/watchlists", { name: newName }).then(() => setNewName("")), "Could not create")}>Create</Button>
        </div>
      </Card>
      {data && <p className="text-xs text-text-muted">{data.context_basis}. Prices come from Angel One and are labelled live, delayed or last session; the market status line shows any NSE holiday the exchange has published.</p>}
    </div>
  );
}
