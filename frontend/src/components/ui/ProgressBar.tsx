export default function ProgressBar({
  label,
  value,
  displayValue,
  colorClass = "bg-brand-600",
}: {
  label: string;
  value: number; // 0-100
  displayValue?: string;
  colorClass?: string;
}) {
  const clamped = Math.max(0, Math.min(value, 100));
  return (
    <div className="flex items-center gap-3">
      <span className="w-32 shrink-0 text-sm text-slate-600">{label}</span>
      <div className="h-2 flex-1 rounded bg-slate-100">
        <div className={`h-2 rounded ${colorClass}`} style={{ width: `${clamped}%` }} />
      </div>
      <span className="w-12 shrink-0 text-right text-sm text-slate-600">
        {displayValue ?? `${clamped.toFixed(0)}%`}
      </span>
    </div>
  );
}
