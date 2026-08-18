const STYLES: Record<string, { label: string; className: string }> = {
  safer: { label: "🟢 Safer", className: "bg-green-100 text-green-800" },
  moderate: { label: "🔵 Moderate", className: "bg-sky-100 text-sky-800" },
  risky: { label: "🟡 Risky", className: "bg-amber-100 text-amber-800" },
  riskiest: { label: "🔴 Riskiest", className: "bg-red-100 text-red-800" },
};

export default function RiskTierBadge({ value }: { value: string | null }) {
  if (value === null) {
    return (
      <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-500">
        Risk tier: insufficient data
      </span>
    );
  }
  const style = STYLES[value] ?? STYLES.moderate;
  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${style.className}`}>{style.label}</span>;
}
