"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, PlusCircle, Wallet } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  HoldingRowIn,
  HoldingsPreviewResponse,
  HoldingsSnapshotOut,
} from "@/lib/types";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonCard } from "@/components/ui/Skeleton";

function formatRupees(v: string | number | null): string {
  if (v === null) return "-";
  const n = typeof v === "string" ? Number(v) : v;
  if (Number.isNaN(n)) return "-";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

const EMPTY_FORM = {
  raw_identifier_text: "",
  amount: "",
  valuation_date: new Date().toISOString().slice(0, 10),
  valuation_source: "manual_entry",
  units: "",
};

function HoldingsInner() {
  const [snapshot, setSnapshot] = useState<HoldingsSnapshotOut | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(true);

  const [form, setForm] = useState(EMPTY_FORM);
  const [pendingRows, setPendingRows] = useState<HoldingRowIn[]>([]);
  const [preview, setPreview] = useState<HoldingsPreviewResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

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

  function addRow() {
    setFormError(null);
    if (!form.amount || Number(form.amount) < 0) {
      setFormError("Enter a valid, non-negative amount.");
      return;
    }
    if (!form.valuation_date) {
      setFormError("Valuation date is required.");
      return;
    }
    if (!form.valuation_source.trim()) {
      setFormError("Valuation source is required.");
      return;
    }
    const row: HoldingRowIn = {
      raw_identifier_text: form.raw_identifier_text.trim() || null,
      instrument_id: null, // manual entry -- no instrument lookup in this UI, will surface as unresolved
      account_label: null,
      units: form.units.trim() || null,
      amount: form.amount,
      valuation_date: form.valuation_date,
      valuation_source: form.valuation_source.trim(),
      cost_basis: null,
      locked: false,
      lock_reason: null,
      ownership: "sole",
      include_in_planning: true,
    };
    setPendingRows((rows) => [...rows, row]);
    setForm({ ...EMPTY_FORM, valuation_date: form.valuation_date });
    setPreview(null);
  }

  function removeRow(idx: number) {
    setPendingRows((rows) => rows.filter((_, i) => i !== idx));
    setPreview(null);
  }

  async function runPreview() {
    setBusy(true);
    setFormError(null);
    try {
      const res = await api.post<HoldingsPreviewResponse>("/api/holdings/import/preview", { rows: pendingRows });
      setPreview(res);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  async function confirmImport() {
    setBusy(true);
    setFormError(null);
    try {
      await api.post<HoldingsSnapshotOut>("/api/holdings/import/confirm", {
        rows: pendingRows,
        idempotency_key: crypto.randomUUID(),
        source: "manual",
      });
      setPendingRows([]);
      setPreview(null);
      loadSnapshot();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Holdings</h1>
        <p className="text-sm text-text-muted">
          Manually record what you currently hold. Each confirmed batch creates a new, immutable snapshot --
          nothing here executes a trade.
        </p>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="Current snapshot">
          {loadingSnapshot ? (
            <SkeletonCard />
          ) : snapshotError ? (
            <p className="text-sm text-negative">{snapshotError}</p>
          ) : !snapshot ? (
            <EmptyState icon={Wallet} title="No holdings snapshot yet" message="Add rows below and confirm an import to create your first snapshot." />
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-text-muted">
                Snapshot from {new Date(snapshot.created_at).toLocaleString("en-IN")} · source: {snapshot.source}
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-text-muted">
                      <th className="py-1 pr-4">Identifier</th>
                      <th className="py-1 pr-4">Amount</th>
                      <th className="py-1 pr-4">Units</th>
                      <th className="py-1 pr-4">Valuation date</th>
                      <th className="py-1">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.positions.map((p) => (
                      <tr key={p.id} className="border-b border-border last:border-0">
                        <td className="py-1 pr-4 font-medium text-text-primary">
                          {p.raw_identifier_text ?? (p.instrument_id ? p.instrument_id.slice(0, 8) : "unknown")}
                        </td>
                        <td className="py-1 pr-4 text-text-muted">{formatRupees(p.amount)}</td>
                        <td className="py-1 pr-4 text-text-muted">{p.units ?? "-"}</td>
                        <td className="py-1 pr-4 text-text-muted">{p.valuation_date}</td>
                        <td className="py-1 text-text-muted">{p.identification_confidence}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="Add a holding">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <label className="text-sm text-text-primary">
              Symbol / identifier
              <input
                type="text"
                value={form.raw_identifier_text}
                onChange={(e) => setForm({ ...form, raw_identifier_text: e.target.value })}
                placeholder="e.g. RELIANCE"
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
            <label className="text-sm text-text-primary">
              Amount (₹)
              <input
                type="number"
                min={0}
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
            <label className="text-sm text-text-primary">
              Units (optional)
              <input
                type="number"
                min={0}
                value={form.units}
                onChange={(e) => setForm({ ...form, units: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
            <label className="text-sm text-text-primary">
              Valuation date
              <input
                type="date"
                value={form.valuation_date}
                onChange={(e) => setForm({ ...form, valuation_date: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
            <label className="text-sm text-text-primary">
              Valuation source
              <input
                type="text"
                value={form.valuation_source}
                onChange={(e) => setForm({ ...form, valuation_source: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
          </div>
          <div className="mt-3">
            <Button variant="secondary" size="sm" onClick={addRow}>
              <PlusCircle className="h-4 w-4" /> Add row to batch
            </Button>
          </div>
          {formError && <p className="mt-2 text-sm text-negative">{formError}</p>}

          {pendingRows.length > 0 && (
            <div className="mt-4 space-y-3">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-text-muted">
                      <th className="py-1 pr-4">Identifier</th>
                      <th className="py-1 pr-4">Amount</th>
                      <th className="py-1 pr-4">Valuation date</th>
                      <th className="py-1"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {pendingRows.map((r, idx) => (
                      <tr key={idx} className="border-b border-border last:border-0">
                        <td className="py-1 pr-4 text-text-primary">{r.raw_identifier_text ?? "unknown"}</td>
                        <td className="py-1 pr-4 text-text-muted">{formatRupees(r.amount)}</td>
                        <td className="py-1 pr-4 text-text-muted">{r.valuation_date}</td>
                        <td className="py-1">
                          <button onClick={() => removeRow(idx)} className="text-xs text-negative hover:underline">
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex gap-2">
                <Button size="sm" onClick={runPreview} loading={busy}>
                  Preview import
                </Button>
                {preview && (
                  <Button size="sm" variant="secondary" onClick={confirmImport} loading={busy}>
                    Confirm import
                  </Button>
                )}
              </div>

              {preview && (
                <div className="space-y-2 rounded-md border border-border bg-bg p-3 text-sm">
                  {preview.duplicate_candidates.length === 0 && preview.unresolved_identifiers.length === 0 ? (
                    <p className="text-text-muted">No duplicates or unresolved identifiers found.</p>
                  ) : (
                    <>
                      {preview.duplicate_candidates.length > 0 && (
                        <div className="flex items-start gap-2 text-warning">
                          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                          <div>
                            <p className="font-medium">Possible duplicates</p>
                            <ul className="list-inside list-disc text-text-muted">
                              {preview.duplicate_candidates.map((d) => (
                                <li key={d.row_index}>
                                  Row {d.row_index + 1} ({d.raw_identifier_text ?? "unknown"}) --{" "}
                                  {d.reason === "duplicate_within_batch" ? "duplicate within this batch" : "matches an existing snapshot"}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      )}
                      {preview.unresolved_identifiers.length > 0 && (
                        <div className="flex items-start gap-2 text-negative">
                          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                          <div>
                            <p className="font-medium">Unresolved identifiers</p>
                            <p className="text-text-muted">
                              These rows could not be matched to a known instrument and will be stored as
                              low-confidence / unresolved text.
                            </p>
                            <ul className="list-inside list-disc text-text-muted">
                              {preview.unresolved_identifiers.map((u) => (
                                <li key={u.row_index}>
                                  Row {u.row_index + 1}: {u.raw_identifier_text ?? "unknown"}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </Card>
      </motion.div>
    </motion.div>
  );
}

export default function HoldingsPage() {
  return <HoldingsInner />;
}
