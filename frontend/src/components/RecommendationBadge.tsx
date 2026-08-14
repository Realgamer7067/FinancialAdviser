const STYLES: Record<string, { label: string; className: string }> = {
  STRONG_CANDIDATE: { label: "🟢 Strong Candidate", className: "bg-green-100 text-green-800" },
  CANDIDATE: { label: "🟢 Candidate", className: "bg-green-50 text-green-700" },
  WATCHLIST: { label: "🟡 Watchlist", className: "bg-amber-100 text-amber-800" },
  NO_RECOMMENDATION: { label: "⚪ No Clear Opportunity", className: "bg-slate-100 text-slate-600" },
};

export default function RecommendationBadge({ value }: { value: string }) {
  const style = STYLES[value] ?? STYLES.NO_RECOMMENDATION;
  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${style.className}`}>{style.label}</span>;
}
