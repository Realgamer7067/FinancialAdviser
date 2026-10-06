"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { V4CurrentDecision } from "@/lib/types";

/** Loads the current decision and can request a review; polls while one is pending. */
export function useDecision() {
  const [decision, setDecision] = useState<V4CurrentDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.get<V4CurrentDecision>("/api/v4/actions/current");
      setDecision(d);
      setError(null);
      return d;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load the review");
      return null;
    }
  }, []);

  const poll = useCallback(
    (tries: number) => {
      load().then((d) => {
        if (d && d.pending_review && tries > 0) timer.current = setTimeout(() => poll(tries - 1), 2000);
        else setBusy(false);
      });
    },
    [load]
  );

  useEffect(() => {
    poll(10);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [poll]);

  async function requestReview(force = false) {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/v4/reviews", { force });
      poll(15);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start a review");
      setBusy(false);
    }
  }

  return { decision, error, busy, requestReview, reload: load };
}
