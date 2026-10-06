"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { PlusCircle, Target } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { GoalOut, HoldingPositionOut, HoldingsSnapshotOut } from "@/lib/types";
import { useApiData } from "@/lib/useApiData";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import ProgressBar from "@/components/ui/ProgressBar";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonCard } from "@/components/ui/Skeleton";

function formatRupees(v: string | number | null): string {
  if (v === null) return "-";
  const n = typeof v === "string" ? Number(v) : v;
  if (Number.isNaN(n)) return "-";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

const EMPTY_FORM = {
  description: "",
  target_amount: "",
  target_basis: "today_money",
  target_date: "",
  priority: "1",
  flexibility: "flexible",
};

function GoalsInner() {
  const { data: goals, error, reload } = useApiData<GoalOut[]>("/api/goals");
  const [positions, setPositions] = useState<HoldingPositionOut[]>([]);

  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [earmarkGoalId, setEarmarkGoalId] = useState<string | null>(null);
  const [earmarkPositionId, setEarmarkPositionId] = useState("");
  const [earmarkAmount, setEarmarkAmount] = useState("");
  const [earmarkError, setEarmarkError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<HoldingsSnapshotOut>("/api/holdings/latest")
      .then((s) => setPositions(s.positions))
      .catch(() => setPositions([])); // 404 (no snapshot yet) -- earmarking is simply unavailable until one exists
  }, []);

  async function createGoal() {
    setFormError(null);
    if (!form.description.trim()) return setFormError("Description is required.");
    if (!form.target_amount || Number(form.target_amount) <= 0) return setFormError("Target amount must be positive.");
    if (!form.target_date) return setFormError("Target date is required.");
    setBusy(true);
    try {
      await api.post("/api/goals", {
        description: form.description.trim(),
        target_amount: form.target_amount,
        target_basis: form.target_basis,
        target_date: form.target_date,
        priority: Number(form.priority),
        flexibility: form.flexibility,
      });
      setForm(EMPTY_FORM);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to create goal");
    } finally {
      setBusy(false);
    }
  }

  async function submitEarmark(goalId: string) {
    setEarmarkError(null);
    if (!earmarkPositionId) return setEarmarkError("Choose a holding.");
    if (!earmarkAmount || Number(earmarkAmount) <= 0) return setEarmarkError("Amount must be positive.");
    setBusy(true);
    try {
      await api.post(`/api/goals/${goalId}/earmarks`, {
        holding_position_id: earmarkPositionId,
        amount: earmarkAmount,
      });
      setEarmarkGoalId(null);
      setEarmarkPositionId("");
      setEarmarkAmount("");
      reload();
    } catch (err) {
      setEarmarkError(err instanceof ApiError ? err.message : "Failed to add earmark");
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Goals</h1>
        <p className="text-sm text-text-muted">
          Track what you&apos;re saving toward and earmark specific holdings against a goal.
        </p>
      </motion.div>

      <motion.div variants={fadeInUp}>
        <Card title="New goal">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <label className="text-sm text-text-primary lg:col-span-2">
              Description
              <input
                type="text"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="e.g. Down payment"
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
            <label className="text-sm text-text-primary">
              Target amount (₹)
              <input
                type="number"
                min={0}
                value={form.target_amount}
                onChange={(e) => setForm({ ...form, target_amount: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
            <label className="text-sm text-text-primary">
              Target date
              <input
                type="date"
                value={form.target_date}
                onChange={(e) => setForm({ ...form, target_date: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
            <label className="text-sm text-text-primary">
              Basis
              <select
                value={form.target_basis}
                onChange={(e) => setForm({ ...form, target_basis: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <option value="today_money">Today&apos;s money</option>
                <option value="future_money">Future money</option>
              </select>
            </label>
            <label className="text-sm text-text-primary">
              Priority
              <input
                type="number"
                min={1}
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
            <label className="text-sm text-text-primary">
              Flexibility
              <select
                value={form.flexibility}
                onChange={(e) => setForm({ ...form, flexibility: e.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <option value="fixed">Fixed</option>
                <option value="flexible">Flexible</option>
              </select>
            </label>
          </div>
          <div className="mt-3">
            <Button size="sm" onClick={createGoal} loading={busy}>
              <PlusCircle className="h-4 w-4" /> Create goal
            </Button>
          </div>
          {formError && <p className="mt-2 text-sm text-negative">{formError}</p>}
        </Card>
      </motion.div>

      {error && <p className="text-sm text-negative">{error}</p>}

      {!goals && !error && (
        <div className="grid gap-4 sm:grid-cols-2">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {goals && goals.length === 0 && (
        <motion.div variants={fadeInUp}>
          <EmptyState icon={Target} title="No goals yet" message="Create your first goal above." />
        </motion.div>
      )}

      {goals && goals.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {goals.map((g) => {
            const target = Number(g.target_amount);
            const earmarked = Number(g.earmarked_total);
            const pct = target > 0 ? Math.min(100, (earmarked / target) * 100) : 0;
            return (
              <motion.div key={g.id} variants={fadeInUp}>
                <Card title={g.description}>
                  <dl className="space-y-1 text-sm">
                    <div className="flex justify-between">
                      <dt className="text-text-muted">Target</dt>
                      <dd className="text-text-primary">
                        {formatRupees(g.target_amount)} by {g.target_date}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-text-muted">Priority</dt>
                      <dd className="text-text-primary">
                        {g.priority} · {g.flexibility}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-text-muted">Basis</dt>
                      <dd className="text-text-primary">{g.target_basis === "today_money" ? "Today's money" : "Future money"}</dd>
                    </div>
                  </dl>

                  <div className="mt-3">
                    <ProgressBar
                      label="Earmarked"
                      value={pct}
                      displayValue={`${formatRupees(g.earmarked_total)} / ${formatRupees(g.target_amount)}`}
                    />
                    <p className="mt-1 text-xs text-text-muted">
                      Remaining unearmarked: {formatRupees(g.remaining_unearmarked_target)}
                    </p>
                  </div>

                  <div className="mt-3 border-t border-border pt-3">
                    {earmarkGoalId !== g.id ? (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setEarmarkGoalId(g.id);
                          setEarmarkError(null);
                        }}
                        disabled={positions.length === 0}
                      >
                        Earmark a holding
                      </Button>
                    ) : (
                      <div className="space-y-2">
                        <select
                          value={earmarkPositionId}
                          onChange={(e) => setEarmarkPositionId(e.target.value)}
                          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        >
                          <option value="">Choose a holding…</option>
                          {positions.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.raw_identifier_text ?? p.id.slice(0, 8)} ({formatRupees(p.amount)})
                            </option>
                          ))}
                        </select>
                        <input
                          type="number"
                          min={0}
                          placeholder="Amount to earmark (₹)"
                          value={earmarkAmount}
                          onChange={(e) => setEarmarkAmount(e.target.value)}
                          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        />
                        {earmarkError && <p className="text-sm text-negative">{earmarkError}</p>}
                        <div className="flex gap-2">
                          <Button size="sm" onClick={() => submitEarmark(g.id)} loading={busy}>
                            Save
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setEarmarkGoalId(null)}>
                            Cancel
                          </Button>
                        </div>
                      </div>
                    )}
                    {positions.length === 0 && earmarkGoalId !== g.id && (
                      <p className="mt-1 text-xs text-text-muted">Add a holding first to earmark it against a goal.</p>
                    )}
                  </div>
                </Card>
              </motion.div>
            );
          })}
        </div>
      )}
    </motion.div>
  );
}

export default function GoalsPage() {
  return <GoalsInner />;
}
