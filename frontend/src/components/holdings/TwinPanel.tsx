"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { V4Twin } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

const DIM_LABEL: Record<string, string> = {
  account_coverage_status: "All accounts added",
  holdings_status: "Holdings imported",
  valuation_status: "Values known",
  identity_status: "Instruments matched",
  suitability_status: "Profile and goals",
};

function rupees(v: string | null): string {
  if (v === null) return "unknown";
  const n = Number(v);
  return Number.isNaN(n) ? "unknown" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function pct(v: string | null): string {
  return v === null ? "n/a" : `${(Number(v) * 100).toFixed(0)}%`;
}

export default function TwinPanel({ refreshKey }: { refreshKey: number }) {
  const [twin, setTwin] = useState<V4Twin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<V4Twin>("/api/v4/state/current").then(setTwin).catch((e) =>
      setError(e instanceof ApiError ? e.message : "Failed to load portfolio state")
    );
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/v4/state/refresh");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Refresh failed");
    } finally {
      setBusy(false);
    }
  }

  if (error && !twin) {
    return (
      <Card title="Portfolio snapshot">
        <p role="alert" className="text-sm text-negative">Could not load your holdings: {error}. This is a loading problem, not an empty portfolio.</p>
        <div className="mt-2"><Button size="sm" variant="secondary" onClick={() => { setError(null); load(); }}>Try again</Button></div>
      </Card>
    );
  }
  if (!twin) return <Card title="Portfolio snapshot"><p aria-busy="true" className="text-sm text-text-muted">Loading your holdings…</p></Card>;

  if (!twin.state) {
    return (
      <Card title="Portfolio snapshot">
        <p className="text-sm text-text-muted">
          Nothing to show yet. Add an account below and import holdings; a dated snapshot is built automatically.
        </p>
      </Card>
    );
  }

  const v = twin.valuation;
  const sel = new Map((v?.selections ?? []).map((s) => [s.position_id, s]));

  return (
    <Card title="Portfolio snapshot">
      {twin.is_stale && (
        <div role="status" className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-bg p-2 text-sm text-warning">
          Your accounts changed since this snapshot was built.
          <Button size="sm" variant="secondary" onClick={refresh} loading={busy}>Rebuild snapshot</Button>
        </div>
      )}
      {error && <p role="alert" className="mb-2 text-sm text-negative">{error}</p>}
      <p className="text-xs text-text-muted">{twin.headline_label}</p>
      <p className="text-2xl font-semibold tabular-nums text-text-primary">{v ? rupees(v.known_total) : "unknown"}</p>
      <p className="text-xs text-text-muted">
        {[
          v?.coverage.latest_as_of && `Values as of ${v.coverage.earliest_as_of === v.coverage.latest_as_of ? v.coverage.latest_as_of : `${v.coverage.earliest_as_of} to ${v.coverage.latest_as_of}`}`,
          v && `${v.unknown_value_count} without a value`,
          v && `${pct(v.coverage.identity_resolved_value_share)} of value matched to instruments`,
          v && `${pct(v.coverage.fresh_value_share)} fresh`,
        ].filter(Boolean).join(" · ")}
      </p>

      {twin.state.positions.length === 0 ? (
        <p className="mt-3 text-sm text-text-muted">No holdings in your accounts yet. Open an account below and import or add what you hold.</p>
      ) : (
        <div tabIndex={0} className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Holdings in the current snapshot</caption>
            <thead>
              <tr className="border-b border-border text-left text-xs text-text-muted">
                <th scope="col" className="py-1.5 pr-4 font-medium">Holding</th>
                <th scope="col" className="py-1.5 pr-4 font-medium">Account</th>
                <th scope="col" className="py-1.5 pr-4 text-right font-medium">Units</th>
                <th scope="col" className="py-1.5 pr-4 text-right font-medium">Value</th>
                <th scope="col" className="py-1.5 font-medium">Freshness</th>
              </tr>
            </thead>
            <tbody>
              {twin.state.positions.map((p) => {
                const s = sel.get(p.position_id);
                return (
                  <tr key={p.position_id} className="border-b border-border last:border-0">
                    <td className="py-1.5 pr-4 font-medium text-text-primary">
                      {p.security_id ? <Link href={`/market/${p.security_id}`} className="hover:text-accent hover:underline">{p.display_name ?? p.raw_identifier ?? "unknown"}</Link> : (p.display_name ?? p.raw_identifier ?? "unknown")}
                      {p.identity === "catalogue"
                        ? <span className="ml-2 text-xs text-text-muted">recognised in the market list</span>
                        : (p.resolution === "unresolved" || p.resolution === "ambiguous") && <span className="ml-2 text-xs text-warning">unmatched</span>}
                    </td>
                    <td className="py-1.5 pr-4 text-text-muted">{p.account_label}</td>
                    <td className="py-1.5 pr-4 text-right tabular-nums text-text-muted">{p.units ? Number(p.units) : "-"}</td>
                    <td className="py-1.5 pr-4 text-right tabular-nums text-text-muted">{rupees(s?.value ?? null)}</td>
                    <td className="py-1.5 text-text-muted">{s ? `${s.quality} (${s.as_of})` : "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(() => {
        const entries = Object.entries(twin.readiness);
        const open = entries.filter(([, r]) => r.status !== "complete");
        return (
          <details className="mt-3 rounded-md border border-border bg-bg p-2 text-xs">
            <summary className="cursor-pointer text-text-muted">
              {open.length === 0 ? "Data readiness: everything is in place" : `Data readiness: ${open.length} of ${entries.length} need attention (${open.map(([d]) => DIM_LABEL[d] ?? d).join(", ")})`}
            </summary>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-5" aria-label="Data readiness">
              {entries.map(([dim, r]) => (
                <li key={dim} className="rounded-md border border-border bg-surface p-2">
                  <p className="font-medium text-text-primary">{DIM_LABEL[dim] ?? dim}</p>
                  <p className={r.status === "complete" ? "text-positive" : r.status === "partial" ? "text-warning" : "text-negative"}>
                    {r.status === "complete" ? "Complete" : r.status === "partial" ? "Partial" : "Not available"}
                  </p>
                  {r.missing.length > 0 && <p className="text-text-muted">{r.missing.join("; ")}</p>}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-text-muted">Snapshot v{twin.state.version}, built {new Date(twin.state.created_at).toLocaleString("en-IN")}.</p>
          </details>
        );
      })()}
    </Card>
  );
}
