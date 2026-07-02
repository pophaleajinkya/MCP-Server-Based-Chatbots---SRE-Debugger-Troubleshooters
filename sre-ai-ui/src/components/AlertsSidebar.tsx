"use client";

import { useEffect, useState, useMemo, useCallback, startTransition, memo } from "react";
import { X, AlertCircle, Loader, RefreshCw, Info, Maximize2, Copy, LayoutList, BarChart2, ChevronLeft, ChevronRight, ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import type { Application, ManagedServiceData, AlertQueryResult, AlertResultAlert } from "@/lib/api-client";
import { promqlApi } from "@/lib/api-client";
import { useTheme } from "@/contexts/ThemeContext";
import { AlertsMultiLineGraphSection } from "@/components/AlertsMultiLineGraphSection";
import type { MultiSeriesGraphData } from "@/components/AlertsMultiLineGraphSection";

interface AlertsSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  app: Application | ManagedServiceData | null;
  intent?: string;
}

type TimeUnit = "minutes" | "hours";
type TabView = "table" | "timeline";
type AlertSortKey = "alert_sla_name" | "episode_start_ts" | "status" | "cluster" | "mms_xmatters_group" | "mms_slack_channel" | "alert_owner_category" | "alertname";
interface AlertSortConfig {
  key: AlertSortKey;
  direction: "asc" | "desc";
}

const MIN_MINUTES = 5;
const MAX_HOURS   = 24;

// Applications/Managed Services sidebar: 30 seconds for fine-grained tracking
const STEP = "30s";
// Configurable threshold: alerts are considered "active" if they ended within this many seconds
// Automatically derived from STEP value (parses "30s" → 30 seconds)
const ACTIVE_THRESHOLD_SECS = parseInt(STEP) || 60;

function computeGraphStep(startSec: number, endSec: number): string {
  const range = endSec - startSec;
  if (range <= 3600) return "60s";
  if (range <= 14400) return "300s";
  if (range <= 43200) return "900s";
  return "3600s";
}

/**
 * Build the PromQL filter string from the app/service object.
 * Always includes tool="juno", alert_team="intl_sre_golden_signals", alertstate="firing"
 * plus service_type-specific labels matching buildAlertsQueryPayload.
 */
function buildPromQLFilters(app: Application | ManagedServiceData): string {
  const base = 'tool="juno", alert_team="intl_sre_golden_signals", alertstate="firing"';
  const extras: string[] = [];

  if ("applicationType" in app) {
    const application = app as Application;
    const sType = (application.applicationType || "").toLowerCase();
    if (sType) extras.push(`alert_type="${sType}"`);
    if (sType === "wcnp") {
      if (application.namespace) extras.push(`namespace="${application.namespace}"`);
      if (application.appName) extras.push(`app_name="${application.appName}"`);
    } else if (sType === "oneops") {
      if (application.oneOpsAssembly) extras.push(`assembly="${application.oneOpsAssembly}"`);
      if (application.oneOpsPlatform) extras.push(`platform="${application.oneOpsPlatform}"`);
    }
  } else if ("serviceType" in app) {
    const service = app as ManagedServiceData;
    const sType = (service.serviceType || "").toLowerCase();
    if (sType) extras.push(`alert_type="${sType}"`);
    switch (sType) {
      case "cassandra":
        if (service.assembly) extras.push(`cluster="${service.assembly}"`);
        break;
      case "cosmos":
        if (service.subscriptionId) extras.push(`subscription_name="${service.subscriptionId}"`);
        if (service.resourceGroup) extras.push(`resource_group="${service.resourceGroup}"`);
        break;
      case "kafka":
        if (service.assembly) extras.push(`cluster="${service.assembly}"`);
        if (service.topicName) extras.push(`topic="${service.topicName}"`);
        break;
      case "meghacache":
        if (service.assembly) extras.push(`megacache_assembly="${service.assembly}"`);
        break;
      case "sql":
      case "oracle":
        if (service.databaseName) extras.push(`database="${service.databaseName}"`);
        break;
    }
  }

  return extras.length > 0 ? `${base},${extras.join(",")}` : base;
}

/**
 * Parse a PromQL "count by (key)" response into multi-series format.
 */
function parsePromQLToMultiSeries(result: any, groupByKey: string): MultiSeriesGraphData {
  const seriesKeysSet = new Set<string>();
  const tsMap = new Map<number, Record<string, number>>();

  if (result?.data?.result && result.data.result.length > 0) {
    for (const series of result.data.result) {
      const seriesName = series.metric?.[groupByKey] || "unknown";
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
 * Parse raw PromQL ALERTS response into per-alert multi-series for a line graph.
 * Each individual alert becomes its own line (value = 1 when firing).
 * Duplicate alert_sla_name entries get a numeric suffix.
 */
function parsePromQLToPerAlertSeries(result: any): MultiSeriesGraphData {
  const seriesKeysSet = new Set<string>();
  const tsMap = new Map<number, Record<string, number>>();
  // Each alert gets a unique Y-lane so lines don't overlap
  const laneMap = new Map<string, number>();

  if (result?.data?.result && result.data.result.length > 0) {
    const nameCount: Record<string, number> = {};
    let laneIndex = 1;

    for (const series of result.data.result) {
      const m = series.metric || {};
      const baseName = m.alert_sla_name || m.alertname || "unknown";
      nameCount[baseName] = (nameCount[baseName] || 0) + 1;
      const seriesName = nameCount[baseName] > 1 ? `${baseName} (${nameCount[baseName]})` : baseName;
      seriesKeysSet.add(seriesName);
      laneMap.set(seriesName, laneIndex);
      laneIndex++;

      for (const [ts] of series.values as [number, string][]) {
        if (!tsMap.has(ts)) tsMap.set(ts, {});
        // Assign each alert its own lane value so they stack vertically
        tsMap.get(ts)![seriesName] = laneMap.get(seriesName)!;
      }
    }
  }

  const seriesKeys = Array.from(seriesKeysSet).sort();
  const timestamps = Array.from(tsMap.keys()).sort((a, b) => a - b);

  const points = timestamps.map((ts) => {
    const row: any = { timestamp: ts };
    const vals = tsMap.get(ts)!;
    for (const key of seriesKeys) {
      row[key] = vals[key] ?? undefined;
    }
    return row;
  });

  return { points, seriesKeys };
}

/**
 * Convert raw PromQL ALERTS response into AlertResultAlert[] for the table.
 * Each result series has metric labels (= alert metadata) + values (= time-series).
 */
function parsePromQLToAlertList(result: any): { alerts: AlertResultAlert[]; total_count: number } {
  const alerts: AlertResultAlert[] = [];

  if (result?.data?.result && result.data.result.length > 0) {
    for (const series of result.data.result) {
      const m = series.metric || {};
      const values: [number, string][] = Array.isArray(series.values) ? series.values : [];
      const firstTs = values.length > 0 ? values[0][0] : null;
      const lastTs = values.length > 0 ? values[values.length - 1][0] : null;

      alerts.push({
        alertname: m.alertname || m.__name__ || undefined,
        alert_type: m.alert_type || undefined,
        alert_sla_name: m.alert_sla_name || undefined,
        severity: m.severity || undefined,
        state: m.alertstate || undefined,
        cluster: m.cluster || null,
        namespace: m.namespace || undefined,
        app_name: m.app_name || undefined,
        alert_team: m.alert_team || null,
        alert_owner_category: m.alert_owner_category || null,
        alert_component: m.alert_component || null,
        mms_slack_channel: m.mms_slack_channel || null,
        mms_xmatters_group: m.mms_xmatters_group || null,
        episode_start_ts: firstTs,
        episode_end_ts: lastTs,
        episode_is_open: lastTs != null ? (Math.abs(Math.floor(Date.now() / 1000) - lastTs) <= ACTIVE_THRESHOLD_SECS) : false,
        values,
        labels: m,
      });
    }
  }

  return { alerts, total_count: alerts.length };
}

function isAlertActive(alert: AlertResultAlert): boolean {
  if (alert.episode_is_open) return true;
  const now = Math.floor(Date.now() / 1000);
  if (alert.episode_end_ts != null) {
    return Math.abs(now - alert.episode_end_ts) <= ACTIVE_THRESHOLD_SECS;
  }
  const lastValueTs = alert.values && alert.values.length > 0
    ? alert.values[alert.values.length - 1][0]
    : null;
  if (lastValueTs != null) {
    return Math.abs(now - lastValueTs) <= ACTIVE_THRESHOLD_SECS;
  }
  return false;
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

function TabBar({ activeTab, onTabChange }: { activeTab: TabView; onTabChange: (t: TabView) => void }) {
  const { isDark } = useTheme();
  return (
    <div className={`flex gap-1 rounded-lg p-1 ${isDark ? "bg-gray-700" : "bg-gray-100"}`}>
      <button
        onClick={() => onTabChange("table")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
          activeTab === "table"
            ? isDark ? "bg-gray-600 text-white shadow-sm" : "bg-white text-[#002244] shadow-sm"
            : isDark ? "text-gray-400 hover:text-gray-100" : "text-gray-500 hover:text-gray-800"
        }`}
      >
        <LayoutList className="w-3.5 h-3.5" />
        Table
      </button>
      <button
        onClick={() => onTabChange("timeline")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
          activeTab === "timeline"
            ? isDark ? "bg-gray-600 text-white shadow-sm" : "bg-white text-[#002244] shadow-sm"
            : isDark ? "text-gray-400 hover:text-gray-100" : "text-gray-500 hover:text-gray-800"
        }`}
      >
        <BarChart2 className="w-3.5 h-3.5" />
        Timeline
      </button>
    </div>
  );
}

const ALERT_TABLE_COLUMNS: { label: string; sortKey: AlertSortKey; minW: string; border: boolean }[] = [
  { label: "SLA_name", sortKey: "alert_sla_name", minW: "min-w-[130px]", border: true },
  { label: "Alert start time", sortKey: "episode_start_ts", minW: "min-w-[160px]", border: true },
  { label: "Status", sortKey: "status", minW: "min-w-[80px]", border: true },
  { label: "Cluster_id", sortKey: "cluster", minW: "min-w-[110px]", border: true },
  { label: "x_matters_group", sortKey: "mms_xmatters_group", minW: "min-w-[160px]", border: true },
  { label: "Slack_xmatters", sortKey: "mms_slack_channel", minW: "min-w-[160px]", border: true },
  { label: "Alert category", sortKey: "alert_owner_category", minW: "min-w-[130px]", border: true },
  { label: "Alert name", sortKey: "alertname", minW: "min-w-[200px]", border: false },
];

function SortIcon({ sortKey, sort }: { sortKey: AlertSortKey; sort: AlertSortConfig | null }) {
  if (sort?.key === sortKey) {
    return sort.direction === "asc"
      ? <ChevronUp className="w-3 h-3 text-[#90EE90] flex-shrink-0" />
      : <ChevronDown className="w-3 h-3 text-[#90EE90] flex-shrink-0" />;
  }
  return <ChevronsUpDown className="w-3 h-3 text-white/40 flex-shrink-0" />;
}

const AlertsTable = memo(function AlertsTable({
  alerts,
  onInfoClick,
  getAlertActive,
  sort,
  onSort,
}: {
  alerts: AlertResultAlert[];
  onInfoClick: (msg: string) => void;
  getAlertActive: (alert: AlertResultAlert) => boolean;
  sort: AlertSortConfig | null;
  onSort: (key: AlertSortKey) => void;
}) {
  return (
    <table className="w-full font-sans">
      <thead className="sticky top-0 z-20">
        <tr className="bg-[#002244] dark:bg-gray-800">
          {ALERT_TABLE_COLUMNS.map(({ label, sortKey, minW, border }) => (
            <th
              key={sortKey}
              onClick={() => onSort(sortKey)}
              className={`px-5 py-4 text-left text-sm font-semibold tracking-wide text-[#90EE90] dark:text-blue-300 cursor-pointer select-none hover:bg-white/5 transition-colors ${minW} ${
                border ? "border-r border-white/15 dark:border-white/10" : ""
              }`}
            >
              <div className="flex items-center gap-1">
                {label}
                <SortIcon sortKey={sortKey} sort={sort} />
              </div>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {alerts.length === 0 ? (
          <tr>
            <td colSpan={ALERT_TABLE_COLUMNS.length} className="px-5 py-16 text-center">
              <div className="flex flex-col items-center gap-2">
                <AlertCircle className="w-7 h-7 opacity-40 text-gray-400 dark:text-gray-500" />
                <p className="text-sm text-gray-500 dark:text-gray-400">No data available</p>
              </div>
            </td>
          </tr>
        ) : null}
        {alerts.map((alert, idx) => {
          const active = getAlertActive(alert);
          const startTs = alert.episode_start_ts ?? alert.values?.[0]?.[0] ?? null;
          const startIsFallback = alert.episode_start_ts == null && startTs != null;

          return (
            <tr
              key={`${alert.alert_id || "alert"}-${idx}`}
              className={`col-separated border-b transition-[box-shadow]
                border-gray-100 dark:border-gray-700
                hover:bg-[#f5f9ff] dark:hover:bg-gray-700/60
                hover:shadow-[inset_4px_0_0_#002244] dark:hover:shadow-[inset_4px_0_0_#3b82f6]
                ${idx % 2 === 1
                  ? "bg-[#fafbfc] dark:bg-gray-800/50"
                  : "bg-white dark:bg-gray-900"
                }`}
            >
              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-200">{alert.alert_sla_name || "-"}</td>
              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-200">
                {startTs != null ? (
                  <div className="flex flex-col gap-0.5">
                    <span>{formatTimestamp(startTs)}</span>
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      ({formatRelativeTime(startTs)})
                    </span>
                  </div>
                ) : "-"}
              </td>
              <td className="px-5 py-3 text-sm">
                <span
                  className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${
                    active
                      ? "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300"
                      : "bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-300"
                  }`}
                >
                  {active ? "Active" : "Inactive"}
                </span>
              </td>
              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-200">
                {(() => {
                  const cid = alert.cluster ?? alert.labels?.cluster_id ?? null;
                  return cid ? (
                    <div className="flex items-center justify-between">
                      <span className="truncate" title={cid}>{cid}</span>
                      <button
                        onClick={() => navigator.clipboard.writeText(cid)}
                        className="flex-shrink-0 ml-2 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400"
                        title="Copy Cluster_id"
                      >
                        <Copy className="w-3 h-3" />
                      </button>
                    </div>
                  ) : "-";
                })()}
              </td>
              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-200">
                {alert.mms_xmatters_group ? (
                  <div className="flex items-center justify-between">
                    <span className="truncate" title={alert.mms_xmatters_group}>{alert.mms_xmatters_group}</span>
                    <button
                      onClick={() => navigator.clipboard.writeText(alert.mms_xmatters_group!)}
                      className="flex-shrink-0 ml-2 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400"
                      title="Copy x_matters_group"
                    >
                      <Copy className="w-3 h-3" />
                    </button>
                  </div>
                ) : "-"}
              </td>
              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-200">
                {alert.mms_slack_channel ? (
                  <div className="flex items-center justify-between">
                    <span className="truncate" title={alert.mms_slack_channel}>{alert.mms_slack_channel}</span>
                    <button
                      onClick={() => navigator.clipboard.writeText(alert.mms_slack_channel!)}
                      className="flex-shrink-0 ml-2 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400"
                      title="Copy Slack_xmatters"
                    >
                      <Copy className="w-3 h-3" />
                    </button>
                  </div>
                ) : "-"}
              </td>
              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-200">{alert.alert_owner_category || "-"}</td>
              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-200">
                <div className="flex items-center gap-1.5">
                  <span className="truncate max-w-[170px]" title={alert.alertname || undefined}>
                    {alert.alertname || "-"}
                  </span>
                  {alert.alertname && (
                    <button
                      onClick={() => onInfoClick(alert.alertname!)}
                      className="flex-shrink-0 transition-colors text-gray-400 hover:text-blue-600 dark:text-gray-500 dark:hover:text-blue-400"
                      title="View full alert name"
                    >
                      <Info className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
});

function ExpandedView({
  alerts,
  appName,
  alertCount,
  timeValue,
  timeUnit,
  timeStart,
  timeEnd,
  onTimeValueChange,
  onUnitChange,
  onSubmit,
  loading,
  refreshing,
  onRefresh,
  onClose,
  onInfoClick,
  isDark,
  activeTab,
  onTabChange,
  getAlertActive,
  sort,
  onSort,
  s1Data,
  s1Error,
  graphData,
  graphLoading,
  graphError,
}: {
  alerts: AlertResultAlert[];
  appName: string;
  alertCount: number;
  timeValue: number;
  timeUnit: TimeUnit;
  timeStart: number;
  timeEnd: number;
  onTimeValueChange: (raw: number) => void;
  onUnitChange: (unit: TimeUnit) => void;
  onSubmit: () => void;
  loading: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onClose: () => void;
  onInfoClick: (msg: string) => void;
  isDark: boolean;
  activeTab: TabView;
  onTabChange: (t: TabView) => void;
  getAlertActive: (alert: AlertResultAlert) => boolean;
  sort: AlertSortConfig | null;
  onSort: (key: AlertSortKey) => void;
  s1Data: MultiSeriesGraphData | null;
  s1Error: string | null;
  graphData: MultiSeriesGraphData | null;
  graphLoading: boolean;
  graphError: string | null;
}) {

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
            <h2 className="text-lg font-semibold text-white">Alerts — {appName}</h2>
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
                disabled={loading || refreshing}
                className="text-xs px-3 py-1.5 rounded border border-white/30 bg-white/10 text-white/80 hover:text-white hover:border-white/60 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
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
        <div className={`px-6 py-3 border-b flex-shrink-0 ${isDark ? "bg-gray-800 border-gray-700" : "bg-gray-50 border-gray-200"}`}>
          <TabBar activeTab={activeTab} onTabChange={onTabChange} />
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto">
          {activeTab === "table" && loading ? (
            <div className={`flex flex-col items-center justify-center h-full gap-4 ${isDark ? "text-gray-400" : "text-gray-500"}`}>
              <Loader className="w-8 h-8 animate-spin" />
              <p className="text-sm">Fetching alerts...</p>
            </div>
          ) : activeTab === "table" ? (
            <AlertsTable alerts={alerts} onInfoClick={onInfoClick} getAlertActive={getAlertActive} sort={sort} onSort={onSort} />
          ) : (
            <div className="p-4 h-full">
              <div className="grid grid-cols-2 gap-4 h-full" style={{ minHeight: 500 }}>
                {/* Section 1: Per-alert firing timeline as line graph */}
                <div className="min-h-0" style={{ minHeight: 500 }}>
                  <AlertsMultiLineGraphSection
                    title="Alert Timeline"
                    data={s1Data ?? { points: [], seriesKeys: [] }}
                    loading={loading}
                    error={s1Error}
                    hideYAxis
                  />
                </div>
                {/* Section 2: COUNT by alert_sla_name multi-line graph */}
                <div className="min-h-0" style={{ minHeight: 500 }}>
                  <AlertsMultiLineGraphSection
                    title="Alerts by SLA Name"
                    data={graphData ?? { points: [], seriesKeys: [] }}
                    loading={graphLoading}
                    error={graphError}
                    yAxisLabel="Count"
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function AlertsSidebar({ isOpen, onClose, app, intent }: AlertsSidebarProps) {
  const { isDark } = useTheme();
  const [alerts, setAlerts] = useState<AlertQueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [expandedView, setExpandedView] = useState(false);
  // Draft = what user is typing; committed = last fetched
  const [draftValue, setDraftValue] = useState(1);
  const [draftUnit, setDraftUnit] = useState<TimeUnit>("hours");
  const [timeValue, setTimeValue] = useState(1);
  const [timeUnit, setTimeUnit] = useState<TimeUnit>("hours");
  const [activeTab, setActiveTab] = useState<TabView>("table");
  const [pageSize, setPageSize] = useState(25);
  const [currentPage, setCurrentPage] = useState(0);
  // Cache alert active/inactive status - only updated on Refresh/Apply, not on other events
  const [alertStatusCache, setAlertStatusCache] = useState<Record<string, boolean>>({});
  // Section 1: Per-alert line graph data (from raw ALERTS response)
  const [s1Data, setS1Data] = useState<MultiSeriesGraphData | null>(null);
  // Section 2: COUNT by alert_sla_name graph data
  const [graphData, setGraphData] = useState<MultiSeriesGraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  // Sorting
  const [sort, setSort] = useState<AlertSortConfig | null>(null);
  // Committed window (for timeline axis + fetch)
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
    fetchAlerts(w);
  };

  useEffect(() => {
    if (!isOpen || !app) return;
    fetchAlerts();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, app, intent]);

  const fetchAlerts = async (windowSecs?: number) => {
    if (!app) return;
    const w = windowSecs ?? timeWindow;
    setLoading(true);
    setError(null);
    // Clear old data so graphs/table show loading state on refresh
    setAlerts(null);
    setS1Data(null);
    setGraphData(null);
    setGraphLoading(true);
    setGraphError(null);
    try {
      const now = Math.floor(Date.now() / 1000);
      const startEpoch = String(now - w);
      const endEpoch = String(now);
      const filters = buildPromQLFilters(app);
      const graphStep = computeGraphStep(now - w, now);

      // 1. Fetch table data via PromQL — raw ALERTS metric (each series = one alert)
      // Includes retry on timeout (AsyncRequestTimeoutException)
      const tablePromql = `(ALERTS{${filters}})`;
      const tablePayload = { promql: tablePromql, start: startEpoch, end: endEpoch, step: graphStep };
      const tableResult = await promqlApi.queryRange(tablePayload).catch(async (err: unknown) => {
        const msg = err instanceof Error ? err.message : "";
        if (msg.includes("500") || msg.includes("Timeout") || msg.includes("AsyncRequest")) {
          console.warn("[AlertsSidebar] Table PromQL timeout, retrying after 2s...");
          await new Promise((r) => setTimeout(r, 2000));
          return promqlApi.queryRange(tablePayload).catch((retryErr: unknown) => {
            const retryMsg = retryErr instanceof Error ? retryErr.message : "Failed to fetch alerts";
            setError(retryMsg);
            console.error("[AlertsSidebar] Table PromQL retry failed:", retryErr);
            return null;
          });
        }
        setError(msg || "Failed to fetch alerts");
        console.error("[AlertsSidebar] Table PromQL error:", err);
        return null;
      });

      if (tableResult) {
        const parsed = parsePromQLToAlertList(tableResult);
        setAlerts({
          status: "success",
          alerts: parsed.alerts,
          total_count: parsed.total_count,
        });

        // Section 1: parse raw result into per-alert line graph data
        setS1Data(parsePromQLToPerAlertSeries(tableResult));

        // Cache alert status
        const cache: Record<string, boolean> = {};
        parsed.alerts.forEach(alert => {
          const key = alert.alert_id || `${alert.alertname}-${alert.alert_sla_name}`;
          cache[key] = isAlertActive(alert);
        });
        setAlertStatusCache(cache);
      } else {
        setAlerts({ status: "success", alerts: [], total_count: 0 });
        setS1Data(null);
      }
      setLoading(false);

      // 2. Fetch graph section 2: COUNT by alert_sla_name — sequential after table
      await new Promise((resolve) => setTimeout(resolve, 2000));

      const graphPromql = `COUNT by (alert_sla_name)(ALERTS{${filters}})`;
      const graphPayload = { promql: graphPromql, start: startEpoch, end: endEpoch, step: graphStep };

      const graphResult = await promqlApi.queryRange(graphPayload).catch(async (err: unknown) => {
        const msg = err instanceof Error ? err.message : "";
        if (msg.includes("500") || msg.includes("Timeout") || msg.includes("AsyncRequest")) {
          console.warn("[AlertsSidebar] Graph PromQL timeout, retrying after 2s...");
          await new Promise((r) => setTimeout(r, 2000));
          return promqlApi.queryRange(graphPayload).catch((retryErr: unknown) => {
            const retryMsg = retryErr instanceof Error ? retryErr.message : "Failed to fetch graph data";
            setGraphError(retryMsg);
            console.error("[AlertsSidebar] Graph retry failed:", retryErr);
            return null;
          });
        }
        setGraphError(msg || "Failed to fetch graph data");
        console.error("[AlertsSidebar] Graph error:", err);
        return null;
      });

      if (graphResult) {
        setGraphData(parsePromQLToMultiSeries(graphResult, "alert_sla_name"));
      }
    } catch (err) {
      const raw = err instanceof Error ? err.message : "Failed to fetch alerts";
      const errorMessage = /50[234]/.test(raw)
        ? "The alerts service is temporarily unavailable. Please try again in a moment."
        : raw;
      setError(errorMessage);
      console.error("Error fetching alerts:", err);
    } finally {
      setLoading(false);
      setGraphLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchAlerts();
    setRefreshing(false);
  };

  // Get cached alert status - uses cached value from last Refresh/Apply, not real-time calculation
  const getAlertActiveStatus = (alert: AlertResultAlert): boolean => {
    const key = alert.alert_id || `${alert.alertname}-${alert.alert_sla_name}`;
    return alertStatusCache[key] ?? false;
  };

  const getAppName = (): string => {
    if (!app) return "Unknown";
    if ("name" in app) return app.name;
    return "Unknown";
  };

  const getAppType = (): string => {
    if (!app) return "Unknown";
    if ("applicationType" in app) return app.applicationType;
    if ("serviceType" in app) return app.serviceType || "Unknown";
    return "Unknown";
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const alertList = useMemo(() => Array.isArray(alerts?.alerts) ? alerts!.alerts : [], [alerts]);

  // Sort handler: asc → desc → clear (3-state toggle)
  const handleSort = useCallback((key: AlertSortKey) => {
    setSort((prev) => {
      if (prev?.key === key) {
        return prev.direction === "asc" ? { key, direction: "desc" } : null;
      }
      return { key, direction: "asc" };
    });
    setCurrentPage(0);
  }, []);

  // Sorted alert list
  const sortedAlerts = useMemo(() => {
    if (!sort) return alertList;

    const factor = sort.direction === "asc" ? 1 : -1;

    return [...alertList].sort((a, b) => {
      let aVal: string | number | boolean | null;
      let bVal: string | number | boolean | null;

      switch (sort.key) {
        case "alert_sla_name":
          aVal = a.alert_sla_name || "";
          bVal = b.alert_sla_name || "";
          break;
        case "episode_start_ts":
          aVal = a.episode_start_ts ?? a.values?.[0]?.[0] ?? null;
          bVal = b.episode_start_ts ?? b.values?.[0]?.[0] ?? null;
          break;
        case "status": {
          const aKey = a.alert_id || `${a.alertname}-${a.alert_sla_name}`;
          const bKey = b.alert_id || `${b.alertname}-${b.alert_sla_name}`;
          aVal = (alertStatusCache[aKey] ?? false) ? 0 : 1; // Active first in asc
          bVal = (alertStatusCache[bKey] ?? false) ? 0 : 1;
          break;
        }
        case "cluster":
          aVal = a.cluster ?? a.labels?.cluster_id ?? "";
          bVal = b.cluster ?? b.labels?.cluster_id ?? "";
          break;
        case "mms_xmatters_group":
          aVal = a.mms_xmatters_group || "";
          bVal = b.mms_xmatters_group || "";
          break;
        case "mms_slack_channel":
          aVal = a.mms_slack_channel || "";
          bVal = b.mms_slack_channel || "";
          break;
        case "alert_owner_category":
          aVal = a.alert_owner_category || "";
          bVal = b.alert_owner_category || "";
          break;
        case "alertname":
          aVal = a.alertname || "";
          bVal = b.alertname || "";
          break;
        default:
          return 0;
      }

      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;

      if (typeof aVal === "number" && typeof bVal === "number") {
        return (aVal - bVal) * factor;
      }

      return String(aVal).toLowerCase().localeCompare(String(bVal).toLowerCase()) * factor;
    });
  }, [alertList, sort, alertStatusCache]);

  // Reset page when data changes
  useEffect(() => { setCurrentPage(0); }, [alerts]);

  const totalPages = Math.ceil(sortedAlerts.length / pageSize);
  const pageStart = currentPage * pageSize;
  const pageEnd = Math.min(pageStart + pageSize, sortedAlerts.length);
  const paginatedAlerts = sortedAlerts.slice(pageStart, pageEnd);

  return (
    <>
      {/* Overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-40 transition-opacity duration-300 ease-out"
          onClick={onClose}
          style={{ pointerEvents: isOpen ? "auto" : "none" }}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed top-0 right-0 h-full w-[900px] shadow-2xl z-50 flex flex-col transition-[transform,opacity] duration-400 ease-out ${
          isDark ? "bg-gray-900" : "bg-white"
        } ${isOpen ? "translate-x-0 opacity-100" : "translate-x-full opacity-95"}`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700 bg-[#002244]">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-white truncate">Alerts</h2>
            <p className="text-sm text-white/70 truncate">
              {getAppName()} ({getAppType()})
            </p>
          </div>
          <div className="flex items-center gap-3 ml-4 flex-shrink-0">
            {alerts && (
              <button
                onClick={() => startTransition(() => setExpandedView(true))}
                className="text-white/80 hover:text-white transition-colors"
                title="Expanded view"
              >
                <Maximize2 className="w-5 h-5" />
              </button>
            )}
            <button
              onClick={onClose}
              className="text-white/80 hover:text-white transition-colors"
              title="Close alerts"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Time frame filter */}
        <div className={`flex items-center gap-2 px-4 py-2 border-b ${isDark ? "border-gray-700 bg-gray-800" : "border-gray-200 bg-gray-50"}`}>
          <label className={`text-xs font-medium whitespace-nowrap ${isDark ? "text-gray-400" : "text-gray-600"}`}>Time frame:</label>
          <input
            type="number"
            value={draftValue}
            min={draftUnit === "hours" ? 1 : MIN_MINUTES}
            max={draftUnit === "hours" ? MAX_HOURS : MAX_HOURS * 60}
            onChange={(e) => handleDraftValueChange(Number(e.target.value))}
            aria-label="Time frame value"
            className={`text-xs border rounded px-2 py-1 w-16 text-center focus:outline-none focus:ring-1 ${
              isDark
                ? "border-gray-600 bg-gray-700 text-gray-200 focus:ring-blue-500"
                : "border-gray-300 bg-white text-gray-700 focus:ring-[#002244]"
            }`}
          />
          <select
            value={draftUnit}
            onChange={(e) => handleDraftUnitChange(e.target.value as TimeUnit)}
            aria-label="Time frame unit"
            className={`text-xs border rounded px-2 py-1 focus:outline-none focus:ring-1 ${
              isDark
                ? "border-gray-600 bg-gray-700 text-gray-200 focus:ring-blue-500"
                : "border-gray-300 bg-white text-gray-700 focus:ring-[#002244]"
            }`}
          >
            <option value="minutes">Minutes</option>
            <option value="hours">Hours</option>
          </select>
          <button
            onClick={handleSubmit}
            disabled={loading || refreshing}
            className={`text-xs px-3 py-1 rounded font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
              isDark
                ? "bg-blue-600 hover:bg-blue-500 text-white"
                : "bg-[#002244] hover:bg-[#003366] text-white"
            }`}
          >
            Apply
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {error && (
            <div className={`p-4 m-4 border rounded-lg flex-shrink-0 ${isDark ? "bg-red-900/20 border-red-800" : "bg-red-50 border-red-200"}`}>
              <div className="flex gap-3">
                <AlertCircle className={`w-5 h-5 flex-shrink-0 mt-0.5 ${isDark ? "text-red-400" : "text-red-600"}`} />
                <div>
                  <h3 className={`font-medium ${isDark ? "text-red-300" : "text-red-900"}`}>Error fetching alerts</h3>
                  <p className={`text-sm mt-1 ${isDark ? "text-red-400" : "text-red-700"}`}>{error}</p>
                </div>
              </div>
            </div>
          )}

          {(alerts || loading) && (
            <div className="flex-1 flex flex-col min-h-0 p-4">
              {/* Summary + tab bar */}
              <div className="mb-4 flex items-start justify-between gap-4 flex-shrink-0">
                <div>
                  <h3 className={`text-lg font-semibold mb-1 ${isDark ? "text-gray-100" : "text-gray-900"}`}>Alert Details</h3>
                  <p className={`text-sm ${isDark ? "text-gray-400" : "text-gray-600"}`}>
                    {loading ? "Loading..." : (
                      <>Showing {sortedAlerts.length} alert{sortedAlerts.length !== 1 ? "s" : ""} • Total count: {alerts?.total_count || sortedAlerts.length}</>
                    )}
                  </p>
                  {alerts?.query_time_ms && (
                    <p className={`text-xs mt-1 ${isDark ? "text-gray-500" : "text-gray-500"}`}>
                      Query time: {alerts.query_time_ms.toFixed(2)}ms
                    </p>
                  )}
                </div>
                <TabBar activeTab={activeTab} onTabChange={setActiveTab} />
              </div>

              {/* Tab content */}
              {activeTab === "table" && loading ? (
                <div className={`flex-1 flex flex-col items-center justify-center gap-4 ${isDark ? "text-gray-400" : "text-gray-500"}`}>
                  <Loader className="w-8 h-8 animate-spin" />
                  <p className="text-sm">Fetching alerts...</p>
                </div>
              ) : activeTab === "table" ? (
                sortedAlerts.length === 0 ? (
                  <div className={`flex-1 flex flex-col items-center justify-center ${isDark ? "text-gray-500" : "text-gray-500"}`}>
                    <AlertCircle className="w-8 h-8 mb-3 opacity-50" />
                    <p className="text-sm text-center">No alerts found for the last {timeLabel}</p>
                  </div>
                ) : (
                <div className="flex-1 flex flex-col min-h-0">
                  <div className={`flex-1 overflow-auto border rounded-t-lg ${isDark ? "border-gray-700" : "border-gray-200"}`}>
                    <AlertsTable alerts={paginatedAlerts} onInfoClick={setInfoMessage} getAlertActive={getAlertActiveStatus} sort={sort} onSort={handleSort} />
                  </div>
                  {/* Pagination bar */}
                  <div className={`px-4 py-3 border border-t-0 rounded-b-lg flex items-center justify-end gap-6 flex-shrink-0 ${isDark ? "border-gray-700 bg-gray-800" : "border-gray-200 bg-[#fafafa]"}`}>
                    <div className={`flex items-center gap-2 text-sm ${isDark ? "text-gray-300" : "text-gray-600"}`}>
                      <span>Rows per page:</span>
                      <select
                        value={pageSize}
                        onChange={(e) => { setPageSize(Number(e.target.value)); setCurrentPage(0); }}
                        className={`border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 ${isDark ? "border-gray-600 text-gray-100 bg-gray-700 focus:ring-blue-500" : "border-gray-300 text-[#002244] bg-white focus:ring-[#002244]"}`}
                      >
                        <option value={10}>10</option>
                        <option value={25}>25</option>
                        <option value={50}>50</option>
                        <option value={100}>100</option>
                      </select>
                    </div>
                    <div className={`text-sm ${isDark ? "text-gray-300" : "text-gray-600"}`}>
                      {sortedAlerts.length === 0 ? "0–0" : `${pageStart + 1}–${pageEnd}`} of {sortedAlerts.length}
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setCurrentPage(p => Math.max(0, p - 1))}
                        disabled={currentPage === 0}
                        className={`p-1 rounded disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${isDark ? "text-gray-300 hover:bg-gray-700" : "text-gray-600 hover:bg-gray-100"}`}
                      >
                        <ChevronLeft className="w-5 h-5" />
                      </button>
                      <button
                        onClick={() => setCurrentPage(p => Math.min(totalPages - 1, p + 1))}
                        disabled={currentPage >= totalPages - 1}
                        className={`p-1 rounded disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${isDark ? "text-gray-300 hover:bg-gray-700" : "text-gray-600 hover:bg-gray-100"}`}
                      >
                        <ChevronRight className="w-5 h-5" />
                      </button>
                    </div>
                  </div>
                </div>
                )
              ) : (
                <div className="flex-1 overflow-auto">
                  <div className="grid grid-cols-2 gap-4 h-full" style={{ minHeight: 400 }}>
                    {/* Section 1: Per-alert firing timeline as line graph */}
                    <div className="min-h-0" style={{ minHeight: 400 }}>
                      <AlertsMultiLineGraphSection
                        title="Alert Timeline"
                            data={s1Data ?? { points: [], seriesKeys: [] }}
                        loading={loading}
                        error={error}
                        hideYAxis
                      />
                    </div>
                    {/* Section 2: COUNT by alert_sla_name multi-line graph */}
                    <div className="min-h-0" style={{ minHeight: 400 }}>
                      <AlertsMultiLineGraphSection
                        title="Alerts by SLA Name"
                            data={graphData ?? { points: [], seriesKeys: [] }}
                        loading={graphLoading}
                        error={graphError}
                        yAxisLabel="Count"
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={`px-4 py-3 border-t ${isDark ? "border-gray-700 bg-gray-800" : "border-gray-200 bg-gray-50"}`}>
          <button
            onClick={handleRefresh}
            disabled={loading || refreshing}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-[#002244] text-white rounded-lg hover:bg-[#003366] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <p className={`text-xs text-center mt-2 ${isDark ? "text-gray-500" : "text-gray-500"}`}>
            Last {timeLabel} • Updated {new Date().toLocaleTimeString()}
          </p>
        </div>
      </aside>

      {/* Info Dialog */}
      {infoMessage && (
        <AlertInfoDialog message={infoMessage} onClose={() => setInfoMessage(null)} isDark={isDark} />
      )}

      {/* Expanded View */}
      {expandedView && (
        <ExpandedView
          alerts={sortedAlerts}
          appName={getAppName()}
          alertCount={sortedAlerts.length}
          timeValue={draftValue}
          timeUnit={draftUnit}
          timeStart={timeStart}
          timeEnd={timeEnd}
          onTimeValueChange={handleDraftValueChange}
          onUnitChange={handleDraftUnitChange}
          onSubmit={handleSubmit}
          loading={loading}
          refreshing={refreshing}
          onRefresh={handleRefresh}
          onClose={() => startTransition(() => setExpandedView(false))}
          onInfoClick={setInfoMessage}
          isDark={isDark}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          getAlertActive={getAlertActiveStatus}
          sort={sort}
          onSort={handleSort}
          s1Data={s1Data}
          s1Error={error}
          graphData={graphData}
          graphLoading={graphLoading}
          graphError={graphError}
        />
      )}
    </>
  );
}
