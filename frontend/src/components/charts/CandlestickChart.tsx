"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { KronosForecast, PriceHistoryPoint } from "@/lib/types";
import { computeOverlays } from "@/lib/indicators";
import { fadeIn } from "@/lib/motion";

const POSITIVE = "#059669";
const NEGATIVE = "#dc2626";

const HORIZONS: KronosForecast["forecast_horizon"][] = ["7d", "30d", "90d"];
const HORIZON_DAYS: Record<KronosForecast["forecast_horizon"], number> = { "7d": 7, "30d": 30, "90d": 90 };

const DIRECTION_COLOR: Record<string, string> = {
  bullish: "#059669",
  neutral: "#94a3b8",
  bearish: "#dc2626",
};

const DEFAULT_HISTORY_WINDOW_DAYS = 90; // ~3 months of recent candles -- keeps the forecast segment readable instead of squeezed into a sliver at the far right of a full multi-year history

interface CandleDatum {
  date: string;
  low: number | null;
  high: number | null;
  open: number | null;
  close: number | null;
  bullish: boolean | null;
  sma20: number | null;
  sma50: number | null;
  // Forecast overlay (Kronos): one path connecting the last real close
  // through however many of the 3 real horizon predictions are toggled on
  // (7d/30d/90d, sorted ascending) -- null everywhere except the anchor
  // point (last real close, zero-width) and the forecast points themselves.
  // This connects only real model outputs (median return per horizon); no
  // intermediate day is fabricated.
  forecastPrice: number | null;
  isForecast: boolean;
  horizon: KronosForecast["forecast_horizon"] | null;
  // Per-horizon band fields, keyed so up to 3 bands can be shown
  // independently without one clobbering another on the same row.
  band7dBase: number | null;
  band7dHeight: number | null;
  band30dBase: number | null;
  band30dHeight: number | null;
  band90dBase: number | null;
  band90dHeight: number | null;
}

const BAND_FIELD: Record<KronosForecast["forecast_horizon"], { base: keyof CandleDatum; height: keyof CandleDatum }> = {
  "7d": { base: "band7dBase", height: "band7dHeight" },
  "30d": { base: "band30dBase", height: "band30dHeight" },
  "90d": { base: "band90dBase", height: "band90dHeight" },
};

// Recharts has no first-class candlestick mark. Rendering one Bar per point
// with dataKey=[low, high] (a floating-bar tuple) means recharts hands the
// custom shape() exact pixel y/height for that low-high span -- interpolating
// the open/close body within that span needs no separate scale lookup.
function CandleShape(props: { x?: number; y?: number; width?: number; height?: number; payload?: CandleDatum }) {
  const { x = 0, y = 0, width = 0, height = 0, payload } = props;
  if (!payload || payload.low === null || payload.high === null || payload.open === null || payload.close === null) {
    return null; // forecast points have no OHLC -- nothing to draw here, only the dashed line/band
  }
  const { low, high, open, close, bullish } = payload;
  const range = high - low || 1;
  const valueToY = (v: number) => y + height * (1 - (v - low) / range);

  const bodyTop = valueToY(Math.max(open, close));
  const bodyBottom = valueToY(Math.min(open, close));
  const bodyHeight = Math.max(bodyBottom - bodyTop, 1);
  const color = bullish ? POSITIVE : NEGATIVE;
  const wickX = x + width / 2;
  const bodyWidth = Math.max(width * 0.75, 3);
  const bodyX = x + (width - bodyWidth) / 2;

  return (
    <g>
      <line x1={wickX} x2={wickX} y1={y} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={bodyX} y={bodyTop} width={bodyWidth} height={bodyHeight} fill={color} />
    </g>
  );
}

function formatDateLabel(d: Date): string {
  return d.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
}

export default function CandlestickChart({
  points,
  forecasts = [],
}: {
  points: PriceHistoryPoint[];
  forecasts?: KronosForecast[];
}) {
  const [showSma20, setShowSma20] = useState(true);
  const [showSma50, setShowSma50] = useState(false);
  const [showFullHistory, setShowFullHistory] = useState(false);
  const [activeHorizons, setActiveHorizons] = useState<Set<KronosForecast["forecast_horizon"]>>(
    new Set(forecasts.map((f) => f.forecast_horizon))
  );

  const toggleHorizon = (h: KronosForecast["forecast_horizon"]) => {
    setActiveHorizons((prev) => {
      const next = new Set(prev);
      if (next.has(h)) next.delete(h);
      else next.add(h);
      return next;
    });
  };

  const visiblePoints = useMemo(() => {
    if (showFullHistory || points.length <= DEFAULT_HISTORY_WINDOW_DAYS) return points;
    return points.slice(-DEFAULT_HISTORY_WINDOW_DAYS);
  }, [points, showFullHistory]);

  // SMA needs the FULL history to compute correctly at the start of the
  // visible window (a 20/50-day average can't be trimmed first) -- compute
  // over the full series, then slice the overlay output to match.
  const overlaysFull = useMemo(() => computeOverlays(points), [points]);
  const overlays = useMemo(
    () => (showFullHistory || points.length <= DEFAULT_HISTORY_WINDOW_DAYS ? overlaysFull : overlaysFull.slice(-DEFAULT_HISTORY_WINDOW_DAYS)),
    [overlaysFull, points.length, showFullHistory]
  );

  const activeForecasts = useMemo(
    () => HORIZONS.map((h) => forecasts.find((f) => f.forecast_horizon === h)).filter((f): f is KronosForecast => !!f && activeHorizons.has(f.forecast_horizon)),
    [forecasts, activeHorizons]
  );

  const data: CandleDatum[] = useMemo(() => {
    const base: CandleDatum[] = visiblePoints.map((p, i) => ({
      date: overlays[i]?.date ?? "",
      low: p.low,
      high: p.high,
      open: p.open,
      close: p.close,
      bullish: p.close >= p.open,
      sma20: overlays[i]?.sma20 ?? null,
      sma50: overlays[i]?.sma50 ?? null,
      forecastPrice: null,
      isForecast: false,
      horizon: null,
      band7dBase: null,
      band7dHeight: null,
      band30dBase: null,
      band30dHeight: null,
      band90dBase: null,
      band90dHeight: null,
    }));

    const lastPoint = points[points.length - 1];
    if (activeForecasts.length === 0 || !lastPoint) return base;

    const lastClose = lastPoint.close;
    const anchor = base[base.length - 1];
    // Anchor the dashed line/every band at the last REAL point with
    // zero-width values -- otherwise the forecast segment renders as
    // disconnected floating shapes instead of visibly continuing from real
    // data.
    anchor.forecastPrice = lastClose;
    for (const h of HORIZONS) {
      const { base: baseKey, height: heightKey } = BAND_FIELD[h];
      (anchor[baseKey] as number | null) = lastClose;
      (anchor[heightKey] as number | null) = 0;
    }

    const forecastRows: CandleDatum[] = activeForecasts.map((f) => {
      const forecastDate = new Date(lastPoint.timestamp);
      forecastDate.setDate(forecastDate.getDate() + HORIZON_DAYS[f.forecast_horizon]);
      const predictedPrice = lastClose * (1 + f.predicted_return);
      const bandLow = lastClose * (1 + f.predicted_return_p10);
      const bandHigh = lastClose * (1 + f.predicted_return_p90);
      const { base: baseKey, height: heightKey } = BAND_FIELD[f.forecast_horizon];

      const row: CandleDatum = {
        date: formatDateLabel(forecastDate),
        low: null,
        high: null,
        open: null,
        close: null,
        bullish: null,
        sma20: null,
        sma50: null,
        forecastPrice: predictedPrice,
        isForecast: true,
        horizon: f.forecast_horizon,
        band7dBase: null,
        band7dHeight: null,
        band30dBase: null,
        band30dHeight: null,
        band90dBase: null,
        band90dHeight: null,
      };
      (row[baseKey] as number | null) = bandLow;
      (row[heightKey] as number | null) = bandHigh - bandLow;
      return row;
    });

    return [...base, ...forecastRows];
  }, [visiblePoints, overlays, points, activeForecasts]);

  if (points.length === 0) {
    return <p className="text-sm text-text-muted">No price history available yet.</p>;
  }

  const lastActualLabel = overlays[overlays.length - 1]?.date;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-xs">
        <label className="flex cursor-pointer items-center gap-1.5 text-text-muted">
          <input type="checkbox" checked={showSma20} onChange={(e) => setShowSma20(e.target.checked)} className="accent-accent" />
          SMA 20
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-text-muted">
          <input type="checkbox" checked={showSma50} onChange={(e) => setShowSma50(e.target.checked)} className="accent-accent" />
          SMA 50
        </label>
        {points.length > DEFAULT_HISTORY_WINDOW_DAYS && (
          <label className="flex cursor-pointer items-center gap-1.5 text-text-muted">
            <input type="checkbox" checked={showFullHistory} onChange={(e) => setShowFullHistory(e.target.checked)} className="accent-accent" />
            Full history
          </label>
        )}
        {forecasts.length > 0 && (
          <div className="ml-auto flex items-center gap-1">
            <span className="text-text-muted">Kronos forecast:</span>
            {forecasts.map((f) => (
              <button
                key={f.forecast_horizon}
                type="button"
                onClick={() => toggleHorizon(f.forecast_horizon)}
                title={`${f.direction}, ${f.confidence == null ? "not yet calibrated" : `${(f.confidence * 100).toFixed(0)}% confidence`}`}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  activeHorizons.has(f.forecast_horizon) ? "text-white" : "bg-slate-100 text-text-muted hover:bg-slate-200"
                }`}
                style={activeHorizons.has(f.forecast_horizon) ? { backgroundColor: DIRECTION_COLOR[f.direction] } : undefined}
              >
                {f.forecast_horizon} {f.direction === "bullish" ? "↑" : f.direction === "bearish" ? "↓" : "→"}
              </button>
            ))}
          </div>
        )}
      </div>
      <motion.div initial="hidden" animate="visible" variants={fadeIn} style={{ width: "100%", height: 300 }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ left: 8, right: 16, top: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgb(226 232 240)" />
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: "rgb(100 116 139)" }} stroke="rgb(226 232 240)" minTickGap={30} />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fontSize: 11, fill: "rgb(100 116 139)" }}
              stroke="rgb(226 232 240)"
              width={56}
              tickFormatter={(v: number) => `₹${v.toFixed(0)}`}
            />
            <Tooltip
              formatter={(v: number | number[], name: string, item: { payload?: CandleDatum }) => {
                // The candle Bar's dataKey returns a [low, high] tuple (a
                // recharts floating-bar range) -- recharts calls this same
                // formatter for that series too, so `v` is an array there,
                // not a number. The Line series (SMA20/50/forecast) pass
                // plain numbers.
                if (Array.isArray(v)) {
                  // Forecast rows carry no OHLC -- this Bar series is [null, null]
                  // there, and recharts still calls this formatter for every
                  // series at the hovered x-index, forecast rows included.
                  // `.toFixed()` on null crashed the whole tooltip on hover.
                  const [low, high] = v;
                  if (low == null || high == null) return ["–", "Range"]; // no OHLC on a forecast row
                  return [`₹${low.toFixed(2)} – ₹${high.toFixed(2)}`, "Range"];
                }
                if (name === "Kronos forecast" && item.payload?.isForecast && item.payload.horizon) {
                  const f = forecasts.find((x) => x.forecast_horizon === item.payload!.horizon);
                  if (!f) return [`₹${v.toFixed(2)}`, name];
                  const confidenceLabel = f.confidence == null ? "not yet calibrated" : `${(f.confidence * 100).toFixed(0)}% confidence`;
                  return [
                    `₹${v.toFixed(2)} (${f.direction}, ${confidenceLabel}, ${f.sample_count} samples)`,
                    `Kronos ${f.forecast_horizon} forecast (median)`,
                  ];
                }
                if (v == null) return ["–", name]; // e.g. SMA on a forecast row, or a band series with connectNulls
                return [`₹${v.toFixed(2)}`, name];
              }}
              labelFormatter={(label) => label}
            />
            <Bar dataKey={(d: CandleDatum) => [d.low, d.high]} shape={CandleShape as never} isAnimationActive={false} />
            {showSma20 && <Line type="monotone" dataKey="sma20" name="SMA 20" stroke="#0ea5e9" strokeWidth={1.5} dot={false} connectNulls />}
            {showSma50 && <Line type="monotone" dataKey="sma50" name="SMA 50" stroke="#8b5cf6" strokeWidth={1.5} dot={false} connectNulls />}
            {activeForecasts.length > 0 && lastActualLabel && (
              <ReferenceLine x={lastActualLabel} stroke="rgb(148 163 184)" strokeDasharray="2 2" label={{ value: "today", position: "insideTopLeft", fontSize: 10, fill: "rgb(100 116 139)" }} />
            )}
            {HORIZONS.map((h) => {
              if (!activeHorizons.has(h)) return null;
              const f = forecasts.find((x) => x.forecast_horizon === h);
              if (!f) return null;
              const { base: baseKey } = BAND_FIELD[h];
              return (
                <Area
                  key={`${h}-base`}
                  dataKey={baseKey as string}
                  stackId={`band-${h}`}
                  stroke="none"
                  fill="transparent"
                  isAnimationActive={false}
                  legendType="none"
                  tooltipType="none"
                  connectNulls
                />
              );
            })}
            {HORIZONS.map((h) => {
              if (!activeHorizons.has(h)) return null;
              const f = forecasts.find((x) => x.forecast_horizon === h);
              if (!f) return null;
              const { height: heightKey } = BAND_FIELD[h];
              const color = DIRECTION_COLOR[f.direction];
              return (
                <Area
                  key={`${h}-band`}
                  dataKey={heightKey as string}
                  name={`${h} band`}
                  stackId={`band-${h}`}
                  stroke="none"
                  fill={color}
                  fillOpacity={0.1}
                  isAnimationActive={false}
                  tooltipType="none"
                  connectNulls
                />
              );
            })}
            {activeForecasts.length > 0 && (
              <Line
                type="linear"
                dataKey="forecastPrice"
                name="Kronos forecast"
                stroke="#334155"
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={(props: { cx?: number; cy?: number; payload?: CandleDatum; key?: string }) => {
                  if (!props.payload?.isForecast || !props.payload.horizon) return <g key={props.key} />;
                  const f = forecasts.find((x) => x.forecast_horizon === props.payload!.horizon);
                  return <circle key={props.key} cx={props.cx} cy={props.cy} r={4} fill={DIRECTION_COLOR[f?.direction ?? "neutral"]} stroke="white" strokeWidth={1.5} />;
                }}
                connectNulls
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </motion.div>
      {activeForecasts.length > 0 && (
        <p className="mt-1 text-xs text-text-muted">
          Dashed line connects the last real close through each toggled Kronos horizon&apos;s median forecast (only real model outputs, no
          days in between are invented); shaded bands = each horizon&apos;s own 10th-90th percentile range. This is a model projection, not
          real price data.{" "}
          {activeForecasts.some((f) => f.confidence == null) &&
            "Confidence not yet calibrated for this model version -- shown as evidence only, excluded from scoring."}
        </p>
      )}
    </div>
  );
}
