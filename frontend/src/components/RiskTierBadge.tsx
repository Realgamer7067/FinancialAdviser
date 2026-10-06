import clsx from "clsx";

const STYLES: Record<string, { label: string; dot: string; className: string }> = {
  safer: { label: "Safer", dot: "bg-positive", className: "bg-positive-subtle text-positive" },
  moderate: { label: "Moderate", dot: "bg-accent", className: "bg-accent-subtle text-accent" },
  risky: { label: "Risky", dot: "bg-warning", className: "bg-warning-subtle text-warning" },
  riskiest: { label: "Riskiest", dot: "bg-negative", className: "bg-negative-subtle text-negative" },
};

export default function RiskTierBadge({ value }: { value: string | null }) {
  if (value === null) {
    return (
      <span className="inline-flex items-center rounded-full bg-border/40 px-2 py-1 text-xs font-medium text-text-muted">
        Risk tier: insufficient data
      </span>
    );
  }
  const style = STYLES[value] ?? STYLES.moderate;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium", style.className)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", style.dot)} />
      {style.label}
    </span>
  );
}
