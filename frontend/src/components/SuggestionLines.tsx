"use client";

import Link from "next/link";
import type { V4SuggestionItem } from "@/lib/types";

// What changed for one security: descriptions of past prices, with the choices the owner has. "Keep things as they are" is always first.
export default function SuggestionLines({ item }: { item: V4SuggestionItem }) {
  if (item.observations.length === 0) {
    return item.note ? <p className="text-xs text-text-muted">{item.note}</p> : <p className="text-xs text-text-muted">Nothing unusual in its price history as of {item.signal_as_of ?? "n/a"}.</p>;
  }
  return (
    <ul className="space-y-2">
      {item.observations.map((o) => (
        <li key={o.kind} className={`rounded border p-2 ${o.attention === "look" ? "border-warning" : "border-border"}`}>
          <p className="text-sm text-text-primary">{o.attention === "look" && <span className="mr-1 text-xs font-medium text-warning">Worth a look:</span>}{o.title}</p>
          {o.attention === "look" && <p className="mt-0.5 text-xs text-text-muted">{o.detail}</p>}
          <details className="mt-1 text-xs text-text-muted">
            <summary className="cursor-pointer text-text-primary">{o.attention === "look" ? "What you can do" : "How this was worked out, and what you can do"}</summary>
            {o.attention !== "look" && <p className="mt-1">{o.detail}</p>}
            <ul className="mt-1 list-inside list-disc space-y-0.5">
              {o.options.map((opt) => <li key={opt.id}>{opt.href ? <Link href={opt.href} className="text-accent underline">{opt.text}</Link> : opt.text}</li>)}
            </ul>
          </details>
        </li>
      ))}
    </ul>
  );
}
