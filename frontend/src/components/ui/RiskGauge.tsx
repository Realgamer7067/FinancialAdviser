"use client";

import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

export default function RiskGauge({ value, label }: { value: number; label: string }) {
  const data = [{ name: label, value, fill: "#16a34a" }];
  return (
    <div className="flex items-center gap-4">
      <div style={{ width: 96, height: 96 }}>
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
            <RadialBar dataKey="value" cornerRadius={5} background={{ fill: "#f1f5f9" }} />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div>
        <p className="text-2xl font-semibold">{value}/100</p>
        <p className="text-sm text-slate-500">{label}</p>
      </div>
    </div>
  );
}
