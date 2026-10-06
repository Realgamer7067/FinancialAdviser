"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4History, V4SecurityDetail } from "@/lib/types";
import Button from "@/components/ui/Button";
import PriceChart from "./PriceChart";
import SignalsPanel from "./SignalsPanel";

const RANGES: [string, number][] = [["1M", 30], ["6M", 182], ["1Y", 365], ["5Y", 1830]];
const AUDIT_TEXT: Record<string, string> = {
  adjusted: "already adjusted by the data source (checked against the prices)",
  raw: "was still unadjusted in the data, so we adjusted it",
  indeterminate: "too small to tell from an ordinary move, so left as delivered",
  unclear: "the price move around it matches neither case, so history there is unreliable",
  conflict: "NSE lists conflicting figures for it, so it was not applied",
  outside: "falls outside the stored history",
  no_data: "no prices around it",
};
const KIND: Record<string, string> = { bonus: "Bonus", split: "Split", dividend: "Dividend", rights: "Rights issue", demerger: "Demerger", buyback: "Buyback", meeting: "Meeting", other: "Other" };

function rupees(v: string | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v);
  return Number.isNaN(n) ? "n/a" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export default function SecurityDetail({ id }: { id: string }) {
  const [detail, setDetail] = useState<V4SecurityDetail | null>(null);
  const [hist, setHist] = useState<V4History | null>(null);
  const [days, setDays] = useState(365);
  const [msg, setMsg] = useState<string | null>(null);

  const loadHist = useCallback(async () => {
    try { setHist(await api.get<V4History>(`/api/v4/catalogue/securities/${id}/history?days=${days}`)); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : "Could not load history"); }
  }, [id, days]);

  useEffect(() => { api.get<V4SecurityDetail>(`/api/v4/catalogue/securities/${id}`).then(setDetail).catch((e) => setMsg(e instanceof ApiError ? e.message : "Could not load details")); }, [id]);
  useEffect(() => { loadHist(); }, [loadHist]);
  // While a fetch is queued, look again every few seconds.
  useEffect(() => {
    if (hist?.status !== "queued") return;
    const t = setInterval(loadHist, 5000);
    return () => clearInterval(t);
  }, [hist?.status, loadHist]);

  async function fetchNav() {
    setMsg(null);
    try { await api.post(`/api/v4/catalogue/securities/${id}/nav-history/sync`); setHist((h) => (h ? { ...h, status: "queued" } : h)); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : "Could not queue the NAV fetch"); }
  }

  async function fetchHistory() {
    setMsg(null);
    try { await api.post(`/api/v4/catalogue/securities/${id}/history/sync`); await loadHist(); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : "Could not queue the fetch"); }
  }

  const reviewMarks = (hist?.adjustment?.unreliable ?? []).map((u) => ({ d: u.date, label: u.reason }));
  return (
    <div className="space-y-3 border-t border-border bg-bg/40 p-3" data-testid="security-detail">
      {msg && <p role="alert" className="text-sm text-negative">{msg}</p>}
      {detail && (
        <p className="text-xs text-text-muted">
          {detail.isin && <>ISIN {detail.isin} · </>}{detail.series && <>series {detail.series} · </>}{detail.lot_size != null && <>lot {detail.lot_size} · </>}
          {detail.face_value && <>face value ₹{detail.face_value} · </>}{detail.listing_date && <>listed {detail.listing_date} · </>}
          {detail.tradable_in_angel ? "tradable in Angel One" : "not found in Angel One's equity list"}
          {detail.kind !== "stock" && <> · {detail.ter ? `expense ratio ${Number(detail.ter.percent).toFixed(2)}% a year (${detail.ter.plan} plan, AMFI, ${detail.ter.as_of})` : "expense ratio not known (no defensible match to AMFI's file)"}</>}
        </p>
      )}

      {detail?.kind === "mutual_fund" && (
        <div className="space-y-2">
          <p className="text-sm text-text-muted">
            NAV {rupees(detail.nav)} as of {detail.nav_date}. {detail.plan === "direct" ? "Direct plan: no distributor commission." : detail.plan === "regular" ? "Regular plan: includes distributor commission, so the same fund costs more over time than its direct plan." : "Plan not stated by AMFI."}
            {" "}Mutual funds are bought in the Angel One app, not through this one.
          </p>
          {hist?.status === "unsupported" && detail.option === "growth" && <Button size="sm" variant="secondary" onClick={fetchNav}>Fetch NAV history</Button>}
          {hist?.status === "unsupported" && detail.option !== "growth" && <p className="text-xs text-text-muted">No NAV history is kept for this option: an IDCW NAV falls on every payout, so it is not a return series.</p>}
          {hist?.status === "queued" && <p role="status" className="text-sm text-text-muted">NAV history is being fetched and checked against AMFI&apos;s figure. This page will update by itself.</p>}
        </div>
      )}
      {detail?.kind !== "mutual_fund" && (
        <>
          {hist?.status === "none" && (
            <div className="text-sm text-text-muted">
              No price history stored yet.{" "}
              {hist.tradable_in_angel !== false
                ? <Button size="sm" variant="secondary" onClick={fetchHistory}>Fetch 5 years of history</Button>
                : "This is not in Angel One's equity list, so there is no source for it."}
            </div>
          )}
          {hist?.status === "queued" && <p role="status" className="text-sm text-text-muted">History is being fetched in the background. This page will update by itself.</p>}
        </>
      )}
      {hist?.status === "ready" && (
        <>
          <div role="group" aria-label="Chart range" className="flex gap-1">
            {RANGES.map(([l, d]) => <button key={l} aria-pressed={days === d} onClick={() => setDays(d)} className={`rounded border px-2 py-0.5 text-xs ${days === d ? "border-accent text-accent" : "border-border text-text-muted"}`}>{l}</button>)}
          </div>
          <PriceChart points={hist.candles.map((c) => ({ d: c.d, c: Number(c.c) }))} marks={reviewMarks} />
          {hist.coverage && <p className="text-xs text-text-muted">History {hist.coverage.first_date} to {hist.coverage.last_date} ({hist.coverage.rows} {detail?.kind === "mutual_fund" ? "daily NAVs" : "sessions"}), fetched {new Date(hist.coverage.fetched_at).toLocaleString("en-IN")}.{hist.coverage.last_error ? ` Last problem: ${hist.coverage.last_error}.` : ""}</p>}
          {hist.adjustment && hist.adjustment.audit.some((a) => a.status !== "outside") && (
            <div>
              <p className="text-xs font-medium text-text-primary">Splits and bonuses in this history</p>
              <ul className="list-inside list-disc text-xs text-text-muted">
                {hist.adjustment.audit.filter((a) => a.status !== "outside").map((a) => <li key={`${a.ex_date}-${a.kind}`}>{KIND[a.kind] ?? a.kind} on {a.ex_date}: {AUDIT_TEXT[a.status] ?? a.status}</li>)}
              </ul>
            </div>
          )}
          {hist.adjustment && hist.adjustment.unreliable.length > 0 && (
            <div className="rounded border border-warning p-2">
              <p className="text-xs font-medium text-warning">Treat prices around these dates with care (dashed lines on the chart)</p>
              <ul className="list-inside list-disc text-xs text-text-muted">{hist.adjustment.unreliable.map((u) => <li key={u.date + u.reason}>{u.reason}</li>)}</ul>
            </div>
          )}
        </>
      )}

      {hist?.status === "ready" && <SignalsPanel id={id} />}

      {detail && detail.corporate_actions.length > 0 && (
        <div>
          <p className="text-xs font-medium text-text-primary">Recent company actions (from NSE)</p>
          <ul className="space-y-0.5 text-xs text-text-muted">
            {detail.corporate_actions.slice(0, 8).map((a) => (
              <li key={a.ex_date + a.subject}>{a.ex_date} · {KIND[a.kind] ?? a.kind}{a.amount ? ` ₹${a.amount} per share` : ""}{a.price_factor ? ` (price factor ${Number(a.price_factor).toFixed(3)})` : ""}{a.needs_review ? " · not adjusted automatically" : ""}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
