"use client";

import {
  ResponsiveContainer,
  LineChart, Line,
  BarChart, Bar,
  AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";
import { TrendingUp, BarChart2, Activity } from "lucide-react";

// JSON schema agents can return inside a ```chart block
interface ChartSeries {
  key: string;
  label?: string;
  color?: string;
}

interface ChartConfig {
  type?: "line" | "bar" | "area";
  title?: string;
  xKey: string;
  yLabel?: string;
  xLabel?: string;
  height?: number;
  series: ChartSeries[];
  data: Record<string, unknown>[];
}

const DEFAULT_COLORS = [
  "#0071CE", "#FFC220", "#22c55e", "#f97316",
  "#a855f7", "#ec4899", "#14b8a6", "#f43f5e",
];

const CHART_ICONS = {
  bar: BarChart2,
  line: TrendingUp,
  area: Activity,
};

interface RechartsBlockProps {
  content: string;
}

export function RechartsBlock({ content }: RechartsBlockProps) {
  let config: ChartConfig;
  try {
    config = JSON.parse(content);
    if (!config.data || !config.series || !config.xKey) return null;
  } catch {
    return null;
  }

  const { type = "bar", title, xKey, yLabel, xLabel, height = 280, series, data } = config;
  const Icon = CHART_ICONS[type] ?? BarChart2;

  const tooltipStyle = {
    fontSize: 12,
    borderRadius: 8,
    border: "1px solid #e5e7eb",
    boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
  };

  const axisTickStyle = { fontSize: 11, fill: "#9ca3af" };

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden my-3">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-gray-100 bg-gray-50/80">
        <Icon className="w-4 h-4 text-[#0071CE]" />
        <span className="text-sm font-semibold text-gray-700">{title ?? "Chart"}</span>
        <span className="text-[10px] text-gray-400 bg-gray-200 px-1.5 py-0.5 rounded-full">
          {type} · {data.length} pts
        </span>
      </div>

      {/* Chart */}
      <div className="px-2 py-4">
        <ResponsiveContainer width="100%" height={height}>
          {type === "line" ? (
            <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
              <XAxis dataKey={xKey} tick={axisTickStyle} axisLine={false} tickLine={false} label={xLabel ? { value: xLabel, position: "insideBottom", offset: -4, fontSize: 11, fill: "#9ca3af" } : undefined} />
              <YAxis tick={axisTickStyle} axisLine={false} tickLine={false} label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", offset: 10, fontSize: 11, fill: "#9ca3af" } : undefined} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
              {series.map((s, i) => (
                <Line
                  key={s.key}
                  dataKey={s.key}
                  name={s.label ?? s.key}
                  stroke={s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              ))}
            </LineChart>
          ) : type === "area" ? (
            <AreaChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
              <XAxis dataKey={xKey} tick={axisTickStyle} axisLine={false} tickLine={false} />
              <YAxis tick={axisTickStyle} axisLine={false} tickLine={false} label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", offset: 10, fontSize: 11, fill: "#9ca3af" } : undefined} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
              {series.map((s, i) => {
                const color = s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length];
                return (
                  <Area
                    key={s.key}
                    dataKey={s.key}
                    name={s.label ?? s.key}
                    stroke={color}
                    fill={color}
                    fillOpacity={0.12}
                    strokeWidth={2}
                    dot={false}
                  />
                );
              })}
            </AreaChart>
          ) : (
            <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
              <XAxis dataKey={xKey} tick={axisTickStyle} axisLine={false} tickLine={false} />
              <YAxis tick={axisTickStyle} axisLine={false} tickLine={false} label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", offset: 10, fontSize: 11, fill: "#9ca3af" } : undefined} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#f8faff" }} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
              {series.map((s, i) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label ?? s.key}
                  fill={s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
