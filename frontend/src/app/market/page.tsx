"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4Facets, V4MarketJobs, V4Movers, V4QuoteRefresh, V4Security, V4SecurityList } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import SecurityDetail from "@/components/market/SecurityDetail";

const PAGE = 50;
const INPUT = "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
type Kind = "stock" | "etf" | "mutual_fund";
const TABS: [Kind, string][] = [["stock", "Stocks"], ["etf", "ETFs"], ["mutual_fund", "Mutual funds"]];
const FRESH: Record<string, string> = { live: "live", delayed: "a little delayed", last_session: "last session", none: "no price" };
const CLASS_LABEL: Record<string, string> = { equity: "Equity", debt: "Debt", gold: "Gold", silver: "Silver", commodity: "Commodity", international: "International", hybrid: "Hybrid", other: "Other / unclassified" };

function errMsg(e: unknown, fallback: string) { return e instanceof ApiError ? e.message : fallback; }
function rupees(v: string | null | undefined, digits = 2) {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v);
  return Number.isNaN(n) ? "n/a" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: digits })}`;
}
function compact(n: number | null | undefined) {
  if (n === null || n === undefined) return "n/a";
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function Change({ pct }: { pct: string | null | undefined }) {
  if (pct == null) return <span className="text-text-muted">n/a</span>;
  const n = Number(pct);
  return <span className={n >= 0 ? "text-positive" : "text-negative"}>{n >= 0 ? "▲" : "▼"} {Math.abs(n).toFixed(2)}%</span>;
}

function RangeBar({ s }: { s: V4Security }) {
  const p = s.price;
  if (!p?.week52_high || !p.week52_low) return <span className="text-text-muted">n/a</span>;
  const lo = Number(p.week52_low), hi = Number(p.week52_high), x = Number(p.ltp);
  if (!(hi > lo)) return <span className="text-text-muted">n/a</span>;
  const pos = Math.min(1, Math.max(0, (x - lo) / (hi - lo)));
  return (
    <div className="flex items-center gap-2" role="img" aria-label={`${(pos * 100).toFixed(0)}% of the way from the 52-week low ${rupees(p.week52_low, 0)} to the high ${rupees(p.week52_high, 0)}`}>
      <div className="h-1.5 w-20 rounded bg-border"><div className="h-1.5 rounded bg-accent" style={{ width: `${pos * 100}%` }} /></div>
    </div>
  );
}

function TrendCell({ s }: { s: V4Security }) {
  const g = s.signals;
  if (!g || !g.trend_state) return <span className="text-text-muted">n/a</span>;
  return <span className={g.trend_state === "above" ? "text-positive" : "text-negative"}>{g.trend_state === "above" ? "▲ above" : "▼ below"}</span>;
}

function MoverList({ title, items, show }: { title: string; items: V4Security[]; show: "pct" | "volume" }) {
  return (
    <Card title={title}>
      {items.length === 0 ? <p className="text-xs text-text-muted">No data yet.</p> : (
        <ul className="space-y-1 text-sm">
          {items.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-2">
              <span className="truncate text-text-primary" title={s.name}>{s.symbol}</span>
              <span className="text-xs">{show === "pct" ? <Change pct={s.price?.percent_change} /> : compact(s.price?.volume)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function MarketPage() {
  const [kind, setKind] = useState<Kind>("stock");
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [sector, setSector] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [category, setCategory] = useState("");
  const [plan, setPlan] = useState<"" | "direct" | "regular">("direct");
  const [option, setOption] = useState<"" | "growth" | "idcw">("growth");
  const [trend, setTrend] = useState<"" | "above" | "below">("");
  const [sort, setSort] = useState<"name" | "change" | "volume" | "price" | "sector" | "momentum" | "volatility" | "drawdown" | "ter">("volume");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [offset, setOffset] = useState(0);
  const [userSorted, setUserSorted] = useState(false); // while searching, relevance wins unless the user picked a sort
  const [data, setData] = useState<V4SecurityList | null>(null);
  const [facets, setFacets] = useState<V4Facets | null>(null);
  const [movers, setMovers] = useState<V4Movers | null>(null);
  const [jobs, setJobs] = useState<V4MarketJobs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [market, setMarket] = useState<V4QuoteRefresh["market"] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dqRef = useRef("");
  dqRef.current = dq;
  const reqId = useRef(0);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { if (q.trim() === dqRef.current) return; setDq(q.trim()); setOffset(0); if (q.trim() === "") setUserSorted(false); }, 300);
  }, [q]);

  // Coming back from a security page (or reloading) returns to the list as you left it: same type, search, filters and page.
  const restored = useRef(false);
  useEffect(() => {
    try {
      const v = JSON.parse(sessionStorage.getItem("market.view") ?? "null");
      if (v) {
        if (v.kind) setKind(v.kind);
        if (typeof v.q === "string") { setQ(v.q); setDq(v.q.trim()); }
        setSector(v.sector ?? ""); setAssetClass(v.assetClass ?? ""); setCategory(v.category ?? ""); setPlan(v.plan ?? "direct"); setOption(v.option ?? "growth");
        setTrend(v.trend ?? ""); if (v.sort) setSort(v.sort); if (v.order) setOrder(v.order); setOffset(v.offset ?? 0); setUserSorted(!!v.userSorted);
      }
    } catch { /* no saved view */ }
    restored.current = true;
  }, []);
  useEffect(() => {
    if (!restored.current) return;
    try { sessionStorage.setItem("market.view", JSON.stringify({ kind, q, sector, assetClass, category, plan, option, trend, sort, order, offset, userSorted })); } catch { /* ignore */ }
  }, [kind, q, sector, assetClass, category, plan, option, trend, sort, order, offset, userSorted]);

  const isFund = kind === "mutual_fund";
  const load = useCallback(async () => {
    const id = ++reqId.current;
    setLoading(true);
    const p = new URLSearchParams({ kind, limit: String(PAGE), offset: String(offset) });
    if (dq) p.set("q", dq);
    if (kind === "stock" && sector) p.set("sector", sector);
    if (!isFund && trend) p.set("trend", trend);
    if (kind !== "mutual_fund" && assetClass) p.set("asset_class", assetClass);
    if (isFund) {
      if (assetClass) p.set("asset_class", assetClass);
      if (category) p.set("category", category);
      if (plan) p.set("plan", plan);
      if (option) p.set("option", option);
    }
    const relevance = dq !== "" && !userSorted;
    const effSort = relevance || (isFund && sort !== "name" && sort !== "ter") ? "name" : sort;
    p.set("sort", effSort);
    p.set("order", relevance ? "asc" : order);
    try {
      const d = await api.get<V4SecurityList>(`/api/v4/catalogue/securities?${p}`);
      if (id === reqId.current) { setData(d); setError(null); }
    } catch (e) {
      if (id === reqId.current) setError(errMsg(e, "Could not load the market list"));
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, [kind, dq, sector, assetClass, category, plan, option, sort, order, offset, isFund, userSorted, trend]);

  useEffect(() => { load(); }, [load]);

  // Which watchlist "Watch" adds to. With one list there is nothing to choose; with several the choice is explicit and remembered.
  const [lists, setLists] = useState<{ id: string; name: string }[]>([]);
  const [targetList, setTargetList] = useState("");
  useEffect(() => {
    api.get<{ lists: { id: string; name: string }[] }>("/api/v4/watchlists").then((r) => {
      setLists(r.lists);
      let saved = "";
      try { saved = localStorage.getItem("market.watchlist") ?? ""; } catch { /* private mode: fine */ }
      setTargetList(r.lists.some((l) => l.id === saved) ? saved : (r.lists[0]?.id ?? ""));
    }).catch(() => setLists([]));
  }, []);
  useEffect(() => {
    api.get<V4Facets>("/api/v4/catalogue/facets").then(setFacets).catch(() => undefined);
    api.get<V4Movers>("/api/v4/catalogue/movers?kind=stock&min_volume=100000").then(setMovers).catch(() => undefined);
    api.get<V4MarketJobs>("/api/v4/catalogue/market-jobs").then(setJobs).catch(() => undefined);
  }, []);

  // Refresh only the rows on screen (at most one broker request); the server decides whether a call is needed at all.
  const refreshVisible = useCallback(async () => {
    const ids = (data?.items ?? []).filter((s) => s.tradable_in_angel).map((s) => s.id).slice(0, 50);
    if (ids.length === 0) return;
    try {
      const r = await api.post<V4QuoteRefresh>("/api/v4/catalogue/quotes/refresh", { security_ids: ids });
      setMarket(r.market);
      setInfo(r.reason);
      if (r.refreshed) {
        const byId = new Map(r.items.map((s) => [s.id, s]));
        setData((d) => (d ? { ...d, items: d.items.map((s) => byId.get(s.id) ?? s) } : d));
      }
    } catch { /* the saved prices stay on screen */ }
  }, [data?.items]);

  // One refresh per page of results (not per render): keyed on the ids on screen.
  const idsKey = data?.items.map((s) => s.id).join(",") ?? "";
  const refreshRef = useRef(refreshVisible);
  refreshRef.current = refreshVisible;
  useEffect(() => { if (idsKey && !isFund) refreshRef.current(); }, [idsKey, isFund]);
  useEffect(() => {
    if (!market?.open || isFund) return;
    const t = setInterval(() => { if (document.visibilityState === "visible") refreshVisible(); }, 30000);
    return () => clearInterval(t);
  }, [market?.open, isFund, refreshVisible]);

  function switchKind(k: Kind) {
    setKind(k); setOffset(0); setSector(""); setAssetClass(""); setCategory(""); setOpen(null); setInfo(null);
    // Funds have no volume or day change: A to Z. Stocks and ETFs default to the most traded.
    if (k === "mutual_fund") { setSort("name"); setOrder("asc"); }
    else if (sort === "name" || sort === "sector") { setSort("volume"); setOrder("desc"); }
  }

  async function watch(s: V4Security) {
    setError(null); setInfo(null);
    try {
      const lists = await api.get<{ lists: { id: string; name: string }[] }>("/api/v4/watchlists");
      let list = lists.lists.find((l) => l.id === targetList) ?? lists.lists[0];
      if (!list) list = await api.post<{ id: string; name: string }>("/api/v4/watchlists", { name: "My watchlist" });
      await api.post(`/api/v4/watchlists/${list.id}/items`, { broker_instrument_id: s.broker_instrument_id });
      setInfo(`${s.symbol} added to "${list.name}".`);
    } catch (e) { setError(errMsg(e, "Could not add to the watchlist")); }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;
  const page = Math.floor(offset / PAGE) + 1;
  const classes = (facets?.asset_classes ?? []);
  const priced = (jobs?.quotes ?? 0) > 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Market</h1>
        <p className="text-sm text-text-muted">
          Every NSE stock, exchange-traded fund and mutual fund scheme we know of, with prices from Angel One (stocks, ETFs) and AMFI (fund NAVs). This is a browsing page: it does not tell you what to buy. Stocks and ETFs are bought in Angel One; so are mutual funds.
        </p>
      </div>

      {facets && (
        <p className="text-xs text-text-muted" role="status">
          {facets.kinds.stock ?? 0} stocks ({facets.unclassified_stocks} without a sector) · {facets.kinds.etf ?? 0} ETFs · {facets.kinds.mutual_fund ?? 0} active fund schemes
          {market && <> · {market.label}</>}
          {jobs && <> · prices saved for {jobs.quotes} instruments · price history for {jobs.candle_securities} · <Link href="/data" className="underline">when it updates</Link></>}
          {jobs?.candle_backfill?.status === "running" || (jobs?.candle_backfill?.status === "queued") ? " (history is still being collected in the background)" : ""}
        </p>
      )}

      <div role="group" aria-label="Kind of investment" className="flex flex-wrap gap-2">
        {TABS.map(([k, l]) => <button key={k} aria-pressed={kind === k} onClick={() => switchKind(k)} className={`rounded-md border px-3 py-1 text-sm ${kind === k ? "border-accent text-accent" : "border-border text-text-muted"}`}>{l}{facets?.kinds[k] != null ? ` (${facets.kinds[k]})` : ""}</button>)}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-xs text-text-muted sm:col-span-2">Search by name, symbol or ISIN
          <input className={INPUT} value={q} onChange={(e) => setQ(e.target.value)} placeholder={isFund ? "e.g. nifty 50 index" : "e.g. reliance"} />
        </label>
        {kind === "stock" && (
          <label className="text-xs text-text-muted">Sector
            <select className={INPUT} value={sector} onChange={(e) => { setSector(e.target.value); setOffset(0); }}>
              <option value="">All sectors</option>
              {facets?.sectors.map((s) => <option key={s.value} value={s.value}>{s.value} ({s.count})</option>)}
            </select>
          </label>
        )}
        {kind !== "stock" && (
          <label className="text-xs text-text-muted">What it invests in
            <select className={INPUT} value={assetClass} onChange={(e) => { setAssetClass(e.target.value); setOffset(0); }}>
              <option value="">Anything</option>
              {classes.filter((c) => c.value !== "other" || isFund).map((c) => <option key={c.value} value={c.value}>{CLASS_LABEL[c.value] ?? c.value}</option>)}
            </select>
          </label>
        )}
        {isFund && (
          <>
            <label className="text-xs text-text-muted">Category
              <select className={INPUT} value={category} onChange={(e) => { setCategory(e.target.value); setOffset(0); }}>
                <option value="">All categories</option>
                {facets?.fund_categories.map((c) => <option key={c.value} value={c.value}>{c.value} ({c.count})</option>)}
              </select>
            </label>
            <label className="text-xs text-text-muted">Plan
              <select className={INPUT} value={plan} onChange={(e) => { setPlan(e.target.value as typeof plan); setOffset(0); }}>
                <option value="direct">Direct (lower cost)</option><option value="regular">Regular</option><option value="">Both</option>
              </select>
            </label>
            <label className="text-xs text-text-muted">Option
              <select className={INPUT} value={option} onChange={(e) => { setOption(e.target.value as typeof option); setOffset(0); }}>
                <option value="growth">Growth</option><option value="idcw">IDCW (payouts)</option><option value="">Both</option>
              </select>
            </label>
          </>
        )}
        <label className="text-xs text-text-muted">Sort by
          <select className={INPUT} value={sort} onChange={(e) => { setSort(e.target.value as typeof sort); setUserSorted(true); setOffset(0); }}>
            <option value="name">Name</option>
            {!isFund && <><option value="change">Day change</option><option value="volume">Volume</option><option value="price">Price</option></>}
            {isFund && <option value="ter">Expense ratio</option>}
            {!isFund && <><option value="momentum">1-year momentum</option><option value="volatility">Volatility</option><option value="drawdown">Distance from 52-week high</option></>}
            {kind === "stock" && <option value="sector">Sector</option>}
          </select>
        </label>
        {!isFund && (
          <label className="text-xs text-text-muted">Price trend
            <select className={INPUT} value={trend} onChange={(e) => { setTrend(e.target.value as typeof trend); setOffset(0); }}>
              <option value="">Any</option><option value="above">Above its 200-day average</option><option value="below">Below its 200-day average</option>
            </select>
          </label>
        )}
        <label className="text-xs text-text-muted">Order
          <select className={INPUT} value={order} onChange={(e) => { setOrder(e.target.value as typeof order); setUserSorted(true); setOffset(0); }}>
            <option value="asc">Low to high / A to Z</option><option value="desc">High to low / Z to A</option>
          </select>
        </label>
      </div>

      {movers && priced && kind === "stock" && (
        <details className="rounded-lg border border-border bg-surface p-3 shadow-sm">
          <summary className="cursor-pointer text-sm font-medium text-text-primary">Stock movers in the last session</summary>
          <section aria-label="Market movers" className="mt-3 grid gap-3 sm:grid-cols-3">
            <MoverList title="Top gainers" items={movers.gainers.slice(0, 5)} show="pct" />
            <MoverList title="Top losers" items={movers.losers.slice(0, 5)} show="pct" />
            <MoverList title="Most traded" items={movers.most_traded.slice(0, 5)} show="volume" />
          </section>
          {movers.as_of && <p className="mt-2 text-xs text-text-muted">Saved prices as of {new Date(movers.as_of).toLocaleString("en-IN")}; thinly traded stocks (under 1 lakh shares) are left out.</p>}
        </details>
      )}


      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      {lists.length > 1 && (
        <label className="flex items-center gap-2 text-xs text-text-muted">
          Watch adds to
          <select className="rounded-md border border-border bg-surface px-2 py-1 text-xs" value={targetList}
            onChange={(e) => { setTargetList(e.target.value); try { localStorage.setItem("market.watchlist", e.target.value); } catch { /* ignore */ } }}>
            {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
      )}
      {info && <p role="status" className="text-xs text-text-muted">{info}</p>}

      <p className="text-xs text-text-muted xl:hidden">Narrow screen: price and day change are shown here. Open a row for the full picture, or widen the window for more columns.</p>
      <div tabIndex={0} className="relative overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm ">
          <caption className="sr-only">{TABS.find(([k]) => k === kind)?.[1]} list, {data?.total ?? 0} results</caption>
          <thead className="bg-bg text-xs text-text-muted">
            {isFund ? (
              <tr><th scope="col" className="p-2">Scheme</th><th scope="col" className="hidden p-2 sm:table-cell">Category</th><th scope="col" className="p-2 text-right">NAV</th><th scope="col" className="p-2 text-right">Expense ratio</th><th scope="col" className="hidden p-2 md:table-cell">As of</th><th scope="col" className="p-2"><span className="sr-only">Actions</span></th></tr>
            ) : (
              <tr><th scope="col" className="p-2">Name</th><th scope="col" className="p-2 text-right">Price</th><th scope="col" className="p-2 text-right">Day</th><th scope="col" className="hidden p-2 xl:table-cell">52-week range</th><th scope="col" className="hidden p-2 text-right lg:table-cell">Volume</th><th scope="col" className="hidden p-2 lg:table-cell">200-day trend</th><th scope="col" className="hidden p-2 text-right xl:table-cell">1-yr momentum</th><th scope="col" className="hidden p-2 text-right xl:table-cell">Volatility</th><th scope="col" className="p-2"><span className="sr-only">Actions</span></th></tr>
            )}
          </thead>
          <tbody>
            {data?.items.length === 0 && <tr><td colSpan={10} className="p-4 text-center text-text-muted">{loading ? "Loading…" : "Nothing matches these filters."}</td></tr>}
            {data?.items.map((s) => (
              <Fragment key={s.id}>
                <tr className="border-t border-border align-top">
                  <td className="p-2">
                    <p className="font-medium text-text-primary"><Link href={`/market/${s.id}`} className="hover:text-accent hover:underline">{s.symbol ?? s.name}</Link>{!s.is_active && <span className="ml-1 text-xs text-warning">inactive</span>}</p>
                    <p className="max-w-[6.5rem] truncate text-xs text-text-muted sm:max-w-xs" title={s.name}>{isFund ? `${s.name} · ${s.plan ?? "plan n/a"} · ${s.option ?? "option n/a"}` : s.name}{kind === "stock" && s.sector ? ` · ${s.sector}` : ""}</p>
                  </td>
                  {isFund ? (
                    <>
                      <td className="hidden p-2 text-xs text-text-muted sm:table-cell">{s.category ?? "n/a"}<br />{s.amc}</td>
                      <td className="p-2 text-right">{rupees(s.nav, 4)}</td>
                      <td className="p-2 text-right text-xs">{s.ter ? `${Number(s.ter.percent).toFixed(2)}% a year` : <span className="text-text-muted" title="No defensible match to AMFI's expense-ratio file">unknown</span>}</td>
                      <td className="hidden p-2 text-xs text-text-muted md:table-cell">{s.nav_date}</td>
                    </>
                  ) : (
                    <>
                      <td className="p-2 text-right">{s.price ? rupees(s.price.ltp) : <span className="text-text-muted">{s.tradable_in_angel ? "no price yet" : "not in Angel"}</span>}
                        {s.price && <p className="text-[11px] text-text-muted">{FRESH[s.price.freshness]}</p>}</td>
                      <td className="p-2 text-right"><Change pct={s.price?.percent_change} /></td>
                      <td className="hidden p-2 xl:table-cell"><RangeBar s={s} /></td>
                      <td className="hidden p-2 text-right text-xs lg:table-cell">{compact(s.price?.volume)}</td>
                      <td className="hidden p-2 text-xs lg:table-cell"><TrendCell s={s} /></td>
                      <td className="hidden p-2 text-right text-xs xl:table-cell">{s.signals?.mom_12_1_rank != null ? `stronger than ${s.signals.mom_12_1_rank.toFixed(0)}%` : <span className="text-text-muted">n/a</span>}</td>
                      <td className="hidden p-2 text-right text-xs xl:table-cell">{s.signals?.vol_252 != null ? `${(s.signals.vol_252 * 100).toFixed(0)}%` : <span className="text-text-muted">n/a</span>}</td>
                    </>
                  )}
                  <td className="p-2 text-right sm:whitespace-nowrap"><div className="flex flex-col items-end gap-1 sm:block">
                    <Button size="sm" variant="secondary" aria-expanded={open === s.id} onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? "Hide" : "Details"}</Button>
                    {!isFund && s.broker_instrument_id && <Button size="sm" variant="secondary" className="sm:ml-1" onClick={() => watch(s)} aria-label={`Add ${s.symbol} to watchlist`}>Watch</Button>}
                  </div></td>
                </tr>
                {open === s.id && <tr><td colSpan={10} className="p-0"><div className="flex justify-end border-t border-border bg-bg/40 px-3 pt-2"><Link href={`/market/${s.id}`} className="text-xs font-medium text-accent hover:text-accent-hover">Open full page, with actions and a link you can keep</Link></div><SecurityDetail id={s.id} /></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.total > PAGE && (
        <nav aria-label="Pages" className="flex items-center justify-between text-sm">
          <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</Button>
          <span className="text-text-muted">Page {page} of {pages} · {data.total.toLocaleString("en-IN")} results</span>
          <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setOffset(offset + PAGE)}>Next</Button>
        </nav>
      )}
      <p className="text-xs text-text-muted">
        Prices are from Angel One and labelled live, delayed or last session; NSE trading holidays are applied for the years the exchange has published (the status line above says which). Fund NAVs are AMFI&apos;s official end-of-day figures. Sector data covers the larger listed companies only. Nothing here is a recommendation.
      </p>
    </div>
  );
}
