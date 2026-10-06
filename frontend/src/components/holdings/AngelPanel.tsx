"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4AngelStatus, V4Job } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";

const SESSION_LABEL: Record<V4AngelStatus["session"], string> = {
  connected: "Connected",
  reconnect_required: "Reconnect required",
  not_connected: "Not connected",
};

export default function AngelPanel({ onSynced }: { onSynced: () => void }) {
  const [status, setStatus] = useState<V4AngelStatus | null>(null);
  const [jobs, setJobs] = useState<Record<string, V4Job>>({});
  const [error, setError] = useState<string | null>(null);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const load = useCallback(() => {
    api.get<V4AngelStatus>("/api/v4/connections/angel/status").then(setStatus).catch((e) =>
      setError(e instanceof ApiError ? e.message : "Failed to load Angel status")
    );
  }, []);

  useEffect(() => {
    load();
    const t = timers.current;
    return () => Object.values(t).forEach(clearTimeout);
  }, [load]);

  const poll = useCallback(
    (accountId: string, jobId: string) => {
      api
        .get<V4Job>(`/api/v4/jobs/${jobId}`)
        .then((job) => {
          setJobs((j) => ({ ...j, [accountId]: job }));
          if (job.status === "queued" || job.status === "running") {
            timers.current[accountId] = setTimeout(() => poll(accountId, jobId), 2000);
          } else {
            load();
            if (job.status === "done") onSynced();
          }
        })
        .catch((e) => setError(e instanceof ApiError ? e.message : "Lost track of the sync job"));
    },
    [load, onSynced]
  );

  async function sync(accountId: string) {
    setError(null);
    try {
      const job = await api.post<V4Job>(`/api/v4/accounts/${accountId}/sync`, { idempotency_key: crypto.randomUUID() });
      setJobs((j) => ({ ...j, [accountId]: job }));
      poll(accountId, job.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start sync");
    }
  }

  if (!status) return null;
  const busy = (id: string) => jobs[id]?.status === "queued" || jobs[id]?.status === "running";

  return (
    <Card title="Angel One (read-only)">
      <p className="text-sm text-text-muted">
        Status: <strong className="text-text-primary">{SESSION_LABEL[status.session]}</strong>
        {status.session_expires_at && ` · session ends ${new Date(status.session_expires_at).toLocaleString("en-IN")}`}
        {" · "}This app only reads holdings; it cannot place or change orders.
      </p>
      {(!status.api_key_configured || !status.fingerprint_key_configured) && (
        <p className="mt-2 text-sm text-warning" role="status">
          Set ANGEL_API_KEY and ANGEL_FINGERPRINT_KEY in .env, then restart the backend.
        </p>
      )}
      {status.reconnect_instructions && (
        <div className="mt-2 text-sm text-text-muted">
          <p>Sign in from your own terminal (your PIN and TOTP are typed there, never in this page):</p>
          <code tabIndex={0} className="mt-1 block overflow-x-auto rounded-md border border-border bg-bg px-3 py-2 text-xs">
            python -m app.portfolio_intelligence.sources.angel.setup connect
          </code>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-negative">{error}</p>}
      {status.accounts.map((a) => {
        const job = jobs[a.id];
        return (
          <div key={a.id} className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
            <div>
              <p className="text-sm font-medium text-text-primary">
                {a.label} <span className="text-text-muted">({a.masked_external_id ?? "masked"})</span>
              </p>
              <p className="text-xs text-text-muted">
                {a.last_sync_at ? `Last sync ${new Date(a.last_sync_at).toLocaleString("en-IN")}` : "Never synced"}
                {a.status === "reconnect_required" && " · reconnect required"}
              </p>
              {a.last_error && <p className="text-xs text-negative">{a.last_error}</p>}
              {job && (
                <p className="text-xs text-text-muted" aria-live="polite">
                  Sync {job.status}
                  {job.status === "failed" && job.error_code ? `: ${job.error_code}` : ""}
                  {job.status === "done" && job.result_import_status ? ` (${job.result_import_status})` : ""}
                </p>
              )}
            </div>
            <Button size="sm" variant="secondary" onClick={() => sync(a.id)} loading={busy(a.id)} disabled={status.session !== "connected"}>
              Sync now
            </Button>
          </div>
        );
      })}
    </Card>
  );
}
