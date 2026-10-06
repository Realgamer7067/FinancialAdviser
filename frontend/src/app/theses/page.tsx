"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4Assessment, V4Instrument, V4Thesis } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

const INPUT = "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

const STATUS: Record<V4Assessment["status"], { label: string; text: string }> = {
  supported: { label: "SUPPORTED", text: "New evidence fits your conditions, with independent corroboration." },
  mixed: { label: "MIXED", text: "Some conditions are met, but not all, or only one source backs them." },
  weakened: { label: "WEAKENED", text: "Evidence points against something your thesis relies on." },
  insufficient: { label: "NOT ENOUGH EVIDENCE", text: "What was found does not address your conditions." },
};

const VERDICT: Record<string, string> = { supported: "Evidence says this holds", contradicted: "Evidence says this does not hold", no_evidence: "No evidence either way" };

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

export default function ThesesPage() {
  const [theses, setTheses] = useState<V4Thesis[]>([]);
  const [instruments, setInstruments] = useState<V4Instrument[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, V4Assessment>>({});
  const [form, setForm] = useState({ instrument_id: "", ownership: "considered", reason: "", confirmed: false });
  const [conds, setConds] = useState<{ text: string; kind: "supports" | "invalidates" }[]>([{ text: "", kind: "supports" }, { text: "", kind: "invalidates" }]);
  const [priceNote, setPriceNote] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const [t, i] = await Promise.all([api.get<V4Thesis[]>("/api/v4/theses"), api.get<V4Instrument[]>("/api/v4/instruments")]);
      setTheses(t);
      setInstruments(i);
      // Arriving from a watchlist row ("Write a rationale"): that stock is chosen for you. Otherwise nothing is
      // pre-selected, so a rationale is never saved against whichever stock happens to be first in the list.
      const wanted = new URLSearchParams(window.location.search).get("instrument");
      setForm((f) => (f.instrument_id ? f : { ...f, instrument_id: wanted && i.some((x) => x.id === wanted) ? wanted : "" }));
    } catch (e) {
      setError(errMsg(e, "Failed to load"));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function create() {
    setError(null);
    try {
      await api.post("/api/v4/theses", { ...form, conditions: conds.filter((c) => c.text.trim().length >= 5) });
      setForm({ ...form, reason: "", confirmed: false });
      setConds([{ text: "", kind: "supports" }, { text: "", kind: "invalidates" }]);
      await load();
    } catch (e) {
      setError(errMsg(e, "Could not save the thesis"));
    }
  }

  async function refresh(t: V4Thesis) {
    setBusy(t.chain_id);
    setError(null);
    try {
      const a = await api.post<V4Assessment>(`/api/v4/theses/${t.chain_id}/refresh`);
      setDetail((d) => ({ ...d, [t.chain_id]: a }));
      await load();
    } catch (e) {
      setError(errMsg(e, "Evidence refresh failed"));
    } finally {
      setBusy(null);
    }
  }

  async function openLatest(t: V4Thesis) {
    if (!t.latest_assessment) return;
    const all = await api.get<V4Assessment[]>(`/api/v4/theses/${t.chain_id}/assessments`);
    if (all[0]) setDetail((d) => ({ ...d, [t.chain_id]: all[0] }));
  }

  async function ack(t: V4Thesis, a: V4Assessment) {
    await api.post(`/api/v4/theses/${t.chain_id}/assessments/${a.assessment_id}/acknowledge`);
    await load();
    await openLatest(t);
  }

  async function price(t: V4Thesis) {
    const r = await api.post<{ status: string; move_5_sessions?: number; move_20_sessions?: number | null; as_of?: string }>(`/api/v4/theses/${t.chain_id}/price-check`);
    setPriceNote((p) => ({ ...p, [t.chain_id]: r.status === "insufficient_history" ? "Not enough price history to check."
      : `5-session move ${(100 * (r.move_5_sessions ?? 0)).toFixed(1)}%${r.move_20_sessions != null ? `, 20-session ${(100 * r.move_20_sessions).toFixed(1)}%` : ""} as of ${r.as_of}. Price moves are noted, but never change your thesis.` }));
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Theses</h1>
        <p className="text-sm text-text-muted">
          Write down why you hold (or are considering) a stock and what would prove you right or wrong. We check new evidence against YOUR conditions on request and show
          what changed and which sources say so. Your wording is never edited by us, there is no score, and nothing here changes your portfolio review.
        </p>
      </div>
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}

      {theses.map((t) => {
        const a = detail[t.chain_id] ?? null;
        const latest = a ?? t.latest_assessment;
        return (
          <Card key={t.chain_id}>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-medium text-text-primary">{t.symbol}</h3>
              <span className="text-xs text-text-muted">{t.ownership === "owned" ? "You own it" : "Considering it"} · version {t.version}{t.status === "closed" ? " · closed" : ""}</span>
              {latest && <span className="rounded-md border border-border px-2 py-0.5 text-xs font-semibold tracking-wide text-text-primary">{STATUS[latest.status].label}</span>}
            </div>
            <p className="mt-1 text-sm text-text-muted">&ldquo;{t.reason}&rdquo;</p>
            <ul className="mt-2 list-inside list-disc text-sm text-text-muted">
              {t.conditions.map((c) => <li key={c.id}>{c.kind === "supports" ? "I am right if" : "I am wrong if"}: {c.text}</li>)}
            </ul>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => refresh(t)} loading={busy === t.chain_id} disabled={t.status !== "active"}>Check new evidence</Button>
              <Button size="sm" variant="secondary" onClick={() => price(t)}>Check the price</Button>
              {t.latest_assessment && !a && <Button size="sm" variant="secondary" onClick={() => openLatest(t)}>Show the evidence</Button>}
            </div>
            {priceNote[t.chain_id] && <p className="mt-1 text-xs text-text-muted">{priceNote[t.chain_id]}</p>}

            {latest && (
              <div className="mt-3 space-y-2 rounded-md border border-border p-3 text-sm" aria-live="polite">
                <p className="text-text-primary">{STATUS[latest.status].text}</p>
                <p className="text-xs text-text-muted">{latest.change_log}</p>
                <p className="text-xs text-text-muted">{latest.portfolio_effect}</p>
                {a?.per_condition && (
                  <ul className="space-y-2">
                    {a.per_condition.map((c) => (
                      <li key={c.condition_id}>
                        <strong className="text-text-primary">{c.text}</strong>: {VERDICT[c.verdict]}
                        {c.verdict !== "no_evidence" && <span className="text-xs text-text-muted"> ({c.independent_sources} independent source{c.independent_sources === 1 ? "" : "s"}{c.lineages.length ? `: ${c.lineages.join(", ")}` : ""})</span>}
                        {c.note && <><br /><span className="text-text-muted">{c.note}</span></>}
                        {c.cited_fact_ids.map((f) => a.evidence?.[f] && (
                          <p key={f} className="text-xs text-text-muted">Evidence: {a.evidence[f].text} (
                            {a.evidence[f].supporting.map((s, i) => <span key={i}><a className="text-accent underline" href={s.url} target="_blank" rel="noreferrer">{s.lineage}</a>{s.publication_time ? `, published ${s.publication_time.slice(0, 10)}` : ""}{i < a.evidence![f].supporting.length - 1 ? "; " : ""}</span>)})</p>
                        ))}
                        {c.dropped.map((d) => <p key={d} className="text-xs text-warning">Not used: {d}</p>)}
                      </li>
                    ))}
                  </ul>
                )}
                {a?.gaps && a.gaps.length > 0 && <div><p className="text-xs font-medium text-text-primary">What is missing</p><ul className="list-inside list-disc text-xs text-text-muted">{a.gaps.map((g) => <li key={g}>{g}</li>)}</ul></div>}
                {a?.contradictions && a.contradictions.length > 0 && <p className="text-xs text-warning">{a.contradictions.length} contradiction(s) between sources were found.</p>}
                {a?.verification && <p className="text-xs text-text-muted">{a.verification.supported_count} of {a.verification.total_material_claims} claims checked against source text. {a.verification.caveat}</p>}
                {a?.model_info && <p className="text-xs text-text-muted">{a.model_info.used ? `A language model only matched evidence to your conditions (${a.model_info.model ?? "model"}); it did not set the status.` : "No language model was used for matching."}</p>}
                <p className="text-xs text-text-muted">This is a research aid, not advice. Reviewed: {latest.review_status === "acknowledged" ? "yes" : "not yet"}.</p>
                {latest.review_status === "pending" && <Button size="sm" variant="secondary" onClick={() => ack(t, latest)}>I have reviewed this</Button>}
              </div>
            )}
          </Card>
        );
      })}

      <Card title="Add an investment rationale">
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="text-sm">Stock<select className={INPUT} value={form.instrument_id} onChange={(e) => setForm({ ...form, instrument_id: e.target.value })}><option value="">Choose a stock…</option>{instruments.map((i) => <option key={i.id} value={i.id}>{i.symbol}</option>)}</select></label>
          <label className="text-sm">Your relationship<select className={INPUT} value={form.ownership} onChange={(e) => setForm({ ...form, ownership: e.target.value })}><option value="considered">I am considering it</option><option value="owned">I own it (checked against your holdings)</option></select></label>
        </div>
        <label className="mt-3 block text-sm">Why, in your own words<textarea className={INPUT} rows={3} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
        <p className="mt-3 text-sm font-medium text-text-primary">What would prove you right or wrong?</p>
        {conds.map((c, i) => (
          <div key={i} className="mt-2 flex flex-wrap items-end gap-2">
            <label className="text-sm">Type<select className={INPUT} value={c.kind} onChange={(e) => setConds(conds.map((x, j) => j === i ? { ...x, kind: e.target.value as "supports" | "invalidates" } : x))}><option value="supports">I am right if…</option><option value="invalidates">I am wrong if…</option></select></label>
            <label className="grow text-sm">Condition (something that can be checked)<input className={INPUT} value={c.text} onChange={(e) => setConds(conds.map((x, j) => j === i ? { ...x, text: e.target.value } : x))} /></label>
          </div>
        ))}
        <div className="mt-2"><Button size="sm" variant="secondary" onClick={() => setConds([...conds, { text: "", kind: "supports" }])} disabled={conds.length >= 8}>Add another condition</Button></div>
        <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={form.confirmed} onChange={(e) => setForm({ ...form, confirmed: e.target.checked })} /> This is my own thesis and I confirm it</label>
        <div className="mt-3"><Button size="sm" onClick={create} disabled={!form.instrument_id || !form.confirmed || form.reason.trim().length < 10 || !conds.some((c) => c.text.trim().length >= 5)}>Save rationale</Button></div>
      </Card>
    </div>
  );
}
