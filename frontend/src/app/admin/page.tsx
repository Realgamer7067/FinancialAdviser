"use client";

import { motion } from "framer-motion";
import { useApiData } from "@/lib/useApiData";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import StatCard from "@/components/ui/StatCard";
import Card from "@/components/ui/Card";
import { SkeletonCard } from "@/components/ui/Skeleton";

interface DebugOut {
  demo_mode: boolean;
  qwen_configured: boolean;
  finrl_checkpoint_trained: boolean;
  data_sources: { name: string; kind: string; status: string; last_synced_at: string | null; token_expires_at: string | null }[];
  recent_jobs: { id: string; status: string; error: string | null; created_at: string }[];
}

const STATUS_CLASS: Record<string, string> = {
  ok: "text-positive",
  degraded: "text-warning",
  error: "text-negative",
  unconfigured: "text-text-muted",
};

export default function AdminPage() {
  const { data: debug, error, loading } = useApiData<DebugOut>("/admin/debug");

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Admin / Debug</h1>
        <p className="text-sm text-text-muted">
          Developer-only view of provider status, model config, and recent job runs (Section 69). Not
          protected by auth in this MVP — do not expose publicly.
        </p>
      </motion.div>

      {error && <p className="text-sm text-negative">{error}</p>}
      {loading && !debug && !error && (
        <motion.div variants={fadeInUp} className="grid gap-4 sm:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </motion.div>
      )}
      {debug && (
        <>
          <motion.div variants={fadeInUp} className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Demo mode" value={String(debug.demo_mode)} />
            <StatCard label="Qwen configured" value={String(debug.qwen_configured)} />
            <StatCard label="FinRL checkpoint" value={debug.finrl_checkpoint_trained ? "trained (unvalidated)" : "not trained"} />
          </motion.div>

          <motion.div variants={fadeInUp}>
            <Card title="Data sources">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-text-muted">
                    <tr>
                      <th className="py-1">Name</th>
                      <th>Kind</th>
                      <th>Status</th>
                      <th>Last synced</th>
                    </tr>
                  </thead>
                  <tbody>
                    {debug.data_sources.map((s) => (
                      <tr key={s.name} className="border-t border-border">
                        <td className="py-1 text-text-primary">{s.name}</td>
                        <td className="text-text-muted">{s.kind}</td>
                        <td className={STATUS_CLASS[s.status] ?? "text-text-muted"}>{s.status}</td>
                        <td className="text-text-muted">{s.last_synced_at ?? "never"}</td>
                      </tr>
                    ))}
                    {debug.data_sources.length === 0 && (
                      <tr>
                        <td colSpan={4} className="py-2 text-text-muted">
                          No data sources synced yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          </motion.div>

          <motion.div variants={fadeInUp}>
            <Card title="Recent recommendation jobs">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-text-muted">
                    <tr>
                      <th className="py-1">Job</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {debug.recent_jobs.map((j) => (
                      <tr key={j.id} className="border-t border-border">
                        <td className="py-1 font-mono text-xs text-text-primary">{j.id.slice(0, 8)}</td>
                        <td className="text-text-muted">{j.status}</td>
                        <td className="text-text-muted">{new Date(j.created_at).toLocaleString()}</td>
                        <td className="text-negative">{j.error ?? ""}</td>
                      </tr>
                    ))}
                    {debug.recent_jobs.length === 0 && (
                      <tr>
                        <td colSpan={4} className="py-2 text-text-muted">
                          No jobs yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          </motion.div>
        </>
      )}
    </motion.div>
  );
}
