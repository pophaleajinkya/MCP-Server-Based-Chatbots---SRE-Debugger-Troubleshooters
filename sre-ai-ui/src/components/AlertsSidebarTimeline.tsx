"use client";

import { useState, useRef, useCallback, useMemo } from "react";
import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceArea,
  Cell,
} from "recharts";
import { Maximize2, Minimize2, Loader, AlertCircle } from "lucide-react";
import { useTheme } from "@/contexts/ThemeContext";
import type { AlertResultAlert } from "@/lib/api-client";

// Color palette for alert lines
const PALETTE = [
  "#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4",
  "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6", "#f59e0b",
  "#6366f1", "#84cc16", "#e11d48", "#0ea5e9",
];

interface TimelineEntry {
  x: number; // timestamp
  y: number; // alert index (row position)
  label: string;
  alertName: string;
}

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

interface AlertsSidebarTimelineProps {
  alerts: AlertResultAlert[];
  loading?: boolean;
  error?: string | null;
}

export function AlertsSidebarTimeline({ alerts, loading, error }: AlertsSidebarTimelineProps) {
  const { isDark } = useTheme();
  const [expanded, setExpanded] = useState(false);

  // Zoom state
  const [zoomLeft, setZoomLeft] = useState<number | null>(null);
  const [zoomRight, setZoomRight] = useState<number | null>(null);
  const [zoomDomain, setZoomDomain] = useState<[number, number] | null>(null);
  const isDragging = useRef(false);

  // Build timeline data: each alert becomes a horizontal band of scatter points
  const { scatterData, alertLabels, allTimestamps } = useMemo(() => {
    if (!alerts || alerts.length === 0) {
      return { scatterData: [] as TimelineEntry[], alertLabels: [] as string[], allTimestamps: [] as number[] };
    }

    const labels: string[] = [];
    const data: TimelineEntry[] = [];
    const tsSet = new Set<number>();

    alerts.forEach((alert, idx) => {
      const label = alert.alert_sla_name || alert.alertname || `Alert ${idx + 1}`;
      labels.push(label);

      if (alert.values && alert.values.length > 0) {
        for (const [ts] of alert.values) {
          tsSet.add(ts);
          data.push({
            x: ts,
            y: idx,
            label,
            alertName: alert.alertname || "Unknown",
          });
        }
      }
    });

    return {
      scatterData: data,
      alertLabels: labels,
      allTimestamps: Array.from(tsSet).sort((a, b) => a - b),
    };
  }, [alerts]);

  // Group scatter points by alert index for coloring
  const scatterByAlert = useMemo(() => {
    const groups: Map<number, TimelineEntry[]> = new Map();
    for (const point of scatterData) {
      if (!groups.has(point.y)) groups.set(point.y, []);
      groups.get(point.y)!.push(point);
    }
    return groups;
  }, [scatterData]);

  // Compute domain
  const xMin = zoomDomain?.[0] ?? (allTimestamps.length > 0 ? allTimestamps[0] : 0);
  const xMax = zoomDomain?.[1] ?? (allTimestamps.length > 0 ? allTimestamps[allTimestamps.length - 1] : 1);

  const handleMouseDown = useCallback((e: any) => {
    if (e?.activeLabel != null) {
      setZoomLeft(e.activeLabel);
      setZoomRight(null);
      isDragging.current = true;
    }
  }, []);

  const handleMouseMove = useCallback((e: any) => {
    if (isDragging.current && e?.activeLabel != null) {
      setZoomRight(e.activeLabel);
    }
  }, []);

  const handleMouseUp = useCallback(() => {
    if (zoomLeft != null && zoomRight != null && zoomLeft !== zoomRight) {
      const left = Math.min(zoomLeft, zoomRight);
      const right = Math.max(zoomLeft, zoomRight);
      setZoomDomain([left, right]);
    }
    setZoomLeft(null);
    setZoomRight(null);
    isDragging.current = false;
  }, [zoomLeft, zoomRight]);

  const resetZoom = useCallback(() => {
    setZoomDomain(null);
    setZoomLeft(null);
    setZoomRight(null);
  }, []);

  const bgColor = isDark ? "bg-[#0d1117]" : "bg-white";
  const borderColor = isDark ? "border-gray-700" : "border-gray-200";
  const textColor = isDark ? "text-gray-100" : "text-gray-900";
  const subTextColor = isDark ? "text-gray-400" : "text-gray-600";
  const gridStroke = isDark ? "#30363d" : "#e5e7eb";
  const axisColor = isDark ? "#8b949e" : "#6b7280";

  // Custom tooltip
  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload || payload.length === 0) return null;
    const point = payload[0]?.payload as TimelineEntry;
    if (!point) return null;
    return (
      <div className={`${isDark ? "bg-gray-800 border-gray-600" : "bg-white border-gray-300"} border rounded-lg shadow-lg px-3 py-2 text-xs`}>
        <p className={`font-semibold ${textColor}`}>{point.label}</p>
        <p className={subTextColor}>{formatDateTime(point.x)}</p>
        {point.alertName !== point.label && (
          <p className={subTextColor}>Alert: {point.alertName}</p>
        )}
      </div>
    );
  };

  const renderChart = (height: number) => (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart
        margin={{ top: 10, right: 20, bottom: 20, left: 10 }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke={gridStroke}
          horizontal={true}
          vertical={true}
        />
        <XAxis
          dataKey="x"
          type="number"
          domain={[xMin, xMax]}
          tickFormatter={formatTime}
          stroke={axisColor}
          tick={{ fontSize: 11, fill: axisColor }}
          scale="linear"
        />
        <YAxis
          dataKey="y"
          type="number"
          domain={[-0.5, alertLabels.length - 0.5]}
          ticks={alertLabels.map((_, i) => i)}
          tickFormatter={(val: number) => {
            const label = alertLabels[val] || "";
            return label.length > 30 ? label.slice(0, 28) + "…" : label;
          }}
          stroke={axisColor}
          tick={{ fontSize: 10, fill: axisColor }}
          width={200}
          interval={0}
        />
        <Tooltip content={<CustomTooltip />} />

        {/* Render one Scatter per alert for distinct colors */}
        {Array.from(scatterByAlert.entries()).map(([alertIdx, points]) => (
          <Scatter
            key={alertIdx}
            data={points}
            fill={PALETTE[alertIdx % PALETTE.length]}
            line={{ stroke: PALETTE[alertIdx % PALETTE.length], strokeWidth: 6 }}
            lineType="joint"
            shape="circle"
            legendType="none"
          >
            {points.map((_, i) => (
              <Cell
                key={i}
                fill={PALETTE[alertIdx % PALETTE.length]}
                r={0}
              />
            ))}
          </Scatter>
        ))}

        {/* Zoom selection area */}
        {zoomLeft != null && zoomRight != null && (
          <ReferenceArea
            x1={zoomLeft}
            x2={zoomRight}
            strokeOpacity={0.3}
            fill={isDark ? "#3b82f6" : "#002244"}
            fillOpacity={0.15}
          />
        )}
      </ScatterChart>
    </ResponsiveContainer>
  );

  // Loading state
  if (loading) {
    return (
      <div className={`${bgColor} rounded-lg border ${borderColor} p-6 h-full flex items-center justify-center`}>
        <div className="flex flex-col items-center gap-3">
          <Loader className={`w-6 h-6 animate-spin ${subTextColor}`} />
          <p className={`text-sm ${subTextColor}`}>Loading timeline...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className={`${bgColor} rounded-lg border ${borderColor} p-6 h-full flex items-center justify-center`}>
        <div className="flex flex-col items-center gap-3">
          <AlertCircle className="w-6 h-6 text-red-500" />
          <p className="text-sm text-red-500">{error}</p>
        </div>
      </div>
    );
  }

  // Empty state
  if (!alerts || alerts.length === 0) {
    return (
      <div className={`${bgColor} rounded-lg border ${borderColor} p-6 h-full flex items-center justify-center`}>
        <p className={`text-sm ${subTextColor}`}>No alerts to display on timeline</p>
      </div>
    );
  }

  // Expanded fullscreen
  if (expanded) {
    return (
      <div className="fixed inset-0 z-[150] bg-black/60 flex items-center justify-center p-6" onClick={() => setExpanded(false)}>
        <div
          className={`${isDark ? "bg-gray-900" : "bg-white"} rounded-xl shadow-2xl flex flex-col`}
          style={{ width: "95vw", height: "90vh" }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className={`flex items-center justify-between px-6 py-3 border-b ${borderColor}`}>
            <div>
              <h3 className={`text-sm font-semibold ${textColor}`}>Alert Timeline</h3>
              <p className={`text-xs ${subTextColor}`}>{alerts.length} alert{alerts.length !== 1 ? "s" : ""}</p>
            </div>
            <div className="flex items-center gap-2">
              {zoomDomain && (
                <button onClick={resetZoom} className={`text-xs px-2 py-1 rounded border ${isDark ? "border-gray-600 text-gray-300 hover:bg-gray-700" : "border-gray-300 text-gray-600 hover:bg-gray-100"}`}>
                  Reset Zoom
                </button>
              )}
              <button onClick={() => setExpanded(false)} className={`p-1.5 rounded-md transition-colors ${isDark ? "text-gray-400 hover:bg-gray-700" : "text-gray-500 hover:bg-gray-100"}`}>
                <Minimize2 className="w-4 h-4" />
              </button>
            </div>
          </div>
          <div className="flex-1 p-4">
            {renderChart(Math.max(400, alerts.length * 60 + 80))}
          </div>
        </div>
      </div>
    );
  }

  // Normal view
  const chartHeight = Math.max(250, alerts.length * 50 + 60);

  return (
    <div className={`${bgColor} rounded-lg border ${borderColor} h-full flex flex-col`}>
      <div className={`flex items-center justify-between px-4 py-2 border-b ${borderColor}`}>
        <p className={`text-xs ${subTextColor}`}>
          {alerts.length} alert{alerts.length !== 1 ? "s" : ""} • Drag to zoom
        </p>
        <div className="flex items-center gap-2">
          {zoomDomain && (
            <button onClick={resetZoom} className={`text-xs px-2 py-1 rounded border ${isDark ? "border-gray-600 text-gray-300 hover:bg-gray-700" : "border-gray-300 text-gray-600 hover:bg-gray-100"}`}>
              Reset Zoom
            </button>
          )}
          <button onClick={() => setExpanded(true)} className={`p-1 rounded-md transition-colors ${isDark ? "text-gray-400 hover:bg-gray-700" : "text-gray-500 hover:bg-gray-100"}`}>
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className={`px-4 py-2 border-b ${borderColor} flex flex-wrap gap-x-4 gap-y-1`}>
        {alertLabels.map((label, idx) => (
          <div key={idx} className="flex items-center gap-1.5">
            <span
              className="inline-block w-4 h-1.5 rounded-full"
              style={{ backgroundColor: PALETTE[idx % PALETTE.length] }}
            />
            <span className={`text-xs ${subTextColor} truncate max-w-[250px]`} title={label}>
              {label}
            </span>
          </div>
        ))}
      </div>

      <div className="flex-1 p-2 overflow-auto">
        {renderChart(chartHeight)}
      </div>
    </div>
  );
}
