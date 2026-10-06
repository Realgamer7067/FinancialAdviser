"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { JobStatus } from "@/lib/types";

const POLL_INTERVAL_MS = 3000;
const MAX_BACKOFF_MS = 30000;
// Single-user app (Section per CLAUDE.md) -- one fixed key is enough to
// remember "is there a job in flight" across a page refresh. Without this,
// refreshing mid-run showed a fresh "Run analysis" button with no memory
// that a job was still running server-side, inviting a duplicate trigger
// (docs/V2-RETHINK.md P1).
const ACTIVE_JOB_STORAGE_KEY = "ex2_active_job_id";

function readStoredJobId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
  } catch {
    return null; // private browsing / storage disabled -- degrade to "no memory", not a crash
  }
}

function writeStoredJobId(id: string | null) {
  try {
    if (id) localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, id);
    else localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
  } catch {
    // ignore -- best-effort persistence only
  }
}

// Polls a recommendation job until it reaches a terminal state.
//
// Two fixes over the original version (docs/V2-RETHINK.md P1):
// 1. Resumes an in-flight job after a page refresh by remembering its id in
//    localStorage, instead of always starting from "no job" and losing track
//    of a run that's still going server-side.
// 2. A failed poll (transient network blip) no longer silently stops the
//    loop forever -- it retries with capped exponential backoff and exposes
//    a `pollError` the caller can show as "reconnecting...".
export function useJobPolling(initialJob: JobStatus | null, onDone?: () => void) {
  const [job, setJobState] = useState<JobStatus | null>(initialJob);
  const [pollError, setPollError] = useState<string | null>(null);
  const failureCountRef = useRef(0);
  const resumedRef = useRef(false);

  function setJob(next: JobStatus | null) {
    setJobState(next);
    if (next && next.status !== "done" && next.status !== "failed") {
      writeStoredJobId(next.id);
    } else {
      writeStoredJobId(null);
    }
  }

  useEffect(() => {
    setJobState(initialJob);
    if (initialJob) writeStoredJobId(initialJob.status === "done" || initialJob.status === "failed" ? null : initialJob.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialJob]);

  // On first mount only, if nothing was explicitly passed in, try to resume
  // a job id left over from before a refresh.
  useEffect(() => {
    if (resumedRef.current) return;
    resumedRef.current = true;
    if (initialJob) return;
    const storedId = readStoredJobId();
    if (!storedId) return;
    (async () => {
      try {
        const resumed = await api.get<JobStatus>(`/api/recommendations/jobs/${storedId}`);
        setJob(resumed);
      } catch {
        writeStoredJobId(null); // job id is gone/invalid server-side -- stop remembering it
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keyed on job.id (not the whole job object) and self-reschedules on every
  // tick -- including failed ones -- so a transient error can't silently
  // stall the loop (setting state to a referentially-equal object wouldn't
  // re-trigger an effect keyed on `job`, which is why this isn't `[job]`).
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    const jobId = job.id;
    // Reset backoff state whenever the tracked job id changes (e.g. a new
    // job started while a previous one was mid-backoff after failures) --
    // otherwise a fresh job inherits a stale failure count and starts its
    // first poll delayed as if it had already failed repeatedly.
    failureCountRef.current = 0;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      const delay = Math.min(POLL_INTERVAL_MS * 2 ** failureCountRef.current, MAX_BACKOFF_MS);
      timer = setTimeout(async () => {
        if (cancelled) return;
        try {
          const updated = await api.get<JobStatus>(`/api/recommendations/jobs/${jobId}`);
          if (cancelled) return;
          failureCountRef.current = 0;
          setPollError(null);
          setJob(updated);
          if (updated.status === "done") onDone?.();
          if (updated.status !== "done" && updated.status !== "failed") tick();
        } catch {
          if (cancelled) return;
          failureCountRef.current += 1;
          setPollError("Lost contact with the job status endpoint -- retrying...");
          tick();
        }
      }, delay);
    }
    tick();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id]);

  return { job, setJob, pollError };
}
