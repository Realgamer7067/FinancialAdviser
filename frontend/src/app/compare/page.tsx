"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { CouncilRunSummary, StockDetail } from "@/lib/types";
import StockSummaryCard from "@/components/StockSummaryCard";
import Button from "@/components/ui/Button";

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
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Compare stocks</h1>
      <p className="text-sm text-slate-500">Pick up to {SLOT_COUNT} stocks to view side by side.</p>

      <div className="grid gap-4 sm:grid-cols-3">
        {Array.from({ length: SLOT_COUNT }).map((_, i) => (
          <div key={i} className="rounded border bg-white p-3">
            <label className="block text-xs font-medium text-slate-500">Slot {i + 1}</label>
            <select
              value={candidates.includes(symbols[i]) ? symbols[i] : ""}
              onChange={(e) => setSlot(i, e.target.value)}
              className="mt-1 w-full rounded border px-2 py-1 text-sm"
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
                className="w-full rounded border px-2 py-1 text-sm"
              />
              <Button
                variant="secondary"
                onClick={() => setSlot(i, manualInput[i])}
                disabled={!manualInput[i]}
                className="shrink-0"
              >
                Go
              </Button>
            </div>
            {errors[i] && <p className="mt-1 text-xs text-red-600">{errors[i]}</p>}
          </div>
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {stocks.map((stock, i) =>
          stock ? <StockSummaryCard key={i} stock={stock} /> : <div key={i} />
        )}
      </div>
    </div>
  );
}

export default function ComparePage() {
  return <ComparePageInner />;
}
