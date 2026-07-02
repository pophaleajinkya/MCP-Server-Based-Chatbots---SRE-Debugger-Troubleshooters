"use client";

import { useState, useEffect, useMemo, useCallback, startTransition, memo } from "react";
import { Bell, AlertCircle, Loader, RefreshCw, Info, Maximize2, X, Copy, LayoutList, BarChart2, ZoomIn, ZoomOut } from "lucide-react";
import { alertsApi, promqlApi } from "@/lib/api-client";
import type { AlertQueryResult, AlertResultAlert } from "@/lib/api-client";
import { useTheme } from "@/contexts/ThemeContext";
import { AlertsTimeline } from "@/components/AlertsTimeline";
import { AlertsGraphDashboard, type GraphDataPoint, type GraphSectionData, type MultiSeriesSectionData, type MultiSeriesGraphData } from "@/components/AlertsGraphDashboard";
import { DataTable, CellBadge, CellTruncated, CellCopyable, CellList, multiSelectFilterFn } from "@/components/ui/DataTable";
import { type ColumnDef } from "@tanstack/react-table";

type TimeUnit = "minutes" | "hours";
type TabView = "table" | "timeline";
type DensityType = "compact" | "standard" | "comfortable";
type AlertColumnKey = "alertId" | "slaName" | "startTime" | "status" | "clusterId" | "xmattersGroup" | "slackChannel" | "alertCategory" | "alertName";
interface AlertColumnConfig { key: AlertColumnKey; label: string; visible: boolean; }

const ALERT_COLUMN_DEFS: { key: AlertColumnKey; label: string; minW: string }[] = [
  { key: "alertId",        label: "Alert ID",          minW: "min-w-[140px]" },
  { key: "slaName",        label: "SLA_name",         minW: "min-w-[130px]" },
  { key: "alertCategory",  label: "Tenant",    minW: "min-w-[130px]" },
  { key: "startTime",      label: "Alert start time",  minW: "min-w-[160px]" },
  { key: "status",         label: "Status",            minW: "min-w-[80px]"  },
  { key: "clusterId",      label: "Cluster_id",        minW: "min-w-[110px]" },
  { key: "xmattersGroup",  label: "x_matters_group",   minW: "min-w-[160px]" },
  { key: "slackChannel",   label: "Slack_xmatters",    minW: "min-w-[160px]" },
  { key: "alertName",      label: "Alert name",        minW: "min-w-[200px]" },
];

const MIN_MINUTES = 5;
const MAX_HOURS   = 24;

// Alerts page specific: 360 seconds for broader time window
const STEP = "360s";
// Step size in seconds — parsed from STEP constant (e.g. "360s" → 360)
// Used as the buffer when determining alert active status
const STEP_SECONDS = parseInt(STEP) || 60;

// PromQL Section 1 query — uses max_over_time to avoid undercounting short-lived alerts
const SECTION1_PROMQL =
  'sum(max_over_time(ALERTS{tool="juno", alert_team="intl_sre_golden_signals", alertstate="firing"}[1m]))';

// PromQL Section 2 query — same but grouped by alert_type
const SECTION2_PROMQL =
  'sum by (alert_type) (max_over_time(ALERTS{tool="juno", alert_team="intl_sre_golden_signals", alertstate="firing"}[1m]))';

// PromQL Section 3 query — grouped by both alert_type and alert_sla_name
const SECTION3_PROMQL =
  'sum by (alert_type, alert_sla_name) (max_over_time(ALERTS{tool="juno", alert_team="intl_sre_golden_signals", alertstate="firing"}[1m]))';

function computeGraphStep(startSec: number, endSec: number): string {
  const range = endSec - startSec;
  if (range <= 3600) return "60s";
  if (range <= 14400) return "300s";
  if (range <= 43200) return "900s";
  return "3600s";
}

function parsePromQLToGraphData(result: any): GraphDataPoint[] {
  const points: GraphDataPoint[] = [];
  if (result?.data?.result && result.data.result.length > 0) {
    for (const series of result.data.result) {
      for (const [ts, val] of series.values as [number, string][]) {
        points.push({
          timestamp: ts,
          value: parseFloat(val) || 0,
          label: new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        });
      }
    }
  }
  points.sort((a, b) => a.timestamp - b.timestamp);
  return points.filter((p, i, arr) => i === 0 || p.timestamp !== arr[i - 1].timestamp);
}

/**
 * Parse a PromQL "count by (label)" response into multi-series format.
 * Each result series has metric.alert_type (or the groupBy label) and values.
 * We pivot into { timestamp, seriesA: val, seriesB: val, ... } rows for Recharts.
 */
function parsePromQLToMultiSeries(result: any, groupByKey: string = "alert_type"): MultiSeriesGraphData {
  const seriesKeysSet = new Set<string>();
  // Map: timestamp → { key: value }
  const tsMap = new Map<number, Record<string, number>>();

  if (result?.data?.result && result.data.result.length > 0) {
    for (const series of result.data.result) {
      const seriesName: string = series.metric?.[groupByKey] || "unknown";
      seriesKeysSet.add(seriesName);
      for (const [ts, val] of series.values as [number, string][]) {
        if (!tsMap.has(ts)) tsMap.set(ts, {});
        tsMap.get(ts)![seriesName] = parseFloat(val) || 0;
      }
    }
  }

  const seriesKeys = Array.from(seriesKeysSet).sort();
  const timestamps = Array.from(tsMap.keys()).sort((a, b) => a - b);

  const points = timestamps.map((ts) => {
    const row: any = { timestamp: ts };
    const vals = tsMap.get(ts)!;
    for (const key of seriesKeys) {
      row[key] = vals[key] ?? 0;
    }
    return row;
  });

  return { points, seriesKeys };
}

/**
 * Parse a PromQL "count by (key1, key2)" response into multi-series format.
 * Builds a composite series key from multiple metric labels, e.g. "cosmos — cassandraDB_cpu_spike".
 */
function parsePromQLToCompositeMultiSeries(
  result: any,
  groupByKeys: string[]
): MultiSeriesGraphData {
  const seriesKeysSet = new Set<string>();
  const tsMap = new Map<number, Record<string, number>>();

  if (result?.data?.result && result.data.result.length > 0) {
    for (const series of result.data.result) {
      // Build composite key: "alert_type — alert_sla_name"
      const parts = groupByKeys.map((k) => series.metric?.[k] || "unknown");
      const seriesName = parts.join(" — ");
      seriesKeysSet.add(seriesName);
      for (const [ts, val] of series.values as [number, string][]) {
        if (!tsMap.has(ts)) tsMap.set(ts, {});
        tsMap.get(ts)![seriesName] = parseFloat(val) || 0;
      }
    }
  }

  const seriesKeys = Array.from(seriesKeysSet).sort();
  const timestamps = Array.from(tsMap.keys()).sort((a, b) => a - b);

  const points = timestamps.map((ts) => {
    const row: any = { timestamp: ts };
    const vals = tsMap.get(ts)!;
    for (const key of seriesKeys) {
      row[key] = vals[key] ?? 0;
    }
    return row;
  });

  return { points, seriesKeys };
}

/**
 * Determine if an alert is currently active.
 *
 * @param alert       — the alert row from PromQL
 * @param refreshEpoch — epoch seconds captured when the query was triggered
 * @param stepSeconds  — PromQL step size in seconds (parsed from STEP constant)
 *
 * Logic: An alert that is still firing will have its last datapoint timestamp
 * within one step of the query end time. If (lastTs + step) >= refreshEpoch
 * the alert was still firing when we queried.
 */
function isAlertActive(alert: AlertResultAlert, refreshEpoch: number, stepSeconds: number): boolean {
  // Guard: no values or empty array → inactive
  if (!alert.values || alert.values.length === 0) return false;

  const lastEntry = alert.values[alert.values.length - 1];
  const lastTs = lastEntry?.[0];

  // Guard: non-numeric or missing timestamp → inactive
  if (lastTs == null || typeof lastTs !== "number" || isNaN(lastTs)) return false;

  // Guard: timestamp looks like milliseconds (>year 2100 in seconds) → normalize
  const normalizedTs = lastTs > 9999999999 ? Math.floor(lastTs / 1000) : lastTs;

  return (normalizedTs + stepSeconds) >= refreshEpoch;
}

function formatTimestamp(ts: number | null | undefined): string {
  if (ts == null) return "-";
  return new Date(ts * 1000).toLocaleString();
}

function formatRelativeTime(ts: number): string {
  const diffSecs = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (diffSecs < 60) return `${diffSecs} sec ago`;
  if (diffSecs < 3600) {
    const mins = Math.floor(diffSecs / 60);
    return `${mins} min ago`;
  }
  if (diffSecs < 86400) {
    const hrs = Math.floor(diffSecs / 3600);
    return `${hrs} hr${hrs !== 1 ? "s" : ""} ago`;
  }
  const days = Math.floor(diffSecs / 86400);
  return `${days} day${days !== 1 ? "s" : ""} ago`;
}

function AlertInfoDialog({
  message,
  onClose,
  isDark,
}: {
  message: string;
  onClose: () => void;
  isDark: boolean;
}) {
  return (
    <div
      className="fixed inset-0 bg-black/50 z-[200] flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className={`rounded-lg shadow-2xl max-w-lg w-full mx-4 p-6 ${isDark ? "bg-gray-800" : "bg-white"}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className={`text-base font-semibold ${isDark ? "text-gray-100" : "text-gray-900"}`}>Alert name</h3>
          <button
            onClick={onClose}
            className={`transition-colors ${isDark ? "text-gray-400 hover:text-gray-100" : "text-gray-500 hover:text-gray-900"}`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <p className={`text-sm break-words leading-relaxed ${isDark ? "text-gray-300" : "text-gray-700"}`}>{message}</p>
      </div>
    </div>
  );
}

function AlertDetailsDialog({
  alert,
  onClose,
  isDark,
}: {
  alert: AlertResultAlert;
  onClose: () => void;
  isDark: boolean;
}) {
  // Key fields shown prominently at the top
  const KEY_FIELDS = [
    "alertname", "alert_sla_name", "alert_type", "alertstate", "severity",
    "namespace", "app_name", "cluster", "cluster_id",
    "alert_team", "alert_owner_category", "alert_component",
    "mms_slack_channel", "mms_xmatters_group",
  ];
  const keyFieldSet = new Set(KEY_FIELDS);

  const allLabels = alert.labels || {};
  const keyLabels = Object.fromEntries(
    KEY_FIELDS.filter(k => allLabels[k] != null && allLabels[k] !== "").map(k => [k, allLabels[k]])
  );
  const additionalLabels = Object.fromEntries(
    Object.entries(allLabels).filter(([k]) => !keyFieldSet.has(k) && k !== "__name__" && k !== "")
  );

  const hasKeyLabels = Object.keys(keyLabels).length > 0;
  const hasAdditionalLabels = Object.keys(additionalLabels).length > 0;
  const hasValues = alert.values && alert.values.length > 0;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className={`${isDark ? "bg-[#0d1117]" : "bg-white"} rounded-lg shadow-xl w-full max-w-4xl max-h-[85vh] overflow-auto`} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className={`flex items-center justify-between px-6 py-4 border-b ${isDark ? "border-[#30363d] bg-[#002244]" : "border-gray-200 bg-[#002244]"}`}>
          <div>
            <h2 className="text-lg font-semibold text-white">Alert Details</h2>
            <p className="text-sm text-white/70">{alert.alertname || alert.alert_id || "Unknown Alert"}</p>
          </div>
          <button onClick={onClose} className="text-white/80 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Values Data */}
          {hasValues && (
            <div>
              <h3 className={`text-xs font-semibold ${isDark ? "text-gray-400" : "text-gray-400"} uppercase tracking-wider mb-4`}>Time-Series Values ({alert.values?.length ?? 0} points)</h3>
              <div className={`${isDark ? "bg-[#0d1117] border-[#30363d]" : "bg-gray-50 border-gray-200"} border rounded p-4 max-h-64 overflow-y-auto`}>
                <table className="w-full text-xs">
                  <thead>
                    <tr className={`border-b ${isDark ? "border-[#30363d]" : "border-gray-200"}`}>
                      <th className={`text-left px-2 py-2 font-semibold ${isDark ? "text-gray-400" : "text-gray-600"}`}>Timestamp</th>
                      <th className={`text-left px-2 py-2 font-semibold ${isDark ? "text-gray-400" : "text-gray-600"}`}>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alert.values?.map((value, idx) => (
                      <tr key={idx} className={`border-b ${isDark ? "border-[#30363d]" : "border-gray-200"} ${idx % 2 === 0 ? (isDark ? "bg-[#161b22]" : "bg-white") : (isDark ? "bg-[#0d1117]" : "bg-gray-50")}`}>
                        <td className={`px-2 py-1.5 font-mono ${isDark ? "text-gray-300" : "text-gray-700"}`}>
                          {new Date(value[0] * 1000).toLocaleString()}
                        </td>
                        <td className={`px-2 py-1.5 font-mono ${isDark ? "text-gray-300" : "text-gray-700"}`}>
                          {value[1]}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Key Fields */}
          {hasKeyLabels && (
            <div>
              <h3 className={`text-xs font-semibold ${isDark ? "text-gray-400" : "text-gray-400"} uppercase tracking-wider mb-4`}>Key Fields</h3>
              <div className="grid grid-cols-3 gap-4">
                {Object.entries(keyLabels).map(([key, value]) => (
                  <div key={key}>
                    <label className={`text-xs ${isDark ? "text-gray-400" : "text-gray-500"}`}>{key}</label>
                    <p className={`text-sm font-mono break-words mt-1 ${isDark ? "text-gray-100" : "text-gray-900"}`}>{value}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Additional Labels — all remaining tags */}
          {hasAdditionalLabels && (
            <div>
              <h3 className={`text-xs font-semibold ${isDark ? "text-gray-400" : "text-gray-400"} uppercase tracking-wider mb-4`}>All Labels ({Object.keys(additionalLabels).length})</h3>
              <div className={`${isDark ? "bg-[#0d1117] border-[#30363d]" : "bg-gray-50 border-gray-200"} border rounded p-4 max-h-64 overflow-y-auto`}>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                  {Object.entries(additionalLabels).sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => (
                    <div key={key} className="flex items-start gap-2 text-xs">
                      <span className={`font-medium flex-shrink-0 ${isDark ? "text-gray-400" : "text-gray-500"}`}>{key}:</span>
                      <span className={`font-mono break-all ${isDark ? "text-gray-200" : "text-gray-800"}`}>{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {!hasKeyLabels && !hasAdditionalLabels && !hasValues && (
            <div className={`text-sm text-center py-8 ${isDark ? "text-gray-400" : "text-gray-500"}`}>
              No additional data to display
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={`px-6 py-4 border-t ${isDark ? "border-[#30363d] bg-[#0d1117]" : "border-gray-200 bg-gray-50"} flex justify-end`}>
          <button onClick={onClose} className="px-4 py-2 bg-[#002244] text-white rounded hover:bg-[#003366] transition-colors">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function TabBar({ activeTab, onTabChange }: { activeTab: TabView; onTabChange: (t: TabView) => void }) {
  const { isDark } = useTheme();
  return (
    <div className={`flex gap-0.5 rounded-md p-0.5 ${isDark ? "bg-[#21262d]" : "bg-gray-100"}`}>
      <button
        onClick={() => onTabChange("table")}
        className={`flex items-center gap-1.5 px-2.5 h-6 rounded text-xs font-medium transition-all ${
          activeTab === "table"
            ? isDark ? "bg-[#30363d] text-white shadow-sm" : "bg-white text-[#002244] shadow-sm"
            : isDark ? "text-gray-400 hover:text-gray-100" : "text-gray-500 hover:text-gray-800"
        }`}
      >
        <LayoutList className="w-3.5 h-3.5" />
        Table
      </button>
      <button
        onClick={() => onTabChange("timeline")}
        className={`flex items-center gap-1.5 px-2.5 h-6 rounded text-xs font-medium transition-all ${
          activeTab === "timeline"
            ? isDark ? "bg-[#30363d] text-white shadow-sm" : "bg-white text-[#002244] shadow-sm"
            : isDark ? "text-gray-400 hover:text-gray-100" : "text-gray-500 hover:text-gray-800"
        }`}
      >
        <BarChart2 className="w-3.5 h-3.5" />
        Timeline
      </button>
    </div>
  );
}

const AlertsTable = memo(function AlertsTable({
  alerts,
  onInfoClick,
  visibleCols,
  density = "standard",
  getAlertActive,
  sort,
  onSort,
  onAlertDetailClick,
}: {
  alerts: AlertResultAlert[];
  onInfoClick: (msg: string) => void;
  visibleCols?: Set<AlertColumnKey>;
  density?: DensityType;
  getAlertActive: (alert: AlertResultAlert) => boolean;
  sort: { key: AlertColumnKey | null; direction: "asc" | "desc" };
  onSort: (sort: { key: AlertColumnKey | null; direction: "asc" | "desc" }) => void;
  onAlertDetailClick?: (alert: AlertResultAlert) => void;
}) {
  const cellPy = density === "compact" ? "py-1.5" : density === "comfortable" ? "py-4" : "py-3";
  const vis = (key: AlertColumnKey) => !visibleCols || visibleCols.has(key);
  const visibleDefs = ALERT_COLUMN_DEFS.filter(c => vis(c.key));

  return (
    <table className="w-full font-sans">
      <thead className="sticky top-0 z-10">
        <tr className="bg-[#002244] dark:bg-gray-800">
          {visibleDefs.map((col, i) => (
            <th
              key={col.key}
              scope="col"
              role="columnheader"
              aria-label={col.label}
              onClick={() =>
                onSort({
                  key: col.key,
                  direction: sort.key === col.key && sort.direction === "asc" ? "desc" : "asc",
                })
              }
              className={`px-3 py-2 text-[10px] font-semibold tracking-wide text-[#90EE90] dark:text-blue-300 cursor-pointer select-none whitespace-nowrap hover:bg-[#003366] transition-colors ${col.minW} ${
                i < visibleDefs.length - 1 ? "border-r border-white/15 dark:border-white/10" : ""
              }`}
            >
              <span className="inline-flex items-center gap-1 text-[#90EE90] dark:text-blue-300">
                {col.label}
                {sort.key === col.key ? (
                  <span className="text-xs">{sort.direction === "asc" ? "▲" : "▼"}</span>
                ) : null}
              </span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {alerts.map((alert, idx) => {
          const active = getAlertActive(alert);
          const startTs = alert.episode_start_ts ?? alert.values?.[0]?.[0] ?? null;
          return (
            <tr
              key={`${alert.alert_id || "alert"}-${idx}`}
              className={`col-separated border-b transition-[box-shadow]
                border-gray-100 dark:border-gray-700
                hover:bg-[#f5f9ff] dark:hover:bg-gray-700/60
                hover:shadow-[inset_4px_0_0_#002244] dark:hover:shadow-[inset_4px_0_0_#3b82f6]
                ${idx % 2 === 1 ? "bg-[#fafbfc] dark:bg-gray-800/50" : "bg-white dark:bg-gray-900"}`}
            >
              {vis("alertId") && (
                <td className={`px-5 ${cellPy} text-sm text-[#1a1a1a] dark:text-gray-200`}>
                  {alert.alert_id ? (
                    <div className="flex items-center gap-1.5">
                      <span className="truncate" title={alert.alert_id}>{alert.alert_id}</span>
                      <button onClick={() => navigator.clipboard.writeText(alert.alert_id!)} className="flex-shrink-0 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400" title="Copy Alert ID">
                        <Copy className="w-3 h-3" />
                      </button>
                      {onAlertDetailClick && (
                        <button onClick={() => onAlertDetailClick(alert)} className="flex-shrink-0 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400" title="View alert details">
                          <Info className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                  ) : "-"}
                </td>
              )}
              {vis("slaName") && (
                <td className={`px-5 ${cellPy} text-sm text-[#1a1a1a] dark:text-gray-200`}>{alert.alert_sla_name || "-"}</td>
              )}
              {vis("startTime") && (
                <td className={`px-5 ${cellPy} text-sm text-[#1a1a1a] dark:text-gray-200`}>
                  {startTs != null ? (
                    <div className="flex flex-col gap-0.5">
                      <span>{formatTimestamp(startTs)}</span>
                      <span className="text-xs text-gray-400 dark:text-gray-500">({formatRelativeTime(startTs)})</span>
                    </div>
                  ) : "-"}
                </td>
              )}
              {vis("status") && (
                <td className={`px-5 ${cellPy} text-sm`}>
                  <span className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${
                    active ? "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300"
                           : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                  }`}>
                    {active ? "Active" : "Inactive"}
                  </span>
                </td>
              )}
              {vis("clusterId") && (
                <td className={`px-5 ${cellPy} text-sm text-[#1a1a1a] dark:text-gray-200`}>
                  {(() => {
                    const cid = alert.cluster ?? alert.labels?.cluster_id ?? null;
                    return cid ? (
                      <div className="flex items-center justify-between">
                        <span className="truncate" title={cid}>{cid}</span>
                        <button onClick={() => navigator.clipboard.writeText(cid)} className="flex-shrink-0 ml-2 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400" title="Copy Cluster_id">
                          <Copy className="w-3 h-3" />
                        </button>
                      </div>
                    ) : "-";
                  })()}
                </td>
              )}
              {vis("xmattersGroup") && (
                <td className={`px-5 ${cellPy} text-sm text-[#1a1a1a] dark:text-gray-200`}>
                  {alert.mms_xmatters_group ? (
                    <div className="flex items-center justify-between">
                      <span className="truncate" title={alert.mms_xmatters_group}>{alert.mms_xmatters_group}</span>
                      <button onClick={() => navigator.clipboard.writeText(alert.mms_xmatters_group!)} className="flex-shrink-0 ml-2 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400" title="Copy x_matters_group">
                        <Copy className="w-3 h-3" />
                      </button>
                    </div>
                  ) : "-"}
                </td>
              )}
              {vis("slackChannel") && (
                <td className={`px-5 ${cellPy} text-sm text-[#1a1a1a] dark:text-gray-200`}>
                  {alert.mms_slack_channel ? (
                    <div className="flex items-center justify-between">
                      <span className="truncate" title={alert.mms_slack_channel}>{alert.mms_slack_channel}</span>
                      <button onClick={() => navigator.clipboard.writeText(alert.mms_slack_channel!)} className="flex-shrink-0 ml-2 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400" title="Copy Slack_xmatters">
                        <Copy className="w-3 h-3" />
                      </button>
                    </div>
                  ) : "-"}
                </td>
              )}
              {vis("alertCategory") && (
                <td className={`px-5 ${cellPy} text-sm text-[#1a1a1a] dark:text-gray-200`}>{alert.alert_owner_category || "-"}</td>
              )}
              {vis("alertName") && (
                <td className={`px-5 ${cellPy} text-sm text-[#1a1a1a] dark:text-gray-200`}>
                  <div className="flex items-center gap-1.5">
                    <span className="truncate max-w-[170px]" title={alert.alertname || undefined}>{alert.alertname || "-"}</span>
                    {alert.alertname && (
                      <button onClick={() => onInfoClick(alert.alertname!)} className="flex-shrink-0 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400" title="View full alert name">
                        <Info className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
});

function ExpandedView({
  alerts,
  activeAlerts,
  alertCount,
  timeValue,
  timeUnit,
  timeStart,
  timeEnd,
  onTimeValueChange,
  onUnitChange,
  loading,
  refreshing,
  onRefresh,
  onClose,
  onInfoClick,
  isDark,
  activeTab,
  onTabChange,
  onSubmit,
  getAlertActive,
  sort,
  onSort,
  onAlertDetailClick,
  graphSection1,
  graphSection2,
  graphSection3,
}: {
  alerts: AlertResultAlert[];
  activeAlerts: AlertResultAlert[];
  alertCount: number;
  timeValue: number;
  timeUnit: TimeUnit;
  timeStart: number;
  timeEnd: number;
  onTimeValueChange: (raw: number) => void;
  onUnitChange: (unit: TimeUnit) => void;
  loading: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onClose: () => void;
  onInfoClick: (msg: string) => void;
  isDark: boolean;
  activeTab: TabView;
  onTabChange: (t: TabView) => void;
  onSubmit: () => void;
  getAlertActive: (alert: AlertResultAlert) => boolean;
  sort: { key: AlertColumnKey | null; direction: "asc" | "desc" };
  onSort: (state: { key: AlertColumnKey | null; direction: "asc" | "desc" }) => void;
  onAlertDetailClick?: (alert: AlertResultAlert) => void;
  graphSection1: GraphSectionData;
  graphSection2: MultiSeriesSectionData;
  graphSection3: MultiSeriesSectionData;
}) {
  const [isZoomed, setIsZoomed] = useState(false);

  return (
    <div
      className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className={`rounded-xl shadow-2xl flex flex-col ${isDark ? "bg-gray-900" : "bg-white"}`}
        style={{ width: "95vw", height: "90vh" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className={`flex items-center justify-between px-6 py-4 border-b rounded-t-xl flex-shrink-0 bg-[#002244] ${isDark ? "border-gray-700" : "border-gray-200"}`}>
          <div>
            <h2 className="text-lg font-semibold text-white">Alerts</h2>
            <p className="text-sm text-white/70">
              {alertCount} alert{alertCount !== 1 ? "s" : ""}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Time frame filter */}
            <div className="flex items-center gap-1.5">
              <label className="text-xs font-medium text-white/70 whitespace-nowrap">Time frame:</label>
              <input
                type="number"
                value={timeValue}
                min={timeUnit === "hours" ? 1 : MIN_MINUTES}
                max={timeUnit === "hours" ? MAX_HOURS : MAX_HOURS * 60}
                onChange={(e) => onTimeValueChange(Number(e.target.value))}
                aria-label="Time frame value"
                className="text-xs border border-white/30 rounded px-2 py-1 bg-white/10 text-white w-14 text-center focus:outline-none focus:ring-1 focus:ring-white/50"
              />
              <select
                value={timeUnit}
                onChange={(e) => onUnitChange(e.target.value as TimeUnit)}
                aria-label="Time frame unit"
                className="text-xs border border-white/30 rounded px-2 py-1 bg-white/10 text-white focus:outline-none focus:ring-1 focus:ring-white/50"
              >
                <option value="minutes" className="text-gray-900 bg-white">Minutes</option>
                <option value="hours" className="text-gray-900 bg-white">Hours</option>
              </select>
              <button
                onClick={onSubmit}
                disabled={loading}
                className="text-xs px-2.5 py-1 rounded border border-white/40 text-white/90 hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
              >
                Apply
              </button>
            </div>
            <button
              onClick={onRefresh}
              disabled={loading || refreshing}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-white/30 text-white/80 hover:text-white hover:border-white/60 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Refresh alerts"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <button
              onClick={onClose}
              className="text-white/80 hover:text-white transition-colors"
              title="Close expanded view"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Tab bar */}
        <div className={`px-6 py-3 border-b flex-shrink-0 flex items-center gap-2 ${isDark ? "bg-gray-800 border-gray-700" : "bg-gray-50 border-gray-200"}`}>
          <TabBar activeTab={activeTab} onTabChange={(t) => { onTabChange(t); if (t === "table") setIsZoomed(false); }} />
          {activeTab === "timeline" && (
            <button
              onClick={() => setIsZoomed(v => !v)}
              title={isZoomed ? "Exit zoom" : "Zoom timeline"}
              className={`p-1.5 rounded-md transition-colors ${
                isZoomed
                  ? isDark ? "bg-blue-500/20 text-blue-300" : "bg-[#002244]/10 text-[#002244]"
                  : isDark ? "text-gray-400 hover:text-gray-100 hover:bg-gray-700" : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"
              }`}
            >
              {isZoomed ? <ZoomOut className="w-4 h-4" /> : <ZoomIn className="w-4 h-4" />}
            </button>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto">
          {activeTab === "table" ? (
            <AlertsTable alerts={alerts} onInfoClick={onInfoClick} getAlertActive={getAlertActive} sort={sort} onSort={onSort} onAlertDetailClick={onAlertDetailClick} />
          ) : (
            <AlertsGraphDashboard section1={graphSection1} section2={graphSection2} section3={graphSection3} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Alerts cache — 10 minute client-side cache ─────────────────────────────
const ALERTS_CACHE_DURATION = 10 * 60 * 1000; // 10 minutes
interface AlertsCacheData {
  alerts: AlertQueryResult;
  s1: GraphDataPoint[];
  s2: MultiSeriesGraphData;
  s3: MultiSeriesGraphData;
  timeWindow: number;
  timestamp: number;
}
let alertsCache: AlertsCacheData | null = null;

/** Reset alerts cache — for tests */
export function _resetAlertsCache() { alertsCache = null; }

// Expose cache to browser console for debugging — window.__alertsCache
if (typeof window !== "undefined") {
  Object.defineProperty(window, "__alertsCache", { get: () => alertsCache, configurable: true });
}

function formatTimeAgo(epochSec: number): string {
  const diff = Math.floor(Date.now() / 1000) - epochSec;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function AlertsView() {
  const { isDark } = useTheme();
  const [alerts, setAlerts] = useState<AlertQueryResult | null>(() => alertsCache?.alerts ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [selectedAlert, setSelectedAlert] = useState<AlertResultAlert | null>(null);
  const [expandedView, setExpandedView] = useState(false);
  // Epoch (seconds) captured at query time — used to determine alert active/inactive status
  const [refreshEpoch, setRefreshEpoch] = useState<number>(Math.floor(Date.now() / 1000));
  // Draft = what user is typing; committed = last fetched
  const [draftValue, setDraftValue] = useState(1);
  const [draftUnit, setDraftUnit] = useState<TimeUnit>("hours");
  const [timeValue, setTimeValue] = useState(1);
  const [timeUnit, setTimeUnit] = useState<TimeUnit>("hours");
  const [activeTab, setActiveTab] = useState<TabView>("table");
  const [isTimelineZoomed, setIsTimelineZoomed] = useState(false);
  // Graph section data — fetched alongside alerts on Apply/Refresh, cached across tab switches
  const [s1Data, setS1Data] = useState<GraphDataPoint[]>(() => alertsCache?.s1 ?? []);
  const [s1Loading, setS1Loading] = useState(false);
  const [s1Error, setS1Error] = useState<string | null>(null);
  const [s2Data, setS2Data] = useState<MultiSeriesGraphData>(() => alertsCache?.s2 ?? { points: [], seriesKeys: [] });
  const [s2Loading, setS2Loading] = useState(false);
  const [s2Error, setS2Error] = useState<string | null>(null);
  const [s3Data, setS3Data] = useState<MultiSeriesGraphData>(() => alertsCache?.s3 ?? { points: [], seriesKeys: [] });
  const [s3Loading, setS3Loading] = useState(false);
  const [s3Error, setS3Error] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: AlertColumnKey | null; direction: "asc" | "desc" }>({
    key: "startTime",
    direction: "desc",
  });
  // Committed window (used for timeline axis + fetch)
  const timeWindow = Math.min(
    MAX_HOURS * 3600,
    Math.max(MIN_MINUTES * 60, timeUnit === "hours" ? timeValue * 3600 : timeValue * 60)
  );

  const timeLabel = timeUnit === "hours"
    ? `${timeValue} hr${timeValue !== 1 ? "s" : ""}`
    : `${timeValue} min`;

  const timeEnd = Math.floor(Date.now() / 1000);
  const timeStart = timeEnd - timeWindow;

  const handleDraftValueChange = (raw: number) => {
    const max = draftUnit === "hours" ? MAX_HOURS : MAX_HOURS * 60;
    const min = draftUnit === "hours" ? 1 : MIN_MINUTES;
    setDraftValue(Math.min(max, Math.max(min, raw || min)));
  };

  const handleDraftUnitChange = (unit: TimeUnit) => {
    if (unit === "hours" && draftUnit === "minutes") {
      setDraftValue(Math.max(1, Math.min(MAX_HOURS, Math.round(draftValue / 60))));
    } else if (unit === "minutes" && draftUnit === "hours") {
      setDraftValue(Math.min(MAX_HOURS * 60, Math.max(MIN_MINUTES, draftValue * 60)));
    }
    setDraftUnit(unit);
  };

  const handleSubmit = () => {
    const w = Math.min(MAX_HOURS * 3600, Math.max(MIN_MINUTES * 60,
      draftUnit === "hours" ? draftValue * 3600 : draftValue * 60));
    setTimeValue(draftValue);
    setTimeUnit(draftUnit);
    fetchAllAlerts(w);
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    // If we have fresh cache, skip the API calls — just show cached data
    if (alertsCache && (Date.now() - alertsCache.timestamp) < ALERTS_CACHE_DURATION) {
      // Restore refreshEpoch from cache timestamp (convert ms → seconds)
      setRefreshEpoch(Math.floor(alertsCache.timestamp / 1000));
      setLoading(false);
      return;
    }
    fetchAllAlerts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchAllAlerts = async (windowSecs?: number) => {
    const w = windowSecs ?? timeWindow;
    setLoading(true);
    setError(null);
    setS1Loading(true);
    setS1Error(null);
    setS2Loading(true);
    setS2Error(null);
    setS3Loading(true);
    setS3Error(null);
    try {
      const now = Math.floor(Date.now() / 1000);
      const startEpoch = String(now - w);
      const endEpoch = String(now);
      const graphStep = computeGraphStep(now - w, now);

      // Capture epoch at query time — used to determine active/inactive status
      setRefreshEpoch(now);

      // 1. Fetch alerts table data first (highest priority) — render table immediately
      const result = await alertsApi.query({ start: startEpoch, end: endEpoch, step: STEP });
      setAlerts(result);
      setLoading(false);

      // 2. Fire graph calls in background — don't block table rendering
      const fetchGraphs = async () => {
        // Section 1
        const s1Result = await promqlApi.queryRange({
          promql: SECTION1_PROMQL,
          start: startEpoch,
          end: endEpoch,
          step: graphStep,
        }).catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : "Failed to fetch graph data";
          setS1Error(msg);
          console.error("[AlertsView] Section 1 graph error:", err);
          return null;
        });
        if (s1Result) setS1Data(parsePromQLToGraphData(s1Result));
        setS1Loading(false);

        // Section 2
        const s2Result = await promqlApi.queryRange({
          promql: SECTION2_PROMQL,
          start: startEpoch,
          end: endEpoch,
          step: graphStep,
        }).catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : "Failed to fetch graph data";
          setS2Error(msg);
          console.error("[AlertsView] Section 2 graph error:", err);
          return null;
        });
        if (s2Result) setS2Data(parsePromQLToMultiSeries(s2Result, "alert_type"));
        setS2Loading(false);

        // Section 3 — small delay to prevent backend AsyncRequestTimeoutException
        await new Promise((resolve) => setTimeout(resolve, 1000));

        const s3Result = await promqlApi.queryRange({
          promql: SECTION3_PROMQL,
          start: startEpoch,
          end: endEpoch,
          step: graphStep,
        }).catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : "Failed to fetch graph data";
          setS3Error(msg);
          console.error("[AlertsView] Section 3 graph error:", err);
          return null;
        });

        const parsedS3 = s3Result ? parsePromQLToCompositeMultiSeries(s3Result, ["alert_type", "alert_sla_name"]) : s3Data;
        if (s3Result) setS3Data(parsedS3);

        // Save all fetched data to the 10-minute client-side cache
        alertsCache = {
          alerts: result,
          s1: s1Result ? parsePromQLToGraphData(s1Result) : s1Data,
          s2: s2Result ? parsePromQLToMultiSeries(s2Result, "alert_type") : s2Data,
          s3: parsedS3,
          timeWindow: w,
          timestamp: Date.now(),
        };
      };

      // Don't await — let graphs load independently while table is already visible
      fetchGraphs().catch(console.error);
    } catch (err) {
      const rawMessage = err instanceof Error ? err.message : "Failed to fetch alerts";
      const friendlyMessage =
        /50[0234]/.test(rawMessage) || rawMessage.includes("Server Components render") || rawMessage.includes("Internal Server Error")
          ? "The alerts service is temporarily unavailable. Please try again in a moment."
          : rawMessage;
      setError(friendlyMessage);
      setLoading(false);
      // If table fetch failed, clear graph loading too since fetchGraphs won't run
      setS1Loading(false);
      setS2Loading(false);
      setS3Loading(false);
      console.error("Error fetching alerts:", err);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchAllAlerts();
    setRefreshing(false);
  };

  // Stable ref that updates when refreshEpoch changes — forces column re-creation
  const getAlertActiveStatus = useCallback((alert: AlertResultAlert): boolean => {
    return isAlertActive(alert, refreshEpoch, STEP_SECONDS);
  }, [refreshEpoch]);

  const alertListRaw = useMemo(
    () => Array.isArray(alerts?.alerts) ? alerts!.alerts : [],
    [alerts]
  );

  // Pre-compute active status INTO each row so TanStack Table's row-value cache
  // invalidates when refreshEpoch changes (new object refs = cache miss).
  const alertList = useMemo(
    () => alertListRaw.map(a => ({ ...a, _isActive: isAlertActive(a, refreshEpoch, STEP_SECONDS) })),
    [alertListRaw, refreshEpoch]
  );

  // Timeline always shows only active alerts — memoized to avoid new ref on every render
  const activeAlerts = useMemo(() => alertList.filter(a => a._isActive), [alertList]);

  const alertColumns = useMemo<ColumnDef<AlertResultAlert, unknown>[]>(() => [
    // Alert ID — hidden by default, user can enable via Columns toggle
    { id: "alertId", accessorFn: (row) => row.alert_id || "", header: "Alert ID", size: 180, filterFn: "includesString", meta: { filterType: "text" }, cell: ({ getValue }) => <CellCopyable text={getValue() as string} /> },
    // SLA Name
    { id: "slaName", accessorFn: (row) => row.alert_sla_name || row.labels?.alert_sla_name || "", header: "SLA Name", size: 200, filterFn: "includesString", meta: { filterType: "text" }, cell: ({ getValue }) => <CellTruncated text={getValue() as string} /> },
    // Tenant (3rd visible column)
    { id: "alertCategory", accessorFn: (row) => row.labels?.alert_type || row.alert_type || "", header: "Tenant", size: 100, filterFn: multiSelectFilterFn as never, meta: { filterType: "facet" }, cell: ({ getValue }) => { const v = getValue() as string; return v ? <CellBadge variant="purple">{v}</CellBadge> : <span className="text-gray-400">&mdash;</span>; } },
    // Alert Details — name + info icon to open full details dialog
    { id: "alertName", accessorFn: (row) => row.alertname || row.labels?.alertname || "", header: "Alert Details", size: 250, filterFn: "includesString", meta: { filterType: "text" }, cell: ({ getValue, row }) => (
      <div className="flex items-center gap-1.5">
        <span className="truncate flex-1" title={getValue() as string}>{getValue() as string || "—"}</span>
        <button onClick={(e) => { e.stopPropagation(); setSelectedAlert(row.original); }} className="flex-shrink-0 p-1 text-[#002244] dark:text-gray-400 hover:bg-blue-50 dark:hover:bg-[#21262d] hover:text-[#0071CE] rounded transition-colors" title="View full alert details"><Info className="w-3.5 h-3.5" /></button>
      </div>
    ) },
    // Status — string "Active"/"Inactive" so multiSelectFilterFn works reliably (no boolean filter issues)
    { id: "status", accessorFn: (row) => (row as AlertResultAlert & { _isActive: boolean })._isActive ? "Active" : "Inactive", header: "Status", size: 90, filterFn: multiSelectFilterFn as never, meta: { filterType: "facet" }, cell: ({ getValue }) => { const a = getValue() as string; return a === "Active" ? <CellBadge variant="red">Active</CellBadge> : <CellBadge variant="default">Inactive</CellBadge>; } },
    // Start Time
    { id: "startTime", accessorFn: (row) => { const v = row.values; return v?.length ? v[0][0] : 0; }, header: "Start Time", size: 160, cell: ({ getValue }) => { const ts = getValue() as number; if (!ts) return <span className="text-gray-400">&mdash;</span>; const d = new Date(ts * 1000); return (<div><div>{d.toLocaleDateString()}, {d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</div><div className="text-[10px] text-gray-400">({formatTimeAgo(ts)})</div></div>); } },
    // Cluster
    { id: "clusterId", accessorFn: (row) => row.cluster || row.labels?.cluster_id || row.labels?.cluster || "", header: "Cluster ID", size: 160, filterFn: "includesString", meta: { filterType: "text" }, cell: ({ getValue }) => <CellCopyable text={getValue() as string} /> },
    // xMatters
    { id: "xmattersGroup", accessorFn: (row) => row.labels?.mms_xmatters_group || "", header: "xMatters", size: 120, filterFn: "includesString", meta: { filterType: "text" }, cell: ({ getValue }) => { const v = getValue() as string; return v ? <CellList items={[v]} variant="purple" /> : <span className="text-gray-400">&mdash;</span>; } },
    // Slack
    { id: "slackChannel", accessorFn: (row) => row.labels?.mms_slack_channel || "", header: "Slack", size: 120, filterFn: "includesString", meta: { filterType: "text" }, cell: ({ getValue }) => { const v = getValue() as string; return v ? <CellList items={[v]} variant="blue" prefix="#" /> : <span className="text-gray-400">&mdash;</span>; } },
    // Hidden by default — user can enable via Columns toggle
    { id: "severity", accessorFn: (row) => row.severity || row.labels?.severity || "", header: "Severity", size: 100, meta: { filterType: "facet" }, filterFn: multiSelectFilterFn as never, cell: ({ getValue }) => { const v = getValue() as string; return v ? <CellBadge variant={v === "critical" ? "red" : v === "warning" ? "orange" : "default"}>{v}</CellBadge> : <span className="text-gray-400">—</span>; } },
    { id: "namespace", accessorFn: (row) => row.namespace || row.labels?.namespace || "", header: "Namespace", size: 160, filterFn: "includesString", meta: { filterType: "text" }, cell: ({ getValue }) => <CellCopyable text={getValue() as string} /> },
    { id: "appName", accessorFn: (row) => row.app_name || row.labels?.app_name || "", header: "App Name", size: 180, filterFn: "includesString", meta: { filterType: "text" }, cell: ({ getValue }) => <CellCopyable text={getValue() as string} /> },
  ], []);

  // Save rows to localStorage with incremental row numbers (1 to length) whenever alertList updates
  useEffect(() => {
    if (alertList.length > 0 && typeof window !== "undefined") {
      try {
        const rowsWithNum = alertList.map((row, idx) => ({ _rowNum: idx + 1, ...row }));
        localStorage.setItem("sre_alerts_rows", JSON.stringify(rowsWithNum));
        (window as any).__alertsRows = rowsWithNum;
      } catch {
        // localStorage can throw if quota exceeded — silently ignore
      }
    }
  }, [alertList, refreshEpoch]);

  // Time frame + action controls — passed as prefixActions into the DataTable toolbar (row 1)
  const alertsPrefixActions = (
    <div className="flex items-center gap-2 ml-auto">
      {/* Time frame group — enclosed in a single bordered container */}
      <div className={`flex items-center gap-1.5 px-2.5 h-7 rounded-md border ${
        isDark ? "border-[#30363d] bg-[#161b22]" : "border-gray-200 bg-white"
      }`}>
        <label className={`text-xs whitespace-nowrap ${isDark ? "text-gray-500" : "text-gray-400"}`}>Time:</label>
        <input
          type="number"
          value={draftValue}
          min={draftUnit === "hours" ? 1 : MIN_MINUTES}
          max={draftUnit === "hours" ? MAX_HOURS : MAX_HOURS * 60}
          onChange={(e) => handleDraftValueChange(Number(e.target.value))}
          aria-label="Time frame value"
          className={`h-5 text-xs border-0 rounded px-1 py-0 w-10 text-center focus:outline-none ${
            isDark ? "bg-[#21262d] text-gray-200" : "bg-gray-50 text-gray-700"
          }`}
        />
        <select
          value={draftUnit}
          onChange={(e) => handleDraftUnitChange(e.target.value as TimeUnit)}
          aria-label="Time frame unit"
          className={`h-5 text-xs border-0 rounded px-1 py-0 focus:outline-none ${
            isDark ? "bg-[#21262d] text-gray-200" : "bg-gray-50 text-gray-700"
          }`}
        >
          <option value="minutes">Min</option>
          <option value="hours">Hours</option>
        </select>
      </div>
      {/* Apply — primary action button */}
      <button
        onClick={handleSubmit}
        disabled={loading}
        className={`h-7 text-xs px-3 rounded-md font-medium whitespace-nowrap transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
          isDark
            ? "bg-blue-600 text-white hover:bg-blue-500"
            : "bg-[#002244] text-white hover:bg-[#003366]"
        }`}
      >
        Apply
      </button>
      {/* Divider */}
      <div className={`h-4 w-px ${isDark ? "bg-gray-700" : "bg-gray-300"}`} />
      {/* Expand — ghost button, consistent with row-2 utilities */}
      {alertList.length > 0 && (
        <button
          onClick={() => startTransition(() => setExpandedView(true))}
          className={`h-7 flex items-center gap-1.5 px-2.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors ${
            isDark ? "text-gray-400 hover:text-gray-200 hover:bg-[#21262d]" : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
          }`}
          title="Expanded view"
        >
          <Maximize2 className="w-3.5 h-3.5 flex-shrink-0" />
          Expand
        </button>
      )}
      {/* Refresh — ghost button, matches Expand */}
      <button
        onClick={handleRefresh}
        disabled={loading || refreshing}
        className={`h-7 flex items-center gap-1.5 px-2.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
          isDark ? "text-gray-400 hover:text-gray-200 hover:bg-[#21262d]" : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
        }`}
      >
        <RefreshCw className={`w-3.5 h-3.5 flex-shrink-0 ${refreshing ? "animate-spin" : ""}`} />
        Refresh
      </button>
    </div>
  );

  return (
    <div className="flex-1 flex flex-col h-full">

      {/* Content */}
      <div className="flex-1 flex flex-col min-h-0">
        {error && (
          <div className={`border rounded-lg p-4 mx-6 mt-4 mb-2 flex-shrink-0 ${isDark ? "bg-red-900/20 border-red-800" : "bg-red-50 border-red-200"}`}>
            <div className="flex gap-3">
              <AlertCircle className={`w-5 h-5 flex-shrink-0 mt-0.5 ${isDark ? "text-red-400" : "text-red-600"}`} />
              <div>
                <h3 className={`font-medium ${isDark ? "text-red-300" : "text-red-900"}`}>Error fetching alerts</h3>
                <p className={`text-sm mt-1 ${isDark ? "text-red-400" : "text-red-700"}`}>{error}</p>
              </div>
            </div>
          </div>
        )}

        {loading && alertList.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 flex-shrink-0">
            <Loader className={`w-8 h-8 animate-spin mb-4 ${isDark ? "text-blue-400" : "text-[#002244]"}`} />
            <p className={`text-sm font-medium ${isDark ? "text-gray-300" : "text-gray-700"}`}>Fetching alerts...</p>
            <p className={`text-xs mt-1.5 ${isDark ? "text-gray-500" : "text-gray-400"}`}>This typically takes 30–50 seconds to load</p>
          </div>
        )}

        {!loading && alerts && alertList.length === 0 && !error && (
          <div className={`flex flex-col items-center justify-center py-12 flex-shrink-0 ${isDark ? "text-gray-500" : "text-gray-500"}`}>
            <Bell className="w-12 h-12 mb-4 opacity-50" />
            <p className="text-sm text-center">No alerts found for the last {timeLabel}</p>
          </div>
        )}

        {/* Tab content — fills remaining space */}
        {alertList.length > 0 && (
          <>
            {activeTab === "table" ? (
              <div className="flex-1 flex flex-col min-h-0">
                <DataTable
                  data={alertList}
                  columns={alertColumns}
                  title="Alerts"
                  defaultSorting={[{ id: "startTime", desc: true }]}
                  defaultColumnVisibility={{
                    alertId: false,
                    severity: false,
                    namespace: false,
                    appName: false,
                  }}
                  getRowId={(row, idx) => row.alert_id ? `${row.alert_id}-${idx}` : `row-${idx}`}
                  emptyMessage="No alerts found"
                  filterEmptyMessage="No alerts match your filters"
                  prefixActions={alertsPrefixActions}
                  toolbarActions={
                    <TabBar activeTab={activeTab} onTabChange={(t) => { setActiveTab(t); if (t === "table") setIsTimelineZoomed(false); }} />
                  }
                />
              </div>
            ) : (
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className={`px-4 py-2 flex items-center gap-3 border-b flex-shrink-0 ${isDark ? "bg-[#0d1117] border-[#30363d]" : "bg-[#f8f9fa] border-gray-200"}`}>
                  <TabBar activeTab={activeTab} onTabChange={(t) => { setActiveTab(t); if (t === "table") setIsTimelineZoomed(false); }} />
                </div>
                <div className="flex-1 overflow-hidden">
                  <AlertsGraphDashboard section1={{ data: s1Data, loading: s1Loading, error: s1Error }} section2={{ data: s2Data, loading: s2Loading, error: s2Error }} section3={{ data: s3Data, loading: s3Loading, error: s3Error }} />
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Info Dialog */}
      {infoMessage && (
        <AlertInfoDialog message={infoMessage} onClose={() => setInfoMessage(null)} isDark={isDark} />
      )}

      {/* Expanded View */}
      {expandedView && (
        <ExpandedView
          alerts={alertList}
          activeAlerts={activeAlerts}
          alertCount={alertList.length}
          timeValue={draftValue}
          timeUnit={draftUnit}
          timeStart={timeStart}
          timeEnd={timeEnd}
          onTimeValueChange={handleDraftValueChange}
          onUnitChange={handleDraftUnitChange}
          loading={loading}
          refreshing={refreshing}
          onRefresh={handleRefresh}
          onClose={() => startTransition(() => setExpandedView(false))}
          onInfoClick={setInfoMessage}
          isDark={isDark}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          onSubmit={handleSubmit}
          getAlertActive={getAlertActiveStatus}
          sort={sort}
          onSort={setSort}
          onAlertDetailClick={setSelectedAlert}
          graphSection1={{ data: s1Data, loading: s1Loading, error: s1Error }}
          graphSection2={{ data: s2Data, loading: s2Loading, error: s2Error }}
          graphSection3={{ data: s3Data, loading: s3Loading, error: s3Error }}
        />
      )}

      {/* Alert Details Dialog */}
      {selectedAlert && (
        <AlertDetailsDialog alert={selectedAlert} onClose={() => setSelectedAlert(null)} isDark={isDark} />
      )}
    </div>
  );
}
