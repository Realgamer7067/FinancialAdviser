"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { V4AngelStatus } from "@/lib/types";

// The Angel session ends every midnight IST. Without a fresh one the nightly holdings, funds and price steps cannot run, and everything after
// them quietly stays on the last day. This says so on the first page, with the exact command. It shows nothing when the session is fine, when
// Angel was never connected, or when the status could not be read (an unreadable status is not the same as a lapsed session).
export default function AngelSessionBanner() {
  const [status, setStatus] = useState<V4AngelStatus | null>(null);
  useEffect(() => {
    let live = true;
    api.get<V4AngelStatus>("/api/v4/connections/angel/status").then((s) => live && setStatus(s)).catch(() => {});
    return () => { live = false; };
  }, []);

  if (!status || status.session !== "reconnect_required") return null;
  const lastSync = status.accounts.map((a) => a.last_sync_at).filter((x): x is string => !!x).sort().pop();
  return (
    <section role="status" aria-label="Angel One session" className="rounded-md border border-warning bg-warning-subtle px-4 py-3 text-sm">
      <p className="font-medium text-warning">Angel One needs reconnecting</p>
      <p className="mt-1 text-text-muted">
        The session ended, so holdings, funds and prices are not updating{lastSync ? `; the last sync was ${new Date(lastSync).toLocaleString("en-IN")}` : ""}.
        What you see is the last day that did update. Turn your VPN on, then run this in your own terminal (the app never asks for your PIN or code):
      </p>
      {status.reconnect_instructions && <code className="mt-2 block overflow-x-auto rounded bg-bg border border-border px-2 py-1 text-xs">{status.reconnect_instructions.replace(/^Run in your own terminal:\s*/, "")}</code>}
      <p className="mt-2 text-xs text-text-muted">The session lasts until midnight India time, so this repeats daily. <Link className="text-accent underline" href="/holdings">Open connection details</Link></p>
    </section>
  );
}
