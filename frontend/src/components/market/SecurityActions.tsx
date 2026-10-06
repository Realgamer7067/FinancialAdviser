"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { V4Security } from "@/lib/types";
import Button from "@/components/ui/Button";

type List = { id: string; name: string };

// What you can do about one security, with the chosen security carried into each tool. A tool that cannot take this security
// says why, instead of silently opening empty.
export default function SecurityActions({ s }: { s: V4Security }) {
  const [lists, setLists] = useState<List[]>([]);
  const [target, setTarget] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<{ lists: List[] }>("/api/v4/watchlists").then((r) => {
      setLists(r.lists);
      let saved = "";
      try { saved = localStorage.getItem("market.watchlist") ?? ""; } catch { /* private mode */ }
      setTarget(r.lists.some((l) => l.id === saved) ? saved : (r.lists[0]?.id ?? ""));
    }).catch(() => setLists([]));
  }, []);

  async function watch() {
    setBusy(true); setMsg(null);
    try {
      let list = lists.find((l) => l.id === target) ?? lists[0];
      if (!list) {
        list = await api.post<List>("/api/v4/watchlists", { name: "My watchlist" });
        setLists([list]); setTarget(list.id);
      }
      await api.post(`/api/v4/watchlists/${list.id}/items`, { broker_instrument_id: s.broker_instrument_id });
      setMsg({ ok: true, text: `${s.symbol} added to “${list.name}”.` });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? e.message : "Could not add to the watchlist" });
    } finally { setBusy(false); }
  }

  const canWatch = s.kind !== "mutual_fund" && !!s.broker_instrument_id;
  const company = s.name;
  return (
    <section aria-label="What you can do" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {canWatch && (
          <>
            {lists.length > 1 && (
              <label className="flex items-center gap-1 text-xs text-text-muted">Add to
                <select className="rounded-md border border-border bg-surface px-2 py-1 text-xs" value={target} onChange={(e) => { setTarget(e.target.value); try { localStorage.setItem("market.watchlist", e.target.value); } catch { /* ignore */ } }}>
                  {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </label>
            )}
            <Button size="sm" onClick={watch} loading={busy}>Watch</Button>
          </>
        )}
        {s.kind === "stock" && <Link href={`/research?company=${encodeURIComponent(company)}`}><Button size="sm" variant="secondary">Research this company</Button></Link>}
        {s.instrument_id && <Link href={`/theses?instrument=${s.instrument_id}`}><Button size="sm" variant="secondary">Write a rationale</Button></Link>}
        {s.instrument_id && <Link href={`/simulate?buy=${s.instrument_id}`}><Button size="sm" variant="secondary">Compare adding some with doing nothing</Button></Link>}
      </div>
      {!canWatch && <p className="text-xs text-text-muted">{s.kind === "mutual_fund" ? "Funds are not on the watchlist (it follows traded prices). Their NAV is shown above." : "Not found in Angel One's equity list, so it cannot be watched."}</p>}
      {s.kind !== "mutual_fund" && !s.instrument_id && <p className="text-xs text-text-muted">Rationales and comparing a purchase currently work for Nifty 50 stocks only, and this one is not on that list.</p>}
      {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "text-positive" : "text-negative"}`}>{msg.text} {msg.ok && <Link href="/watchlist" className="underline">Open watchlists</Link>}</p>}
    </section>
  );
}
