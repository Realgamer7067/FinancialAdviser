"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

interface DebugOut {
  demo_mode: boolean;
  upstox_configured: boolean;
  qwen_configured: boolean;
  data_sources: { name: string; kind: string; status: string; last_synced_at: string | null; token_expires_at: string | null }[];
  recent_jobs: { id: string; status: string; error: string | null; created_at: string }[];
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function AdminPage() {
  const [debug, setDebug] = useState<DebugOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<DebugOut>("/admin/debug")
      .then(setDebug)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load debug info"));
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Admin / Debug</h1>
      <p className="text-sm text-slate-500">
        Developer-only view of provider status, model config, and recent job runs (Section 69). Not
        protected by auth in this MVP -- do not expose publicly.
      </p>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {debug && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="Demo mode" value={String(debug.demo_mode)} />
            <Stat label="Upstox configured" value={String(debug.upstox_configured)} />
            <Stat label="Qwen configured" value={String(debug.qwen_configured)} />
          </div>

          <div className="rounded border bg-white p-4">
            <h2 className="mb-2 font-medium">Data sources</h2>
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-1">Name</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Last synced</th>
                </tr>
              </thead>
              <tbody>
                {debug.data_sources.map((s) => (
                  <tr key={s.name} className="border-t">
                    <td className="py-1">{s.name}</td>
                    <td>{s.kind}</td>
                    <td>{s.status}</td>
                    <td>{s.last_synced_at ?? "never"}</td>
                  </tr>
                ))}
                {debug.data_sources.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-2 text-slate-400">
                      No data sources synced yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="rounded border bg-white p-4">
            <h2 className="mb-2 font-medium">Recent recommendation jobs</h2>
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-1">Job</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {debug.recent_jobs.map((j) => (
                  <tr key={j.id} className="border-t">
                    <td className="py-1 font-mono text-xs">{j.id.slice(0, 8)}</td>
                    <td>{j.status}</td>
                    <td>{new Date(j.created_at).toLocaleString()}</td>
                    <td className="text-red-600">{j.error ?? ""}</td>
                  </tr>
                ))}
                {debug.recent_jobs.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-2 text-slate-400">
                      No jobs yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <a href={`${API_URL}/admin/upstox/login`} className="inline-block text-sm text-brand-700 underline">
            Re-authenticate Upstox (daily token expiry)
          </a>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}
