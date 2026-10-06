"use client";

import { useState } from "react";
import Button from "@/components/ui/Button";

// Two-step action for changes that are awkward to reverse. The first press says what will happen; only the second
// press does it. No native confirm() dialog: it blocks the page and cannot be styled or read in context.
export default function ConfirmButton({ label, consequence, onConfirm, confirmLabel = "Yes, do it" }: {
  label: string;
  consequence: string;
  onConfirm: () => unknown;
  confirmLabel?: string;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) return <Button size="sm" variant="secondary" onClick={() => setAsking(true)}>{label}</Button>;
  return (
    <span role="group" aria-label={`Confirm: ${label}`} className="inline-flex flex-wrap items-center gap-2 rounded-md border border-warning bg-warning-subtle px-2 py-1 text-xs text-warning">
      <span>{consequence}</span>
      <Button size="sm" onClick={async () => { setAsking(false); await onConfirm(); }}>{confirmLabel}</Button>
      <Button size="sm" variant="secondary" onClick={() => setAsking(false)}>Cancel</Button>
    </span>
  );
}
