import { LucideIcon, TrendingDown, TrendingUp } from "lucide-react";
import Card from "./Card";

export default function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  trend,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: LucideIcon;
  trend?: "up" | "down";
}) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <p className="text-xs uppercase tracking-wide text-text-muted">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-text-muted" />}
      </div>
      <div className="mt-1 flex items-center gap-1.5">
        <p className="text-lg font-semibold capitalize text-text-primary">{value}</p>
        {trend === "up" && <TrendingUp className="h-4 w-4 text-positive" />}
        {trend === "down" && <TrendingDown className="h-4 w-4 text-negative" />}
      </div>
      {hint && <p className="text-xs text-text-muted">{hint}</p>}
    </Card>
  );
}
