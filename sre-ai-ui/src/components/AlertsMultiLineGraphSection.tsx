"use client";

import { useState, useCallback, useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceArea,
} from "recharts";
import { ZoomOut, Maximize2, Minimize2, Loader, AlertCircle } from "lucide-react";
import { useTheme } from "@/contexts/ThemeContext";

// ─── Types ──────────────────────────────────────────────────────────────────

export interface MultiSeriesDataPoint {
  timestamp: number;
  [seriesKey: string]: number; // each alert_type becomes a key
}

export interface MultiSeriesGraphData {
  points: MultiSeriesDataPoint[];
  seriesKeys: string[]; // list of unique alert_type values
}

interface AlertsMultiLineGraphSectionProps {
  title: string;
  subtitle?: string;
  data: MultiSeriesGraphData;
  loading: boolean;
  error: string | null;
  yAxisLabel?: string;
  /** Hide the Y-axis entirely — useful for timeline-style graphs */
  hideYAxis?: boolean;
}

// ─── Color palette for series ───────────────────────────────────────────────

const SERIES_COLORS = [
  "#ef4444", // red
  "#3b82f6", // blue
  "#10b981", // emerald
  "#f59e0b", // amber
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#06b6d4", // cyan
  "#f97316", // orange
  "#14b8a6", // teal
  "#6366f1", // indigo
  "#84cc16", // lime
  "#e11d48", // rose
  "#0ea5e9", // sky
  "#a855f7", // purple
];

function getSeriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatXTick(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatTooltipTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// ─── Component ──────────────────────────────────────────────────────────────

export function AlertsMultiLineGraphSection({
  title,
  subtitle,
  data,
  loading,
  error,
  yAxisLabel = "Count",
  hideYAxis = false,
}: AlertsMultiLineGraphSectionProps) {
  const { isDark } = useTheme();

  // Legend toggle state: tracks which series are hidden
  // Click a legend item to hide/show it — Y-axis auto-rescales
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set());

  const handleLegendClick = useCallback((entry: any) => {
    const key = entry.dataKey ?? entry.value;
    if (!key) return;
    setHiddenSeries((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  // Zoom state
  const [isExpanded, setIsExpanded] = useState(false);
  const [refAreaLeft, setRefAreaLeft] = useState<number | null>(null);
  const [refAreaRight, setRefAreaRight] = useState<number | null>(null);
  const [zoomDomain, setZoomDomain] = useState<{ left: number; right: number } | null>(null);

  const chartData = useMemo(() => {
    if (!zoomDomain) return data.points;
    return data.points.filter(
      (d) => d.timestamp >= zoomDomain.left && d.timestamp <= zoomDomain.right
    );
  }, [data.points, zoomDomain]);

  const handleMouseDown = useCallback((e: any) => {
    if (e?.activeLabel != null) setRefAreaLeft(e.activeLabel);
  }, []);

  const handleMouseMove = useCallback(
    (e: any) => {
      if (refAreaLeft != null && e?.activeLabel != null) {
        setRefAreaRight(e.activeLabel);
      }
    },
    [refAreaLeft]
  );

  const handleMouseUp = useCallback(() => {
    if (refAreaLeft != null && refAreaRight != null) {
      const left = Math.min(refAreaLeft, refAreaRight);
      const right = Math.max(refAreaLeft, refAreaRight);
      if (right - left > 0) {
        setZoomDomain({ left, right });
      }
    }
    setRefAreaLeft(null);
    setRefAreaRight(null);
  }, [refAreaLeft, refAreaRight]);

  const handleZoomReset = useCallback(() => {
    setZoomDomain(null);
  }, []);

  // ── Shared styles ─────────────────────────────────────────────────────
  const cardBg = isDark ? "bg-gray-800 border-gray-700" : "bg-white border-gray-200";
  const headerBg = isDark ? "bg-gray-800/80" : "bg-gray-50";
  const textPrimary = isDark ? "text-gray-100" : "text-gray-900";
  const textSecondary = isDark ? "text-gray-400" : "text-gray-500";
  const axisColor = isDark ? "#6b7280" : "#9ca3af";
  const gridColor = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
  const tooltipBg = isDark ? "#1f2937" : "#ffffff";
  const tooltipBorder = isDark ? "#374151" : "#e5e7eb";

  const hasData = data.points.length > 0 && data.seriesKeys.length > 0;

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-2">
          <Loader className={`w-6 h-6 animate-spin ${isDark ? "text-blue-400" : "text-[#002244]"}`} />
          <p className={`text-xs ${textSecondary}`}>Loading data...</p>
        </div>
      );
    }

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-2 px-4">
          <AlertCircle className="w-6 h-6 text-red-400" />
          <p className="text-xs text-red-400 text-center">{error}</p>
        </div>
      );
    }

    if (!hasData) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-2">
          <p className={`text-xs ${textSecondary}`}>No data available for this time range</p>
        </div>
      );
    }

    return (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={chartData}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          margin={{ top: 8, right: 16, left: hideYAxis ? 8 : 4, bottom: 4 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={gridColor}
            horizontal={!hideYAxis}
          />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatXTick}
            stroke={axisColor}
            tick={{ fontSize: 11 }}
            minTickGap={40}
          />
          {hideYAxis ? (
            <YAxis hide domain={["dataMin - 0.5", "dataMax + 0.5"]} />
          ) : (
            <YAxis
              stroke={axisColor}
              tick={{ fontSize: 11 }}
              allowDecimals={false}
              domain={[0, "auto"]}
              label={{
                value: yAxisLabel,
                angle: -90,
                position: "insideLeft",
                style: { fontSize: 11, fill: axisColor },
                offset: 4,
              }}
            />
          )}
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              // Filter out hidden series and sort by value descending
              const visible = payload
                .filter((p: any) => !hiddenSeries.has(p.dataKey) && p.value > 0)
                .sort((a: any, b: any) => (b.value ?? 0) - (a.value ?? 0));
              const hidden = payload.filter((p: any) => !hiddenSeries.has(p.dataKey) && p.value === 0);
              const MAX_SHOW = 12;
              const shown = visible.slice(0, MAX_SHOW);
              const remaining = visible.length - MAX_SHOW + hidden.length;
              return (
                <div style={{
                  backgroundColor: tooltipBg,
                  border: `1px solid ${tooltipBorder}`,
                  borderRadius: 8,
                  fontSize: 11,
                  padding: "8px 12px",
                  maxHeight: 320,
                  overflowY: "auto",
                  maxWidth: 300,
                }}>
                  <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 12 }}>
                    {formatTooltipTime(Number(label))}
                  </div>
                  {shown.map((entry: any) => (
                    <div key={entry.dataKey} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "1px 0" }}>
                      <span style={{ color: entry.color, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 200 }}>
                        {entry.name}
                      </span>
                      <span style={{ fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                        {Math.round(entry.value)}
                      </span>
                    </div>
                  ))}
                  {remaining > 0 && (
                    <div style={{ color: isDark ? "#6b7280" : "#9ca3af", fontSize: 10, marginTop: 4 }}>
                      +{remaining} more with 0 alerts
                    </div>
                  )}
                </div>
              );
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
            iconType="square"
            iconSize={10}
            onClick={handleLegendClick}
            formatter={(value: string) => {
              const isHidden = hiddenSeries.has(value);
              return (
                <span style={{
                  color: isHidden ? (isDark ? "#6b7280" : "#9ca3af") : undefined,
                  textDecoration: isHidden ? "line-through" : "none",
                  opacity: isHidden ? 0.5 : 1,
                  cursor: "pointer",
                }}>
                  {value}
                </span>
              );
            }}
          />
          {data.seriesKeys.map((key, idx) => {
            const isHidden = hiddenSeries.has(key);
            const baseWidth = hideYAxis ? 3 : 1.5;
            return (
              <Line
                key={key}
                type={hideYAxis ? "stepAfter" : "monotone"}
                dataKey={key}
                name={key}
                stroke={getSeriesColor(idx)}
                strokeWidth={isHidden ? 0 : baseWidth}
                strokeOpacity={isHidden ? 0 : 1}
                dot={false}
                activeDot={isHidden ? false : { r: 3, strokeWidth: 0, fill: getSeriesColor(idx) }}
                connectNulls={false}
                hide={isHidden}
              />
            );
          })}
          {refAreaLeft != null && refAreaRight != null && (
            <ReferenceArea
              x1={refAreaLeft}
              x2={refAreaRight}
              strokeOpacity={0.3}
              fill={isDark ? "rgba(59,130,246,0.15)" : "rgba(0,34,68,0.08)"}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    );
  };

  const graphElement = (
    <div className={`flex flex-col rounded-lg border shadow-sm overflow-hidden ${cardBg} ${isExpanded ? "fixed inset-4 z-[150]" : "h-full"}`}>
      {/* Header */}
      <div className={`flex items-center justify-between px-4 py-2.5 border-b flex-shrink-0 ${isDark ? "border-gray-700" : "border-gray-200"} ${headerBg}`}>
        <div className="min-w-0">
          <h4 className={`text-sm font-semibold truncate ${textPrimary}`}>{title}</h4>
          {subtitle && <p className={`text-xs truncate ${textSecondary}`}>{subtitle}</p>}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {zoomDomain && (
            <button
              onClick={handleZoomReset}
              title="Reset zoom"
              className={`p-1.5 rounded-md transition-colors ${isDark ? "text-blue-300 bg-blue-500/20 hover:bg-blue-500/30" : "text-[#002244] bg-[#002244]/10 hover:bg-[#002244]/15"}`}
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={() => setIsExpanded((v) => !v)}
            title={isExpanded ? "Minimize" : "Expand"}
            className={`p-1.5 rounded-md transition-colors ${isDark ? "text-gray-400 hover:text-gray-100 hover:bg-gray-700" : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"}`}
          >
            {isExpanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Chart area */}
      <div className="flex-1 min-h-0 p-2">
        {renderContent()}
      </div>

      {/* Hint text */}
      {!loading && !error && hasData && (
        <div className={`px-4 pb-1.5 text-[10px] text-right ${textSecondary}`}>
          {zoomDomain ? "" : "Drag to zoom • "}Click legend to toggle series
        </div>
      )}
    </div>
  );

  if (isExpanded) {
    return (
      <>
        <div className="fixed inset-0 bg-black/50 z-[140]" onClick={() => setIsExpanded(false)} />
        {graphElement}
      </>
    );
  }

  return graphElement;
}
