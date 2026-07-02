"use client";

import { useState, useRef, useMemo, useEffect } from "react";
import type { AlertResultAlert } from "@/lib/api-client";
import { useTheme } from "@/contexts/ThemeContext";

// ─── Constants ────────────────────────────────────────────────────────────────

const BAR_HEIGHT     = 26;        // px
const LANE_HEIGHT    = BAR_HEIGHT; // zero gap between bars
const AXIS_HEIGHT    = 3;          // px — thickness of the central line
const AXIS_AREA_H    = 32;         // vertical space for the axis + tick labels
const PAD_V          = 16;         // padding above topmost lane and below bottommost lane
const TICK_COUNT     = 7;
const LANE_LIMIT     = 60;         // max lanes searched per side
const ZOOM_MULTIPLIER = 3;         // how many times wider the chart is in zoom mode
// ─── Color palettes ───────────────────────────────────────────────────────────

const INACTIVE_COLORS = [
  "#059669", "#10b981", "#047857", "#34d399",
  "#065f46", "#0d9488", "#14b8a6", "#16a34a",
];

const ACTIVE_COLORS = [
  "#dc2626", "#ef4444", "#b91c1c", "#f87171",
  "#991b1b", "#e11d48", "#f43f5e", "#be123c",
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTimestamp(ts: number | null | undefined): string {
  if (ts == null) return "—";
  return new Date(ts * 1000).toLocaleString();
}

// ─── Layout: sort by duration → collision-avoidance ─────────────────────────
//
//  Sorting by duration (shortest first) BEFORE lane placement means:
//    • Short alerts claim low lane numbers (closest to axis) because they
//      occupy little horizontal space and rarely collide in those lanes.
//    • Long alerts overflow into higher lane numbers because they collide
//      with almost everything in lower lanes.
//  Net effect: short alerts cluster near the axis, long alerts radiate outward.

interface AlertSegment {
  leftPct: number;
  widthPct: number;
}

interface AlertGeometry {
  alert: AlertResultAlert;
  leftPct: number;
  rightPct: number;
  widthPct: number;
  durationPct: number;
  active: boolean;
  segments: AlertSegment[];
}

interface PlacedAlert extends AlertGeometry {
  lane: number;       // +n = above axis, −n = below axis  (n ≥ 1)
  color: string;
}

// Splits an alert's values[] into gap-free segments.
// A gap is detected when two consecutive timestamps exceed 1.8× the natural step.
function detectSegments(
  alert: AlertResultAlert,
  startTs: number,
  endTs: number,
  timeStart: number,
  timeRange: number
): AlertSegment[] {
  const pct = (ts: number) =>
    Math.max(0, Math.min(100, ((ts - timeStart) / timeRange) * 100));

  const values = alert.values;
  if (!values || values.length < 2) {
    return [{ leftPct: pct(startTs), widthPct: Math.max(0.3, pct(endTs) - pct(startTs)) }];
  }

  // Detect natural step (smallest positive gap in first 20 entries)
  let minGap = Infinity;
  for (let i = 1; i < Math.min(values.length, 20); i++) {
    const g = values[i][0] - values[i - 1][0];
    if (g > 0) minGap = Math.min(minGap, g);
  }
  const threshold = minGap === Infinity ? Infinity : minGap * 1.8;

  const segs: AlertSegment[] = [];
  let segStart = startTs;

  for (let i = 1; i < values.length; i++) {
    if (values[i][0] - values[i - 1][0] > threshold) {
      const l = pct(segStart);
      const r = pct(values[i - 1][0]);
      if (r > l) segs.push({ leftPct: l, widthPct: r - l });
      segStart = values[i][0];
    }
  }
  // Final segment
  const l = pct(segStart);
  const r = pct(endTs);
  if (r > l) segs.push({ leftPct: l, widthPct: r - l });

  return segs.length > 0
    ? segs
    : [{ leftPct: pct(startTs), widthPct: Math.max(0.3, pct(endTs) - pct(startTs)) }];
}

function computeLayout(
  alerts: AlertResultAlert[],
  timeStart: number,
  timeEnd: number,
  now: number
): PlacedAlert[] {
  const timeRange = timeEnd - timeStart || 1;

  const items: AlertGeometry[] = alerts
    .map((alert): AlertGeometry | null => {
      const startTs = alert.episode_start_ts ?? alert.values?.[0]?.[0] ?? null;
      if (startTs == null) return null;
      // All alerts passed to timeline are pre-filtered as active by AlertsView
      // so we don't recalculate — just treat them all as active
      const active      = true;
      const lastValueTs = alert.values && alert.values.length > 0
        ? alert.values[alert.values.length - 1][0]
        : null;
      const endTs = timeEnd;
      const cStart  = Math.max(startTs, timeStart);
      const cEnd    = Math.min(endTs,   timeEnd);
      if (cEnd <= cStart) return null;
      const leftPct     = ((cStart - timeStart) / timeRange) * 100;
      const rightPct    = ((cEnd   - timeStart) / timeRange) * 100;
      const durationPct = rightPct - leftPct;
      const segments    = detectSegments(alert, startTs, endTs, timeStart, timeRange);
      return { alert, leftPct, rightPct, widthPct: Math.max(0.3, durationPct), durationPct, active, segments };
    })
    .filter((x): x is AlertGeometry => x !== null);

  // ── Sort longest-first so they get the lowest (closest) lanes ──────────
  items.sort((a, b) => b.durationPct - a.durationPct);

  // ── One alert per lane, assigned in order: 1, −1, 2, −2, … ─────────────
  const laneOrder = Array.from({ length: LANE_LIMIT * 2 }, (_, i) =>
    i % 2 === 0 ? i / 2 + 1 : -(Math.floor(i / 2) + 1)
  );

  let activeIdx   = 0;
  let inactiveIdx = 0;

  const placed: PlacedAlert[] = items.map((item, i) => {
    const lane  = laneOrder[i] ?? (i + 1);
    const color = item.active
      ? ACTIVE_COLORS[activeIdx++   % ACTIVE_COLORS.length]
      : INACTIVE_COLORS[inactiveIdx++ % INACTIVE_COLORS.length];
    return { ...item, lane, color };
  });

  return placed;
}

// ─── Component ────────────────────────────────────────────────────────────────

interface TooltipState {
  alert: AlertResultAlert;
  active: boolean;
  x: number;
  y: number;
}

export function AlertsTimeline({
  alerts,
  timeStart,
  timeEnd,
  loading,
  isZoomed = false,
}: {
  alerts: AlertResultAlert[];
  timeStart: number;
  timeEnd: number;
  loading?: boolean;
  isZoomed?: boolean;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const axisRef    = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const { isDark } = useTheme();
  // Recalculate "now" whenever the time window changes (new query)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const now = useMemo(() => Math.floor(Date.now() / 1000), [timeStart, timeEnd]);

  const placed = useMemo(
    () => computeLayout(alerts, timeStart, timeEnd, now),
    [alerts, timeStart, timeEnd, now]
  );

  // Scroll the above-bars section to show the bottom (closest to axis) on load
  const aboveScrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (aboveScrollRef.current) {
      aboveScrollRef.current.scrollTop = aboveScrollRef.current.scrollHeight;
    }
  }, [placed]);

  if (loading) {
    return (
      <div className={`flex flex-col items-center justify-center gap-4 min-h-[240px] ${isDark ? "bg-gray-900" : "bg-white"}`}>
        <div className={`w-10 h-10 border-4 rounded-full animate-spin ${
          isDark
            ? "border-blue-400 border-t-transparent"
            : "border-[#002244] border-t-transparent"
        }`} />
        <p className={`text-sm ${isDark ? "text-gray-400" : "text-gray-600"}`}>Loading timeline…</p>
      </div>
    );
  }

  if (placed.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-gray-400">
        <p className="text-sm">No timeline data — alerts are missing timestamps.</p>
      </div>
    );
  }

  // ── Geometry ────────────────────────────────────────────────────────────
  const maxAbove = Math.max(...placed.map((p) => (p.lane > 0 ? p.lane : 0)), 1);
  const maxBelow = Math.max(...placed.map((p) => (p.lane < 0 ? -p.lane : 0)), 0);

  const aboveAreaH = maxAbove * LANE_HEIGHT;
  const belowAreaH = maxBelow * LANE_HEIGHT;

  // ── Tick helpers ─────────────────────────────────────────────────────────
  const timeRange = timeEnd - timeStart || 1;
  const ticks = Array.from({ length: TICK_COUNT }, (_, i) => ({
    pct: (i / (TICK_COUNT - 1)) * 100,
    label: new Date(
      (timeStart + (timeRange * i) / (TICK_COUNT - 1)) * 1000
    ).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  }));

  // ── Event handlers ───────────────────────────────────────────────────────
  const handleEnter = (e: React.MouseEvent, pa: PlacedAlert) => {
    const rect = wrapperRef.current?.getBoundingClientRect();
    if (rect)
      setTooltip({ alert: pa.alert, active: pa.active, x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const handleMove = (e: React.MouseEvent) => {
    const rect = wrapperRef.current?.getBoundingClientRect();
    if (rect && tooltip)
      setTooltip((t) => (t ? { ...t, x: e.clientX - rect.left, y: e.clientY - rect.top } : null));
  };

  // Shared bar renderer used in both above/below sections
  const renderBar = (pa: PlacedAlert, idx: number, keyPrefix: string, topY: number) => {
    const label = pa.alert.alert_sla_name || pa.alert.alertname || `Alert ${idx + 1}`;
    const cw = pa.widthPct || 1;
    return (
      <div
        key={`${pa.alert.alert_id || "a"}-${keyPrefix}-${idx}`}
        className="absolute cursor-pointer transition-opacity hover:opacity-80"
        style={{ left: `${pa.leftPct}%`, width: `${pa.widthPct}%`, top: topY, height: BAR_HEIGHT, minWidth: 6 }}
        onMouseEnter={(e) => handleEnter(e, pa)}
        onMouseLeave={() => setTooltip(null)}
      >
        {pa.segments.map((seg, sIdx) => (
          <div key={sIdx} className="absolute top-0 bottom-0" style={{
            left: `${Math.max(0, ((seg.leftPct - pa.leftPct) / cw) * 100)}%`,
            width: `${Math.max(0, (seg.widthPct / cw) * 100)}%`,
            backgroundColor: pa.color,
            borderBottom: "1px solid rgba(0,0,0,0.10)",
          }} />
        ))}
        {pa.segments[0] && (
          <span
            className="absolute flex items-center text-white/90 text-[11px] font-medium truncate leading-none drop-shadow-sm pointer-events-none z-10"
            style={{
              left: `${Math.max(0, ((pa.segments[0].leftPct - pa.leftPct) / cw) * 100)}%`,
              width: `${Math.max(0, (pa.segments[0].widthPct / cw) * 100)}%`,
              top: 0, bottom: 0, paddingLeft: 8, paddingRight: 4,
            }}
          >
            {label}
          </span>
        )}
      </div>
    );
  };

  const gridLines = ticks.map((t, i) => (
    <div key={i} className="absolute top-0 bottom-0 pointer-events-none"
      style={{ left: `${t.pct}%`, width: 1, backgroundColor: isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)" }}
    />
  ));

  return (
    <div
      ref={wrapperRef}
      className="relative font-sans select-none flex flex-col h-full"
      onMouseMove={handleMove}
    >

      {/* ── Legend ───────────────────────────────────────────────────────── */}
      <div className={`flex-shrink-0 border-b shadow-sm ${isDark ? "bg-gray-900 border-gray-700" : "bg-white border-gray-200"}`}>
        <div className="flex items-center gap-6 px-6 py-2">
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-3 rounded" style={{ backgroundColor: ACTIVE_COLORS[0] }} />
            <span className={`text-xs ${isDark ? "text-gray-300" : "text-gray-600"}`}>Active alerts only</span>
          </div>
          <span className={`text-xs ml-auto ${isDark ? "text-gray-500" : "text-gray-400"}`}>Hover for details</span>
        </div>
      </div>

      {/* ── Horizontally scrollable wrapper (zoom mode expands to ZOOM_MULTIPLIER×) */}
      <div className="flex-1 min-h-0 overflow-x-auto">
        <div
          className="flex flex-col h-full"
          style={{ minWidth: isZoomed ? `${ZOOM_MULTIPLIER * 100}%` : "100%" }}
        >

          {/* ── Above bars ─────────────────────────────────────────────────── */}
          <div ref={aboveScrollRef} className="flex-1 overflow-y-auto min-h-0">
            <div className="relative px-6" style={{ height: aboveAreaH + PAD_V }}>
              {gridLines}
              {placed
                .filter(p => p.lane > 0)
                .map((pa, idx) => renderBar(pa, idx, "above", aboveAreaH + PAD_V - pa.lane * LANE_HEIGHT))
              }
            </div>
          </div>

          {/* ── Axis ───────────────────────────────────────────────────────── */}
          <div
            ref={axisRef}
            className={`flex-shrink-0 relative px-6 border-t border-b ${isDark ? "bg-gray-900 border-gray-600" : "bg-white border-gray-300"}`}
            style={{ height: AXIS_AREA_H, zIndex: 20 }}
          >
            {gridLines}
            {/* Axis line */}
            <div className="absolute left-0 right-0" style={{
              top: 0, height: AXIS_HEIGHT,
              backgroundColor: isDark ? "#ffffff" : "#1e293b",
              boxShadow: isDark ? "0 0 6px rgba(255,255,255,0.20)" : "0 0 6px rgba(0,0,0,0.30)",
              zIndex: 10,
            }} />
            {/* Tick marks + labels */}
            {ticks.map((t, i) => (
              <div key={i} className="absolute flex flex-col items-center" style={{
                left: `${t.pct}%`, top: 0,
                transform: i === 0 ? "translateX(0)" : i === TICK_COUNT - 1 ? "translateX(-100%)" : "translateX(-50%)",
              }}>
                <div style={{ width: 2, height: AXIS_HEIGHT + 6, backgroundColor: isDark ? "#ffffff" : "#334155", zIndex: 11, position: "relative" }} />
                <span className="text-[11px] font-semibold whitespace-nowrap mt-1" style={{ color: isDark ? "#ffffff" : "#334155" }}>
                  {t.label}
                </span>
              </div>
            ))}
          </div>

          {/* ── Below bars ─────────────────────────────────────────────────── */}
          <div className="flex-1 overflow-y-auto min-h-0">
            <div className="relative px-6" style={{ height: Math.max(belowAreaH + PAD_V, PAD_V) }}>
              {gridLines}
              {placed
                .filter(p => p.lane < 0)
                .map((pa, idx) => renderBar(pa, idx, "below", (-pa.lane - 1) * LANE_HEIGHT))
              }
            </div>
          </div>

        </div>
      </div>

      {/* ── Tooltip ──────────────────────────────────────────────────────── */}
      {tooltip && (() => {
        const a         = tooltip.alert;
        const startTs   = a.episode_start_ts ?? a.values?.[0]?.[0] ?? null;
        const lastValTs = a.values && a.values.length > 0 ? a.values[a.values.length - 1][0] : null;
        const endTs     = tooltip.active ? now : (a.episode_end_ts ?? lastValTs ?? null);
        const containerW = wrapperRef.current?.offsetWidth ?? 600;
        const flipLeft   = tooltip.x > containerW * 0.6;
        return (
          <div
            className="absolute z-50 pointer-events-none bg-[#002244] text-white text-xs rounded-lg shadow-2xl p-3 w-96 overflow-auto max-h-96"
            style={{ left: flipLeft ? tooltip.x - 400 : tooltip.x + 14, top: tooltip.y - 8 }}
          >
            <div className="font-semibold mb-2 leading-snug break-all">
              {a.alertname || a.alert_sla_name || "Alert"}
            </div>
            <div className="space-y-1 text-white/75 mb-3 pb-3 border-b border-white/20">
              {a.alert_sla_name && (
                <div className="flex gap-1">
                  <span className="text-white/50 shrink-0">SLA:</span>
                  <span className="break-all">{a.alert_sla_name}</span>
                </div>
              )}
              <div className="flex gap-1">
                <span className="text-white/50 shrink-0">Status:</span>
                <span className={tooltip.active ? "text-red-300 font-medium" : "text-emerald-300 font-medium"}>
                  {tooltip.active ? "Active" : "Inactive"}
                </span>
              </div>
              <div className="flex gap-1">
                <span className="text-white/50 shrink-0">Start:</span>
                <span className="break-all">{formatTimestamp(startTs)}</span>
              </div>
              <div className="flex gap-1">
                <span className="text-white/50 shrink-0">End:</span>
                {tooltip.active
                  ? <span className="text-red-300">Ongoing</span>
                  : <span className="break-all">{formatTimestamp(endTs)}</span>}
              </div>
              {a.cluster && (
                <div className="flex gap-1">
                  <span className="text-white/50 shrink-0">Cluster:</span>
                  <span className="break-all">{a.cluster}</span>
                </div>
              )}
              {a.alert_owner_category && (
                <div className="flex gap-1">
                  <span className="text-white/50 shrink-0">Category:</span>
                  <span className="break-all">{a.alert_owner_category}</span>
                </div>
              )}
            </div>
            {/* Values Array - for debugging */}
            {a.values && a.values.length > 0 && (
              <div className="text-white/75">
                <div className="font-semibold text-white/90 mb-1">Values ({a.values.length} points):</div>
                <div className="space-y-0.5 max-h-56 overflow-y-auto pr-1 border border-white/10 rounded p-2 bg-white/5">
                  {a.values.map((val, idx) => (
                    <div key={idx} className="text-white/60 font-mono text-[10px] flex justify-between gap-2">
                      <span className="whitespace-nowrap">{new Date(val[0] * 1000).toLocaleTimeString()}</span>
                      <span className="text-right flex-shrink-0">{val[1]}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
