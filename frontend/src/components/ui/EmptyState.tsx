import { LucideIcon } from "lucide-react";
import Link from "next/link";

// Centralizes the "no data yet" pattern duplicated ad hoc across pages
// before this (Phase 1). Also used for genuinely-designed empty states like
// CouncilTranscript's "no LLM configured" case -- not just "nothing here".
export default function EmptyState({
  icon: Icon,
  title,
  message,
  action,
}: {
  icon: LucideIcon;
  title: string;
  message?: string;
  action?: { href: string; label: string };
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-surface/50 px-6 py-10 text-center">
      <Icon className="h-8 w-8 text-text-muted" />
      <p className="font-medium text-text-primary">{title}</p>
      {message && <p className="max-w-sm text-sm text-text-muted">{message}</p>}
      {action && (
        <Link href={action.href} className="mt-2 text-sm font-medium text-accent hover:text-accent-hover">
          {action.label} →
        </Link>
      )}
    </div>
  );
}
