"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

// Extracts the useState+useEffect+api.get triplet duplicated across nearly
// every page before this (Phase 1 cleanup). Still plain fetch under the hood
// via lib/api.ts -- no caching/revalidation semantics, that's a data-fetching
// library's job and one wasn't approved for this redesign.
export function useApiData<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);

  const load = useCallback(() => {
    if (path === null) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .get<T>(path)
      .then((d) => setData(d))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load data"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  useEffect(() => {
    load();
  }, [load]);

  return { data, error, loading, reload: load };
}
