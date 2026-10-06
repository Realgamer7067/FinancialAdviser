import type { V4Outcome } from "@/lib/types";

const LOOK: Record<V4Outcome["status"], { label: string; tone: string }> = {
  HOLD: { label: "HOLD", tone: "border-positive text-positive" },
  REVIEW: { label: "REVIEW", tone: "border-warning text-warning" },
  NEEDS_INPUT: { label: "NEEDS INFORMATION", tone: "border-border text-text-primary" },
};

export default function DecisionBadge({ status }: { status: V4Outcome["status"] }) {
  const l = LOOK[status];
  return <span className={`inline-block rounded-md border px-2 py-0.5 text-xs font-semibold tracking-wide ${l.tone}`}>{l.label}</span>;
}
