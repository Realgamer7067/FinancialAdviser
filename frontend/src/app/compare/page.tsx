"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, ApiError } from "@/lib/api";
import type { CouncilRunSummary, StockDetail } from "@/lib/types";
import { fadeInUp, staggerChildren } from "@/lib/motion";
import StockSummaryCard from "@/components/StockSummaryCard";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";

const SLOT_COUNT = 3;

function ComparePageInner() {
  const [candidates, setCandidates] = useState<string[]>([]);
  const [symbols, setSymbols] = useState<string[]>(Array(SLOT_COUNT).fill(""));
  const [manualInput, setManualInput] = useState<string[]>(Array(SLOT_COUNT).fill(""));
  const [stocks, setStocks] = useState<(StockDetail | null)[]>(Array(SLOT_COUNT).fill(null));
  const [errors, setErrors] = useState<(string | null)[]>(Array(SLOT_COUNT).fill(null));

  useEffect(() => {
    api
      .get<CouncilRunSummary>("/api/recommendations/latest")
      .then((res) => setCandidates(res.recommendations.map((r) => r.symbol)))
      .catch(() => setCandidates([]));
  }, []);

  useEffect(() => {
    symbols.forEach((symbol, i) => {
      if (!symbol) {
        setStocks((prev) => {
          const next = [...prev];
          next[i] = null;
          return next;
        });
        setErrors((prev) => {
          const next = [...prev];
          next[i] = null;
          return next;
        });
        return;
      }
      api
        .get<StockDetail>(`/api/stocks/${symbol}`)
        .then((res) => {
          setStocks((prev) => {
            const next = [...prev];
            next[i] = res;
            return next;
          });
          setErrors((prev) => {
            const next = [...prev];
            next[i] = null;
            return next;
          });
        })
        .catch((err) => {
          setStocks((prev) => {
            const next = [...prev];
            next[i] = null;
            return next;
          });
          setErrors((prev) => {
            const next = [...prev];
            next[i] = err instanceof ApiError ? err.message : "Failed to load";
            return next;
          });
        });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbols]);

  function setSlot(i: number, symbol: string) {
    setSymbols((prev) => {
      const next = [...prev];
      next[i] = symbol.toUpperCase();
      return next;
    });
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerChildren} className="space-y-6">
      <motion.div variants={fadeInUp}>
        <h1 className="text-xl font-semibold text-text-primary">Compare stocks</h1>
        <p className="text-sm text-text-muted">Pick up to {SLOT_COUNT} stocks to view side by side.</p>
      </motion.div>

      <motion.div variants={fadeInUp} className="grid gap-4 sm:grid-cols-3">
        {Array.from({ length: SLOT_COUNT }).map((_, i) => (
          <Card key={i} className="p-3">
            <label className="block text-xs font-medium text-text-muted">Slot {i + 1}</label>
            <select
              value={candidates.includes(symbols[i]) ? symbols[i] : ""}
              onChange={(e) => setSlot(i, e.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <option value="">-- pick from last analysis --</option>
              {candidates.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <div className="mt-2 flex gap-2">
              <input
                type="text"
                placeholder="or type a symbol"
                value={manualInput[i]}
                onChange={(e) => {
                  const v = e.target.value;
                  setManualInput((prev) => {
                    const next = [...prev];
                    next[i] = v;
                    return next;
                  });
                }}
                className="w-full rounded-md border border-border bg-surface px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setSlot(i, manualInput[i])}
                disabled={!manualInput[i]}
                className="shrink-0"
              >
                Go
              </Button>
            </div>
            {errors[i] && <p className="mt-1 text-xs text-negative">{errors[i]}</p>}
          </Card>
        ))}
      </motion.div>

      <motion.div variants={fadeInUp} className="grid gap-4 sm:grid-cols-3">
        {stocks.map((stock, i) => (stock ? <StockSummaryCard key={i} stock={stock} /> : <div key={i} />))}
      </motion.div>
    </motion.div>
  );
}

export default function ComparePage() {
  return <ComparePageInner />;
}
