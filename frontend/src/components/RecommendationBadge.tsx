import clsx from "clsx";

const STYLES: Record<string, { label: string; dot: string; className: string }> = {
  STRONG_CANDIDATE: { label: "Strong Candidate", dot: "bg-positive", className: "bg-positive-subtle text-positive" },
  CANDIDATE: { label: "Candidate", dot: "bg-accent", className: "bg-accent-subtle text-accent" },
  WATCHLIST: { label: "Watchlist", dot: "bg-warning", className: "bg-warning-subtle text-warning" },
  NO_RECOMMENDATION: { label: "No Clear Opportunity", dot: "bg-text-muted", className: "bg-border/40 text-text-muted" },
};

export default function RecommendationBadge({ value }: { value: string }) {
  const style = STYLES[value] ?? STYLES.NO_RECOMMENDATION;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium", style.className)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", style.dot)} />
      {style.label}
    </span>
  );
}
