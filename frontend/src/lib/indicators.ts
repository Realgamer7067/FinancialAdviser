import type { PriceHistoryPoint } from "@/lib/types";

// Client-side moving-average/Bollinger computation (Phase 0B #2 deliberate
// scope boundary): TechnicalFeatures on the backend stores one snapshot per
// pipeline run, not a historical day-by-day series, so there's no backend
// series to draw an overlay LINE from. The OHLC history endpoint already
// returns a full close-price series, so the rolling stats are computed here
// instead of adding new pipeline logic to backfill history.

export function rollingMean(values: number[], window: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= window) sum -= values[i - window];
    out.push(i >= window - 1 ? sum / window : null);
  }
  return out;
}

export function rollingStdDev(values: number[], window: number): (number | null)[] {
  const means = rollingMean(values, window);
  return values.map((_, i) => {
    const mean = means[i];
    if (mean === null || i < window - 1) return null;
    const slice = values.slice(i - window + 1, i + 1);
    const variance = slice.reduce((acc, v) => acc + (v - mean) ** 2, 0) / window;
    return Math.sqrt(variance);
  });
}

export interface OverlaySeries {
  date: string;
  close: number;
  sma20: number | null;
  sma50: number | null;
  bollingerUpper: number | null;
  bollingerLower: number | null;
}

export function computeOverlays(points: PriceHistoryPoint[]): OverlaySeries[] {
  const closes = points.map((p) => p.close);
  const sma20 = rollingMean(closes, 20);
  const sma50 = rollingMean(closes, 50);
  const stdDev20 = rollingStdDev(closes, 20);

  return points.map((p, i) => ({
    date: new Date(p.timestamp).toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
    close: p.close,
    sma20: sma20[i],
    sma50: sma50[i],
    bollingerUpper: sma20[i] !== null && stdDev20[i] !== null ? sma20[i]! + 2 * stdDev20[i]! : null,
    bollingerLower: sma20[i] !== null && stdDev20[i] !== null ? sma20[i]! - 2 * stdDev20[i]! : null,
  }));
}
