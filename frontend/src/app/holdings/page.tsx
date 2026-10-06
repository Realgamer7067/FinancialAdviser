"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, ApiError } from "@/lib/api";
import type { HoldingsSnapshotOut } from "@/lib/types";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import AccountsPanel from "@/components/holdings/AccountsPanel";
import TwinPanel from "@/components/holdings/TwinPanel";
import SuggestionsPanel from "@/components/holdings/SuggestionsPanel";

function formatRupees(v: string | number | null): string {
  if (v === null) return "-";
  const n = typeof v === "string" ? Number(v) : v;
  if (Number.isNaN(n)) return "-";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function HoldingsInner() {
  const [twinKey, setTwinKey] = useState(0);
  const bumpTwin = useCallback(() => setTwinKey((k) => k + 1), []);
  const [snapshot, setSnapshot] = useState<HoldingsSnapshotOut | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(true);

  const loadSnapshot = useCallback(() => {
    setLoadingSnapshot(true);
    api
      .get<HoldingsSnapshotOut>("/api/holdings/latest")
      .then((s) => {
        setSnapshot(s);
        setSnapshotError(null);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setSnapshot(null);
          setSnapshotError(null);
        } else {
          setSnapshotError(err instanceof ApiError ? err.message : "Failed to load holdings");
        }
      })
      .finally(() => setLoadingSnapshot(false));
  }, []);

  useEffect(() => {
    loadSnapshot();
  }, [loadSnapshot]);

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Holdings</h1>
        <p className="text-sm text-text-muted">
          What you hold, across every account. Update an account to change it. This app only reads; nothing here places an order.
        </p>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <TwinPanel refreshKey={twinKey} />
      </motion.div>

      <motion.div variants={fadeInUp}>
        <SuggestionsPanel />
      </motion.div>

      <motion.div variants={fadeInUp}>
        <AccountsPanel onChanged={bumpTwin} />
      </motion.div>

      {/* The first version's snapshot is shown for history only. New holdings go through an account above;
          the old entry form was removed so a successful save can no longer land in the wrong system. */}
      {!loadingSnapshot && snapshotError && (
        <motion.p variants={fadeInUp} role="alert" className="text-sm text-negative">
          The earlier snapshot could not be loaded: {snapshotError}
        </motion.p>
      )}
      {snapshot && (
        <motion.details variants={fadeInUp} className="rounded-lg border border-border bg-surface p-4 shadow-sm">
          <summary className="cursor-pointer text-sm font-medium text-text-primary">
            Earlier snapshot (history only) · {new Date(snapshot.created_at).toLocaleDateString("en-IN")} · {snapshot.positions.length} rows
          </summary>
          <p className="mt-2 text-xs text-text-muted">
            From the first version of this app, source: {snapshot.source}. It does not feed your current holdings or reviews.
          </p>
          <div tabIndex={0} className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Earlier holdings snapshot</caption>
              <thead>
                <tr className="border-b border-border text-left text-text-muted">
                  <th scope="col" className="py-1 pr-4">Identifier</th>
                  <th scope="col" className="py-1 pr-4 text-right">Amount</th>
                  <th scope="col" className="py-1 pr-4 text-right">Units</th>
                  <th scope="col" className="py-1 pr-4">Valuation date</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.positions.map((p) => (
                  <tr key={p.id} className="border-b border-border last:border-0">
                    <td className="py-1 pr-4 font-medium text-text-primary">{p.raw_identifier_text ?? (p.instrument_id ? p.instrument_id.slice(0, 8) : "unknown")}</td>
                    <td className="py-1 pr-4 text-right tabular-nums text-text-muted">{formatRupees(p.amount)}</td>
                    <td className="py-1 pr-4 text-right tabular-nums text-text-muted">{p.units ?? "-"}</td>
                    <td className="py-1 pr-4 text-text-muted">{p.valuation_date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.details>
      )}
    </motion.div>
  );
}

export default function HoldingsPage() {
  return <HoldingsInner />;
}
