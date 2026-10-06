"use client";

import { useMemo } from "react";

type Point = { d: string; c: number };

// Plain SVG line of closing prices. The y-axis is labelled with the real min/max so the picture cannot mislead
// about scale; the text summary below it carries the same facts for screen readers.
export default function PriceChart({ points, marks }: { points: Point[]; marks?: { d: string; label: string }[] }) {
  const W = 640, H = 180, PAD = 6;
  const geo = useMemo(() => {
    if (points.length < 2) return null;
    const ys = points.map((p) => p.c);
    const min = Math.min(...ys), max = Math.max(...ys);
    const span = max - min || 1;
    const x = (i: number) => PAD + (i / (points.length - 1)) * (W - 2 * PAD);
    const y = (v: number) => H - PAD - ((v - min) / span) * (H - 2 * PAD);
    const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.c).toFixed(1)}`).join(" ");
    const idx = new Map(points.map((p, i) => [p.d, i]));
    const flags = (marks ?? []).flatMap((m) => {
      const i = [...idx.entries()].find(([d]) => d >= m.d)?.[1];
      return i === undefined ? [] : [{ x: x(i), label: m.label }];
    });
    return { min, max, path, flags };
  }, [points, marks]);

  if (!geo) return <p className="text-sm text-text-muted">Not enough history to draw a chart yet.</p>;
  const first = points[0], last = points[points.length - 1];
  const change = ((last.c / first.c) - 1) * 100;
  const fmt = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-44 w-full" role="img"
        aria-label={`Closing price from ${first.d} (₹${fmt(first.c)}) to ${last.d} (₹${fmt(last.c)}), ${change >= 0 ? "up" : "down"} ${Math.abs(change).toFixed(1)}%. Low ₹${fmt(geo.min)}, high ₹${fmt(geo.max)}.`}>
        <path d={geo.path} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" className="text-accent" />
        {geo.flags.map((f, i) => <line key={i} x1={f.x} x2={f.x} y1={0} y2={H} stroke="currentColor" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" className="text-warning"><title>{f.label}</title></line>)}
      </svg>
      <figcaption className="mt-1 flex flex-wrap justify-between gap-2 text-xs text-text-muted">
        <span>{first.d}: ₹{fmt(first.c)}</span>
        <span>low ₹{fmt(geo.min)} · high ₹{fmt(geo.max)}</span>
        <span>{last.d}: ₹{fmt(last.c)} ({change >= 0 ? "+" : ""}{change.toFixed(1)}%)</span>
      </figcaption>
    </figure>
  );
}
