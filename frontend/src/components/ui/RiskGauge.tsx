"use client";

import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

// "profile" = user's risk-tolerance score (always the accent color).
// "tier" = a stock's own objective riskiness (0-100, higher = riskier) --
// color shifts through the same safer/moderate/risky/riskiest bands the
// backend uses (config/scoring.yaml's risk_tier.thresholds), so the gauge and
// the RiskTierBadge label never disagree about what "risky" means.
type Tone = "profile" | "tier";

function fillFor(tone: Tone, value: number): string {
  if (tone === "profile") return "#4f46e5"; // accent (indigo)
  if (value < 30) return "#059669"; // positive
  if (value < 55) return "#4f46e5"; // accent (indigo)
  if (value < 80) return "#d97706"; // warning
  return "#dc2626"; // negative
}

export default function RiskGauge({ value, label, tone = "profile" }: { value: number; label: string; tone?: Tone }) {
  const data = [{ name: label, value, fill: fillFor(tone, value) }];
  return (
    <div className="flex items-center gap-4">
      <div
        style={{ width: 96, height: 96 }}
        role="img"
        aria-label={`${label}: ${value} out of 100`}
      >
        <ResponsiveContainer>
          <RadialBarChart
            innerRadius="70%"
            outerRadius="100%"
            data={data}
            startAngle={90}
            endAngle={-270}
            barSize={10}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
            <RadialBar dataKey="value" cornerRadius={5} background={{ fill: "rgb(226 232 240)" }} />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div>
        <p className="text-2xl font-semibold text-text-primary">{value}/100</p>
        <p className="text-sm text-text-muted">{label}</p>
      </div>
    </div>
  );
}
