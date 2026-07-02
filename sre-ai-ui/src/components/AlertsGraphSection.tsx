"use client";

import { useState, useCallback } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceArea,
} from "recharts";
import { ZoomOut, Maximize2, Minimize2, Loader, AlertCircle } from "lucide-react";
import { useTheme } from "@/contexts/ThemeContext";

// ─── Types ──────────────────────────────────────────────────────────────────

export interface GraphDataPoint {
  timestamp: number;   // epoch seconds
  value: number;
  label: string;       // formatted time string for x-axis
}

interface AlertsGraphSectionProps {
  title: string;
  subtitle?: string;
  data: GraphDataPoint[];
  loading: boolean;
  error: string | null;
  lineColor?: string;
  yAxisLabel?: string;
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

export function AlertsGraphSection({
  title,
  subtitle,
  data,
  loading,
  error,
  lineColor = "#3b82f6",
  yAxisLabel = "Count",
}: AlertsGraphSectionProps) {
  const { isDark } = useTheme();

  // Zoom state
  const [isExpanded, setIsExpanded] = useState(false);
  const [refAreaLeft, setRefAreaLeft] = useState<number | null>(null);
  const [refAreaRight, setRefAreaRight] = useState<number | null>(null);
  const [zoomDomain, setZoomDomain] = useState<{ left: number; right: number } | null>(null);

  const chartData = zoomDomain
    ? data.filter((d) => d.timestamp >= zoomDomain.left && d.timestamp <= zoomDomain.right)
    : data;

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

    if (data.length === 0) {
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
          margin={{ top: 8, right: 16, left: 4, bottom: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatXTick}
            stroke={axisColor}
            tick={{ fontSize: 11 }}
            minTickGap={40}
          />
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
          <Tooltip
            contentStyle={{
              backgroundColor: tooltipBg,
              border: `1px solid ${tooltipBorder}`,
              borderRadius: 8,
              fontSize: 12,
              padding: "8px 12px",
            }}
            labelFormatter={(label) => formatTooltipTime(Number(label))}
            formatter={(value) => [value, yAxisLabel]}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={lineColor}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0, fill: lineColor }}
          />
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

      {/* Drag-to-zoom hint */}
      {!loading && !error && data.length > 0 && !zoomDomain && (
        <div className={`px-4 pb-1.5 text-[10px] text-right ${textSecondary}`}>
          Drag to zoom
        </div>
      )}
    </div>
  );

  if (isExpanded) {
    return (
      <>
        {/* Backdrop */}
        <div className="fixed inset-0 bg-black/50 z-[140]" onClick={() => setIsExpanded(false)} />
        {graphElement}
      </>
    );
  }

  return graphElement;
}
