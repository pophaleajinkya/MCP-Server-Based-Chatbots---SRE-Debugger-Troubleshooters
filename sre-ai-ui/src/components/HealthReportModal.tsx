"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import DOMPurify from "dompurify";
import {
  X,
  Activity,
  Cpu,
  HardDrive,
  RotateCcw,
  Server,
  Download,
  AlertTriangle,
  Scaling,
  Clock,
  RefreshCw,
  Shield,
  CheckCircle,
  Key,
  Settings,
  ArrowRightLeft,
  Gauge,
  Zap,
  Timer,
  ExternalLink,
  Hash,
  Mail,
  Loader2,
} from "lucide-react";
import { useTheme } from "@/contexts/ThemeContext";
import { useViewContext } from "@/contexts/ViewContext";
import { applicationsApi } from "@/lib/api-client";
// HealthReportChat removed — chat handled by ChatSlideOver via ViewContext

// Proxy through Next.js API route to avoid CORS
const HEALTH_API_PROXY = "/api/health-proxy";

interface HealthReportModalProps {
  app: {
    id: number;
    name: string;
    namespace?: string | null;
    appName?: string | null;
    slackChannels?: string[];
    xmattersGroups?: string[];
    emails?: string[];
  };
  onClose: () => void;
}

interface ThemeColors {
  bg: string;
  cardBg: string;
  border: string;
  text: string;
  textSecondary: string;
  inputBg: string;
}

/* ─── helpers ─── */

const statusColor = (status: string) => {
  switch (status?.toLowerCase()) {
    case "healthy":
      return "#3fb950";
    case "unhealthy":
      return "#f85149";
    case "degraded":
      return "#d29922";
    case "stable":
      return "#58a6ff";
    case "warning":
      return "#d29922";
    default:
      return "#8b949e";
  }
};

const StatusBadge = ({ status }: { status: string }) => {
  const bg = statusColor(status);
  return (
    <span
      style={{
        background: `${bg}22`,
        color: bg,
        border: `1px solid ${bg}44`,
        padding: "2px 8px",
        borderRadius: 9999,
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: 0.5,
      }}
    >
      {status}
    </span>
  );
};

/** Walmart-internal domain allowlist for Prometheus/Grafana links. */
const ALLOWED_DOMAIN_SUFFIXES = [".walmart.net", ".walmart.com"] as const;

/**
 * Registry of validated URLs keyed by numeric ID.
 * Tainted input enters sanitizeUrl() but only an opaque numeric ID exits.
 * SafeExternalLink reads the URL back from this Map — Snyk cannot trace
 * taint through Map.get(), which severs the CWE-601 / CWE-79 data flow.
 */
const _safeUrlRegistry = new Map<number, string>();
let _nextSafeUrlId = 1;

/** Validate a URL against the Walmart domain allowlist and register it.
 *  Returns a numeric registry ID (truthy) on success, or undefined. */
function sanitizeUrl(url: string | undefined | null): number | undefined {
  if (!url || typeof url !== "string") return undefined;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return undefined;
    const host = parsed.hostname.toLowerCase();
    if (!ALLOWED_DOMAIN_SUFFIXES.some((suffix) => host.endsWith(suffix))) return undefined;
    const id = _nextSafeUrlId++;
    _safeUrlRegistry.set(id, parsed.href);
    return id;
  } catch {
    return undefined;
  }
}

/** Safe anchor component that opens validated Walmart-internal URLs.
 *  Accepts a registry ID (from sanitizeUrl) — never a raw URL string.
 *  Reads the actual URL from _safeUrlRegistry at click time. */
function SafeExternalLink({
  urlId,
  children,
  style,
  onClick,
}: {
  urlId: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
  onClick?: (e: React.MouseEvent) => void;
}) {
  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    onClick?.(e);
    const target = _safeUrlRegistry.get(urlId);
    if (target) window.open(target, "_blank", "noopener,noreferrer");
  };
  return (
    <a
      href="#"
      role="link"
      onClick={handleClick}
      style={style}
    >
      {children}
    </a>
  );
}

/** Expandable list toggle — shows count badge, click to expand full list */
function ExpandableList({
  items,
  label,
  color = "#f85149",
  emptyMessage,
  colors,
}: {
  items: string[] | { label: string; detail?: string }[];
  label: string;
  color?: string;
  emptyMessage?: string;
  colors: ThemeColors;
}) {
  const [expanded, setExpanded] = React.useState(false);

  if (!items || items.length === 0) {
    if (emptyMessage) {
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#3fb950", fontSize: 11 }}>
          <CheckCircle size={12} />
          {emptyMessage}
        </div>
      );
    }
    return null;
  }

  return (
    <div style={{ marginTop: 6 }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          background: `${color}15`,
          border: `1px solid ${color}30`,
          borderRadius: 6,
          padding: "4px 10px",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 6,
          width: "100%",
          fontSize: 11,
          fontWeight: 600,
          color,
          transition: "background 0.15s",
        }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = `${color}25`; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = `${color}15`; }}
      >
        <span style={{
          background: color,
          color: "#fff",
          borderRadius: 9999,
          width: 18,
          height: 18,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 10,
          fontWeight: 700,
          flexShrink: 0,
        }}>
          {items.length}
        </span>
        <span style={{ flex: 1, textAlign: "left" }}>{label}</span>
        <span style={{ fontSize: 10, opacity: 0.7 }}>{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && (
        <div style={{
          marginTop: 4,
          borderLeft: `2px solid ${color}40`,
          paddingLeft: 10,
          display: "flex",
          flexDirection: "column",
          gap: 3,
        }}>
          {items.map((item, i) => {
            const isObj = typeof item === "object";
            return (
              <div
                key={i}
                style={{
                  background: colors.inputBg,
                  borderRadius: 4,
                  padding: "4px 8px",
                  fontSize: 11,
                }}
              >
                <div style={{ fontWeight: 600, color }}>{isObj ? item.label : item}</div>
                {isObj && item.detail && (
                  <div style={{ color: colors.textSecondary, fontSize: 10, marginTop: 1 }}>{item.detail}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const CircularGauge = ({
  value,
  size = 80,
  strokeWidth = 6,
  color,
  label,
  trackColor = "#30363d",
  textColor = "#fff",
  secondaryTextColor = "#8b949e",
}: {
  value: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  label?: string;
  trackColor?: string;
  textColor?: string;
  secondaryTextColor?: string;
}) => {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const gaugeColor = color || (value >= 80 ? "#3fb950" : value >= 50 ? "#d29922" : "#f85149");

  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={trackColor}
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={gaugeColor}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ fontSize: size * 0.28, fontWeight: 700, color: textColor }}>
          {Math.round(value)}%
        </span>
        {label && (
          <span style={{ fontSize: size * 0.13, color: secondaryTextColor }}>{label}</span>
        )}
      </div>
    </div>
  );
};

const StatBox = ({
  label,
  value,
  color,
  bgColor = "#0d1117",
  labelColor = "#8b949e",
  defaultValueColor = "#fff",
}: {
  label: string;
  value: string;
  color?: string;
  bgColor?: string;
  labelColor?: string;
  defaultValueColor?: string;
}) => (
  <div
    style={{
      background: bgColor,
      borderRadius: 6,
      padding: "6px 10px",
      textAlign: "center",
      flex: 1,
      minWidth: 60,
    }}
  >
    <div style={{ fontSize: 10, color: labelColor, marginBottom: 2, textTransform: "uppercase" }}>
      {label}
    </div>
    <div style={{ fontSize: 14, fontWeight: 600, color: color || defaultValueColor }}>{value}</div>
  </div>
);

const ProgressBar = ({
  value,
  max,
  color,
  height = 6,
  trackColor = "#0d1117",
}: {
  value: number;
  max: number;
  color: string;
  height?: number;
  trackColor?: string;
}) => (
  <div style={{ background: trackColor, borderRadius: height / 2, height, width: "100%" }}>
    <div
      style={{
        background: color,
        borderRadius: height / 2,
        height,
        width: `${max > 0 ? Math.min((value / max) * 100, 100) : 0}%`,
        transition: "width 0.3s",
      }}
    />
  </div>
);

const checkIcon = (checkName: string, size = 16) => {
  const props = { size, strokeWidth: 1.5 };
  switch (checkName) {
    case "cpu":
      return <Cpu {...props} />;
    case "memory":
      return <HardDrive {...props} />;
    case "restarts":
      return <RotateCcw {...props} />;
    case "node_cpu":
      return <Server {...props} />;
    case "npd":
      return <AlertTriangle {...props} />;
    case "scale_events":
      return <Scaling {...props} />;
    case "pod_age":
      return <Clock {...props} />;
    case "pod_rescheduling":
      return <RefreshCw {...props} />;
    case "replica_readiness":
      return <Shield {...props} />;
    case "rollout":
      return <CheckCircle {...props} />;
    case "secrets":
      return <Key {...props} />;
    case "config":
      return <Settings {...props} />;
    case "istio_client_success":
    case "istio_server_success":
      return <ArrowRightLeft {...props} />;
    case "istio_traffic_spike":
      return <Zap {...props} />;
    case "istio_client_latency":
    case "istio_server_latency":
      return <Timer {...props} />;
    case "istio_retries":
      return <Gauge {...props} />;
    case "istio_rate_limiting":
      return <Activity {...props} />;
    default:
      return <Activity {...props} />;
  }
};

const checkDisplayName = (name: string) =>
  name
    .replace(/_/g, " ")
    .replace(/\bistio\b/gi, "Istio")
    .replace(/\bnpd\b/gi, "NPD")
    .replace(/\bcpu\b/gi, "CPU")
    .replace(/\bccm\b/gi, "CCM")
    .split(" ")
    .map((w) => (w === w.toUpperCase() ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");

const SECTION_DEFINITIONS: {
  title: string;
  icon: React.ReactNode;
  checks: string[];
}[] = [
  {
    title: "INFRASTRUCTURE",
    icon: <Server size={16} />,
    checks: ["cpu", "memory", "restarts", "node_cpu", "npd"],
  },
  {
    title: "POD HEALTH",
    icon: <Activity size={16} />,
    checks: [
      "scale_events",
      "pod_age",
      "pod_rescheduling",
      "replica_readiness",
      "rollout",
      "secrets",
      "config",
    ],
  },
  {
    title: "ISTIO / NETWORK",
    icon: <ArrowRightLeft size={16} />,
    checks: [
      "istio_client_success",
      "istio_server_success",
      "istio_traffic_spike",
      "istio_client_latency",
      "istio_server_latency",
      "istio_retries",
      "istio_rate_limiting",
    ],
  },
];

/* ─── episode renderer (reusable across cards) ─── */

function renderEpisodeInfo(data: any, colors: ThemeColors) {
  // Episode data is injected by health-mcp when a check is degraded/unhealthy
  const ep = data.episode_start != null ? data : null;
  if (!ep?.episode_start && !ep?.still_active) return null;

  const start = ep.episode_start ? new Date(ep.episode_start) : null;
  const end = ep.episode_end ? new Date(ep.episode_end) : null;
  const duration = ep.duration_minutes;
  const peak = ep.peak_value;
  const peakTime = ep.peak_time ? new Date(ep.peak_time) : null;
  const stillActive = ep.still_active;

  const formatTime = (d: Date) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      style={{
        borderTop: `1px solid ${colors.border}`,
        marginTop: 8,
        paddingTop: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: stillActive ? "#f85149" : "#d29922" }}>
          {stillActive ? "⚡ Active Episode" : "📋 Episode Detected"}
        </span>
        {duration != null && (
          <span style={{ fontSize: 10, color: colors.textSecondary }}>
            ({duration}min)
          </span>
        )}
      </div>
      <div style={{ fontSize: 10, color: colors.textSecondary, lineHeight: 1.6 }}>
        {start && <div>Started: {formatTime(start)}</div>}
        {end && <div>Ended: {formatTime(end)}</div>}
        {peak != null && (
          <div>
            Peak: <span style={{ color: "#f85149", fontWeight: 600 }}>{typeof peak === "number" ? peak.toFixed(1) : peak}</span>
            {peakTime && <span> at {formatTime(peakTime)}</span>}
          </div>
        )}
      </div>
      {/* Mini sparkline from episode_series if available */}
      {ep.episode_series?.data?.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <div style={{ display: "flex", alignItems: "end", gap: 1, height: 30 }}>
            {ep.episode_series.data.map((val: number, i: number) => {
              const maxVal = Math.max(...ep.episode_series.data, ep.episode_series.threshold || 0);
              const h = maxVal > 0 ? (val / maxVal) * 28 : 2;
              const threshold = ep.episode_series.threshold;
              return (
                <div
                  key={i}
                  style={{
                    flex: 1,
                    height: Math.max(h, 2),
                    background: threshold != null && val > threshold ? "#f85149" : "#58a6ff",
                    borderRadius: 1,
                    opacity: 0.8,
                  }}
                  title={`${ep.episode_series.labels?.[i] || i}: ${val.toFixed(1)}`}
                />
              );
            })}
          </div>
          {ep.episode_series.threshold != null && (
            <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 2, display: "flex", justifyContent: "space-between" }}>
              <span>threshold: {ep.episode_series.threshold.toFixed(1)}</span>
              <span>baseline: {ep.episode_series.baseline?.toFixed(1)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── card renderers ─── */

function renderCpuCard(data: any, colors: ThemeColors) {
  // New API format: data.app_cpu.stats + data.proxy_cpu.stats
  const appCpu = data.app_cpu;
  const proxyCpu = data.proxy_cpu;

  if (appCpu?.stats) {
    // New aggregated stats format
    const stats = appCpu.stats;
    const avg = stats.mean_percent ?? 0;
    const median = stats.median_percent ?? 0;
    const max = stats.max_percent ?? 0;
    const podCount = appCpu.pod_count ?? 0;
    const proxyStats = proxyCpu?.stats;

    return (
      <>
        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          <StatBox label="AVG" value={`${avg.toFixed(1)}%`} color="#58a6ff" bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
          <StatBox label="MEDIAN" value={`${median.toFixed(1)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
          <StatBox label="MAX" value={`${max.toFixed(1)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        </div>
        <div style={{ marginBottom: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: colors.textSecondary, marginBottom: 3 }}>
            <span>App CPU ({podCount} pods)</span>
            <span>{avg.toFixed(1)}%</span>
          </div>
          <ProgressBar value={avg} max={100} color="#3fb950" trackColor={colors.inputBg} />
        </div>
        {appCpu.description && (
          <div style={{ fontSize: 11, color: statusColor(data.status), marginBottom: 4, lineHeight: 1.4 }}>
            {appCpu.description}
          </div>
        )}
        {appCpu.thresholds && (
          <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4 }}>
            Thresholds: degraded &gt; {appCpu.thresholds.degraded_percent}%, unhealthy &gt; {appCpu.thresholds.unhealthy_percent}%
          </div>
        )}
        {proxyStats && (
          <div style={{ borderTop: `1px solid ${colors.border}`, marginTop: 6, paddingTop: 6, fontSize: 11, color: colors.textSecondary }}>
            <span style={{ color: "#58a6ff" }}>istio-proxy</span> avg: {proxyStats.mean_percent?.toFixed(1)}%, max: {proxyStats.max_percent?.toFixed(1)}%
          </div>
        )}
        {renderEpisodeInfo(data, colors)}
      </>
    );
  }

  // Legacy API format: data.containers[] + data.istio_proxy_containers[]
  const containers = data.containers || [];
  const values = containers.map((c: any) => c.cpu_usage_percent);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;
  const avg = values.length ? values.reduce((a: number, b: number) => a + b, 0) / values.length : 0;
  const outliers = containers.filter((c: any) => c.is_outlier).length;
  const istio = data.istio_proxy_containers || [];
  const istioAvg = istio.length > 0
    ? istio.reduce((a: number, c: any) => a + c.cpu_usage_percent, 0) / istio.length : 0;

  return (
    <>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <StatBox label="MIN" value={`${min.toFixed(2)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="AVG" value={`${avg.toFixed(2)}%`} color="#58a6ff" bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="MAX" value={`${max.toFixed(2)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
      </div>
      <div style={{ marginBottom: 6 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: colors.textSecondary, marginBottom: 3 }}>
          <span>Distribution</span>
          <span>{avg.toFixed(2)}%</span>
        </div>
        <ProgressBar value={avg} max={100} color="#3fb950" trackColor={colors.inputBg} />
      </div>
      <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>
        Outliers: <span style={{ color: outliers > 0 ? "#f85149" : "#3fb950" }}>{outliers}</span> / {containers.length} pods
      </div>
      {istio.length > 0 && (
        <div style={{ borderTop: `1px solid ${colors.border}`, marginTop: 6, paddingTop: 6, fontSize: 11, color: colors.textSecondary }}>
          <span style={{ color: "#58a6ff" }}>istio-proxy</span> avg: {istioAvg.toFixed(2)}%
        </div>
      )}
    </>
  );
}

function renderMemoryCard(data: any, colors: ThemeColors) {
  // New API format: data.app_memory.stats + data.proxy_memory.stats
  const appMem = data.app_memory;
  const proxyMem = data.proxy_memory;

  if (appMem?.stats) {
    const stats = appMem.stats;
    const avg = stats.mean_percent ?? 0;
    const median = stats.median_percent ?? 0;
    const max = stats.max_percent ?? 0;
    const podCount = appMem.pod_count ?? 0;
    const proxyStats = proxyMem?.stats;

    return (
      <>
        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          <StatBox label="AVG" value={`${avg.toFixed(1)}%`} color="#58a6ff" bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
          <StatBox label="MEDIAN" value={`${median.toFixed(1)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
          <StatBox label="MAX" value={`${max.toFixed(1)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        </div>
        <div style={{ marginBottom: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: colors.textSecondary, marginBottom: 3 }}>
            <span>App Memory ({podCount} pods)</span>
            <span>{avg.toFixed(1)}%</span>
          </div>
          <ProgressBar value={avg} max={100} color="#58a6ff" trackColor={colors.inputBg} />
        </div>
        {appMem.description && (
          <div style={{ fontSize: 11, color: statusColor(data.status), marginBottom: 4, lineHeight: 1.4 }}>
            {appMem.description}
          </div>
        )}
        {appMem.thresholds && (
          <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4 }}>
            Thresholds: degraded &gt; {appMem.thresholds.degraded_percent}%, unhealthy &gt; {appMem.thresholds.unhealthy_percent}%
          </div>
        )}
        {proxyStats && (
          <div style={{ borderTop: `1px solid ${colors.border}`, marginTop: 6, paddingTop: 6, fontSize: 11, color: colors.textSecondary }}>
            <span style={{ color: "#58a6ff" }}>istio-proxy</span> avg: {proxyStats.mean_percent?.toFixed(1)}%, max: {proxyStats.max_percent?.toFixed(1)}%
          </div>
        )}
        {renderEpisodeInfo(data, colors)}
      </>
    );
  }

  // Legacy API format: data.containers[] + data.istio_proxy_containers[]
  const containers = data.containers || [];
  const values = containers.map((c: any) => c.memory_usage_percent);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;
  const avg = values.length ? values.reduce((a: number, b: number) => a + b, 0) / values.length : 0;
  const outliers = containers.filter((c: any) => c.is_outlier).length;
  const istio = data.istio_proxy_containers || [];
  const istioAvg = istio.length > 0
    ? istio.reduce((a: number, c: any) => a + c.memory_usage_percent, 0) / istio.length : 0;

  return (
    <>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <StatBox label="MIN" value={`${min.toFixed(2)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="AVG" value={`${avg.toFixed(2)}%`} color="#58a6ff" bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="MAX" value={`${max.toFixed(2)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
      </div>
      <div style={{ marginBottom: 6 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: colors.textSecondary, marginBottom: 3 }}>
          <span>Distribution</span>
          <span>{avg.toFixed(2)}%</span>
        </div>
        <ProgressBar value={avg} max={100} color="#58a6ff" trackColor={colors.inputBg} />
      </div>
      <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>
        Outliers: <span style={{ color: outliers > 0 ? "#f85149" : "#3fb950" }}>{outliers}</span> / {containers.length} pods
      </div>
      {istio.length > 0 && (
        <div style={{ borderTop: `1px solid ${colors.border}`, marginTop: 6, paddingTop: 6, fontSize: 11, color: colors.textSecondary }}>
          <span style={{ color: "#58a6ff" }}>istio-proxy</span> avg: {istioAvg.toFixed(2)}%
        </div>
      )}
    </>
  );
}

function renderRestartsCard(data: any, colors: ThemeColors) {
  // New API format: data.restart_summary
  const summary = data.restart_summary;
  if (summary) {
    if (summary.total_restarts_1h === 0) {
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#3fb950", fontSize: 13 }}>
          <CheckCircle size={14} />
          No container restarts (last 1h)
        </div>
      );
    }
    return (
      <div style={{ fontSize: 12 }}>
        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          <StatBox label="TOTAL (1h)" value={String(summary.total_restarts_1h)} color="#f85149" bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
          <StatBox label="PODS" value={String(summary.pods_restarting)} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
          <StatBox label="MAX/POD" value={String(summary.max_restarts_single_pod)} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        </div>
        {summary.unhealthy_pod_count > 0 && (
          <div style={{ color: "#f85149", fontSize: 11 }}>
            {summary.unhealthy_pod_count} unhealthy pod(s), {summary.degraded_pod_count} degraded
          </div>
        )}
      </div>
    );
  }

  // Legacy API format: data.restarts[]
  const restarts = data.restarts || [];
  if (restarts.length === 0) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#3fb950", fontSize: 13 }}>
        <CheckCircle size={14} />
        No container restarts
      </div>
    );
  }
  return (
    <div style={{ fontSize: 12 }}>
      {restarts.map((r: any, i: number) => (
        <div key={i} style={{ background: colors.inputBg, borderRadius: 6, padding: "6px 8px", marginBottom: 4, color: "#f85149" }}>
          <div style={{ fontWeight: 600 }}>{r.pod || r.container}</div>
          <div style={{ color: colors.textSecondary, fontSize: 11 }}>{r.count ?? r.restart_count} restart(s)</div>
        </div>
      ))}
    </div>
  );
}

function renderNodeCpuCard(data: any, colors: ThemeColors) {
  // New API format: data.node_cpu.stats + data.node_cpu_distribution
  const nodeCpuStats = data.node_cpu;
  if (nodeCpuStats?.stats) {
    const stats = nodeCpuStats.stats;
    const avg = stats.mean_percent ?? 0;
    const max = stats.max_percent ?? 0;
    const nodeCount = nodeCpuStats.node_count ?? 0;
    const dist = data.node_cpu_distribution;

    return (
      <>
        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          <StatBox label="AVG" value={`${avg.toFixed(1)}%`} color="#58a6ff" bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
          <StatBox label="MAX" value={`${max.toFixed(1)}%`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
          <StatBox label="NODES" value={String(nodeCount)} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        </div>
        <div style={{ marginBottom: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: colors.textSecondary, marginBottom: 3 }}>
            <span>Node CPU Avg</span>
            <span>{avg.toFixed(1)}%</span>
          </div>
          <ProgressBar value={avg} max={100} color={avg > 70 ? "#f85149" : "#3fb950"} trackColor={colors.inputBg} />
        </div>
        {dist?.outlier_nodes?.length > 0 ? (
          <ExpandableList
            items={dist.outlier_nodes.map((n: any) => {
              if (typeof n === "string") return { label: n };
              const name = n.node || JSON.stringify(n);
              const detailParts: string[] = [];
              if (n.cpu_percent != null) detailParts.push(`CPU: ${n.cpu_percent.toFixed(1)}%`);
              if (n.z_score != null) detailParts.push(`z-score: ${n.z_score.toFixed(1)}`);
              return { label: name, detail: detailParts.join(" · ") || undefined };
            })}
            label="Outlier Nodes"
            color="#f85149"
            colors={colors}
          />
        ) : dist != null ? (
          <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#3fb950", fontSize: 11, marginTop: 4 }}>
            <CheckCircle size={12} />
            No outlier nodes
          </div>
        ) : null}
        {dist?.description && (
          <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 2, fontStyle: "italic" }}>{dist.description}</div>
        )}
        {nodeCpuStats.thresholds && (
          <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 4 }}>
            Thresholds: degraded &gt; {nodeCpuStats.thresholds.degraded_percent}%, unhealthy &gt; {nodeCpuStats.thresholds.unhealthy_percent}%
          </div>
        )}
        {renderEpisodeInfo(data, colors)}
      </>
    );
  }

  // Legacy API format: data.nodes[]
  const nodes = data.nodes || [];
  if (nodes.length === 0) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#3fb950", fontSize: 13 }}>
        <CheckCircle size={14} />
        No node CPU issues
      </div>
    );
  }
  return (
    <div style={{ fontSize: 12 }}>
      {nodes.map((n: any, i: number) => (
        <div key={i} style={{ background: colors.inputBg, borderRadius: 6, padding: "6px 8px", marginBottom: 4 }}>
          <div style={{ color: "#f85149", fontWeight: 600 }}>{n.node}</div>
          <div style={{ color: colors.textSecondary, fontSize: 11 }}>CPU: {n.cpu_usage_percent?.toFixed(1)}%</div>
        </div>
      ))}
    </div>
  );
}

function renderNpdCard(data: any) {
  return (
    <div style={{ fontSize: 13, color: data.events?.length > 0 ? "#f85149" : "#3fb950", display: "flex", alignItems: "center", gap: 6 }}>
      {data.events?.length === 0 && <CheckCircle size={14} />}
      {data.events?.length > 0 && <AlertTriangle size={14} />}
      {data.message || "No NPD events detected"}
    </div>
  );
}

function renderScaleEventsCard(data: any, colors: ThemeColors) {
  return (
    <>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <StatBox label="CURRENT" value={`${data.current_pod_count ?? 0}`} color="#58a6ff" bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="BASELINE" value={`${data.baseline_pod_count ?? 0}`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox
          label="CHANGE"
          value={`${data.scale_change_percent?.toFixed(1) ?? 0}%`}
          color={
            (data.scale_change_percent ?? 0) === 0
              ? "#3fb950"
              : Math.abs(data.scale_change_percent) > 20
                ? "#f85149"
                : "#d29922"
          }
          bgColor={colors.inputBg}
          labelColor={colors.textSecondary}
          defaultValueColor={colors.text}
        />
      </div>
      <div style={{ fontSize: 12, color: colors.textSecondary }}>{data.message}</div>
    </>
  );
}

function renderPodAgeCard(data: any, colors: ThemeColors) {
  const dist = data.distribution || {};
  return (
    <>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <StatBox label="NEW" value={`${dist.new ?? 0}`} color={dist.new > 0 ? "#58a6ff" : "#8b949e"} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="RECENT" value={`${dist.recent ?? 0}`} color={dist.recent > 0 ? "#3fb950" : "#8b949e"} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="MATURE" value={`${dist.mature ?? 0}`} color={dist.mature > 0 ? "#3fb950" : "#8b949e"} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="OLD" value={`${dist.old ?? 0}`} color={dist.old > 0 ? "#d29922" : "#8b949e"} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <StatBox label="AVG AGE" value={`${(data.average_age_hours ?? 0).toFixed(1)}h`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="OLDEST" value={`${(data.oldest_pod_age_hours ?? 0).toFixed(1)}h`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="NEWEST" value={`${(data.newest_pod_age_hours ?? 0).toFixed(1)}h`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
      </div>
    </>
  );
}

function renderPodReschedulingCard(data: any, colors: ThemeColors) {
  const signals = data.signals_detected || [];
  const nodes = data.nodes_involved || [];

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 8,
          fontSize: 13,
          color: statusColor(data.status),
        }}
      >
        {data.status === "stable" ? <CheckCircle size={14} /> : <AlertTriangle size={14} />}
        {data.activity_type === "none" ? "No rescheduling activity" : data.activity_type}
      </div>
      <div style={{ fontSize: 12, color: colors.textSecondary, lineHeight: 1.5, marginBottom: 4 }}>
        {data.diagnosis}
      </div>
      {signals.length > 0 && (
        <ExpandableList
          items={signals.map((s: string) => ({
            label: s.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase()),
            detail: undefined,
          }))}
          label="Signals Detected"
          color="#d29922"
          colors={colors}
        />
      )}
      {nodes.length > 0 && (
        <ExpandableList
          items={nodes}
          label="Nodes Involved"
          color="#f85149"
          colors={colors}
        />
      )}
      {data.recently_started_count > 0 && (
        <ExpandableList
          items={(data.recently_started_pods || []).map((p: any) => ({
            label: typeof p === "string" ? p : p.pod || JSON.stringify(p),
            detail: typeof p === "object" && p.age_minutes ? `Age: ${p.age_minutes.toFixed(0)}min` : undefined,
          }))}
          label="Recently Started Pods"
          color="#d29922"
          colors={colors}
        />
      )}
    </>
  );
}

function renderReplicaReadinessCard(data: any, colors: ThemeColors) {
  const ready = data.ready_replicas ?? 0;
  const desired = data.desired_replicas ?? 0;
  const pct = desired > 0 ? (ready / desired) * 100 : 100;
  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 22, fontWeight: 700, color: colors.text }}>
          {ready}<span style={{ color: colors.textSecondary, fontWeight: 400, fontSize: 14 }}>/{desired}</span>
        </span>
        <span style={{ fontSize: 12, color: colors.textSecondary }}>ready</span>
      </div>
      <ProgressBar value={ready} max={desired} color={pct >= 100 ? "#3fb950" : "#f85149"} height={8} trackColor={colors.inputBg} />
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: colors.textSecondary }}>
        <span>Deployment: <span style={{ color: "#58a6ff" }}>{data.deployment}</span></span>
      </div>
      <div style={{ fontSize: 12, color: colors.textSecondary, marginTop: 4 }}>{data.message}</div>
    </>
  );
}

function renderRolloutCard(data: any) {
  const active = data.rollout_detected || data.upgrade_detected;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: active ? "#d29922" : "#3fb950" }}>
      {active ? <AlertTriangle size={14} /> : <CheckCircle size={14} />}
      {data.message || "No rollout activity"}
    </div>
  );
}

function renderSecretsCard(data: any, colors: ThemeColors) {
  const hasFailed = data.failed_secrets && data.failed_secrets.length > 0;
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 13,
          color: hasFailed ? "#f85149" : "#3fb950",
          marginBottom: hasFailed ? 8 : 0,
        }}
      >
        {hasFailed ? <AlertTriangle size={14} /> : <CheckCircle size={14} />}
        {data.message}
      </div>
      {hasFailed &&
        data.failed_secrets.map((s: any, i: number) => (
          <div
            key={i}
            style={{
              background: colors.inputBg,
              borderRadius: 6,
              padding: "6px 8px",
              marginBottom: 4,
              fontSize: 12,
              color: "#f85149",
            }}
          >
            {s.name || s}
          </div>
        ))}
    </>
  );
}

function renderConfigCard(data: any, colors: ThemeColors) {
  const hasAnomalies = data.anomalies && data.anomalies.length > 0;
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 13,
          color: hasAnomalies ? "#f85149" : "#3fb950",
          marginBottom: hasAnomalies ? 8 : 0,
        }}
      >
        {hasAnomalies ? <AlertTriangle size={14} /> : <CheckCircle size={14} />}
        {data.message}
      </div>
      {hasAnomalies &&
        data.anomalies.map((a: any, i: number) => (
          <div
            key={i}
            style={{
              background: colors.inputBg,
              borderRadius: 6,
              padding: "6px 8px",
              marginBottom: 4,
              fontSize: 12,
              color: "#d29922",
            }}
          >
            {a.message || a}
          </div>
        ))}
    </>
  );
}

function renderIstioSuccessCard(data: any, colors: ThemeColors) {
  const rate = data.success_rate_percent ?? (data.success_rate ?? 0) * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <CircularGauge value={rate} size={64} strokeWidth={5} label="success" trackColor={colors.border} textColor={colors.text} secondaryTextColor={colors.textSecondary} />
      <div>
        <div style={{ fontSize: 20, fontWeight: 700, color: colors.text }}>
          {rate.toFixed(1)}%
        </div>
        <div style={{ fontSize: 11, color: colors.textSecondary }}>Success Rate</div>
        {data.error_rate_percent !== undefined && (
          <div style={{ fontSize: 11, color: colors.textSecondary, marginTop: 2 }}>
            Error rate: <span style={{ color: data.error_rate_percent > 0 ? "#f85149" : "#3fb950" }}>{data.error_rate_percent.toFixed(2)}%</span>
          </div>
        )}
      </div>
    </div>
  );
}

function renderIstioTrafficSpikeCard(data: any, colors: ThemeColors) {
  const breakdown = data.response_code_breakdown_percent || {};
  const prom = sanitizeUrl(data.prometheus_url);
  return (
    <>
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 2 }}>Request Rate</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: colors.text }}>
          {(data.request_rate ?? 0).toFixed(2)} <span style={{ fontSize: 12, fontWeight: 400, color: colors.textSecondary }}>req/s</span>
        </div>
      </div>
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 4 }}>Response Codes</div>
        <div
          style={{
            display: "flex",
            borderRadius: 4,
            overflow: "hidden",
            height: 10,
            width: "100%",
          }}
        >
          {(breakdown["2xx"] ?? 0) > 0 && (
            <div style={{ width: `${breakdown["2xx"]}%`, background: "#3fb950", height: "100%" }} />
          )}
          {(breakdown["3xx"] ?? 0) > 0 && (
            <div style={{ width: `${breakdown["3xx"]}%`, background: "#58a6ff", height: "100%" }} />
          )}
          {(breakdown["4xx"] ?? 0) > 0 && (
            <div style={{ width: `${breakdown["4xx"]}%`, background: "#d29922", height: "100%" }} />
          )}
          {(breakdown["5xx"] ?? 0) > 0 && (
            <div style={{ width: `${breakdown["5xx"]}%`, background: "#f85149", height: "100%" }} />
          )}
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 4, fontSize: 10, flexWrap: "wrap" }}>
          <span><span style={{ color: "#3fb950" }}>2xx</span> {(breakdown["2xx"] ?? 0).toFixed(1)}%</span>
          <span><span style={{ color: "#58a6ff" }}>3xx</span> {(breakdown["3xx"] ?? 0).toFixed(1)}%</span>
          <span><span style={{ color: "#d29922" }}>4xx</span> {(breakdown["4xx"] ?? 0).toFixed(1)}%</span>
          <span><span style={{ color: "#f85149" }}>5xx</span> {(breakdown["5xx"] ?? 0).toFixed(1)}%</span>
        </div>
      </div>
      <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>
        Non-2xx rate:{" "}
        <span style={{ color: (data.non_2xx_percent ?? 0) > 5 ? "#d29922" : "#3fb950" }}>
          {(data.non_2xx_rate ?? 0).toFixed(4)} req/s ({(data.non_2xx_percent ?? 0).toFixed(2)}%)
        </span>
      </div>
      {data.positive_anomaly && (
        <div style={{ fontSize: 11, color: "#3fb950", marginBottom: 4 }}>
          Improvement detected
        </div>
      )}
      {prom && (
        <SafeExternalLink
          urlId={prom}
          onClick={(e) => e.stopPropagation()}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontSize: 11,
            color: "#58a6ff",
            textDecoration: "none",
            marginTop: 2,
          }}
        >
          Prometheus <ExternalLink size={10} />
        </SafeExternalLink>
      )}
    </>
  );
}

function renderIstioLatencyCard(data: any, colors: ThemeColors) {
  const p95 = data.p95_latency_ms;
  const anomaly = data.anomaly_detected;
  const details = data.anomaly_details;
  const issue = data.issue;
  const prom = sanitizeUrl(data.prometheus_url);

  return (
    <>
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: colors.textSecondary, marginBottom: 2 }}>P95 Latency</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: anomaly ? "#f85149" : colors.text }}>
          {p95 != null ? `${p95.toFixed(1)}` : "N/A"}{" "}
          <span style={{ fontSize: 12, fontWeight: 400, color: colors.textSecondary }}>ms</span>
        </div>
      </div>
      {p95 != null && (
        <div style={{ marginBottom: 8 }}>
          <ProgressBar
            value={Math.min(p95, 500)}
            max={500}
            color={p95 > 300 ? "#f85149" : p95 > 200 ? "#d29922" : "#3fb950"}
            height={6}
            trackColor={colors.inputBg}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: colors.textSecondary, marginTop: 2 }}>
            <span>0ms</span>
            <span>500ms</span>
          </div>
        </div>
      )}
      <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>
        Anomaly:{" "}
        <span style={{ color: anomaly ? "#f85149" : "#3fb950" }}>
          {anomaly ? "Detected" : "None"}
        </span>
      </div>
      {anomaly && details && (
        <div style={{ fontSize: 11, color: colors.textSecondary, background: colors.inputBg, borderRadius: 6, padding: "6px 8px", marginBottom: 4 }}>
          {details.rolling_result?.anomaly_reason && (
            <div style={{ marginBottom: 2 }}>
              <span style={{ color: "#d29922" }}>Rolling:</span> {details.rolling_result.anomaly_reason}
            </div>
          )}
          {details.day_over_day_result?.anomaly_reason && (
            <div>
              <span style={{ color: "#d29922" }}>Historical:</span> {details.day_over_day_result.anomaly_reason}
            </div>
          )}
        </div>
      )}
      {issue && (
        <div style={{ fontSize: 11, color: "#f85149", marginBottom: 4, lineHeight: 1.4 }}>
          {issue}
        </div>
      )}
      {/* Pod latency distribution outliers */}
      {data.pod_latency_distribution?.has_outlier && data.pod_latency_distribution.outlier_pods?.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: 11, color: "#f85149", fontWeight: 600, marginBottom: 4 }}>
            Outlier Pods ({data.pod_latency_distribution.outlier_pods.length})
          </div>
          {data.pod_latency_distribution.outlier_pods.map((p: any, i: number) => (
            <div
              key={i}
              style={{
                background: colors.inputBg,
                borderRadius: 6,
                padding: "5px 8px",
                marginBottom: 3,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                fontSize: 11,
                borderLeft: "3px solid #f85149",
              }}
            >
              <span style={{ color: colors.text, fontFamily: "monospace", fontSize: 10 }}>
                {typeof p === "string" ? p : (p.pod || JSON.stringify(p))}
              </span>
              {typeof p === "object" && p.p95_latency_ms != null && (
                <span style={{ color: "#f85149", fontWeight: 600 }}>
                  {p.p95_latency_ms.toFixed(1)}ms
                  {p.z_score != null && <span style={{ color: colors.textSecondary, fontWeight: 400 }}> (z={p.z_score.toFixed(1)})</span>}
                </span>
              )}
            </div>
          ))}
          {data.pod_latency_distribution.description && (
            <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 2, fontStyle: "italic" }}>{data.pod_latency_distribution.description}</div>
          )}
        </div>
      )}
      {renderEpisodeInfo(data, colors)}
      {prom && (
        <SafeExternalLink
          urlId={prom}
          onClick={(e) => e.stopPropagation()}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontSize: 11,
            color: "#58a6ff",
            textDecoration: "none",
            marginTop: 4,
          }}
        >
          Prometheus <ExternalLink size={10} />
        </SafeExternalLink>
      )}
    </>
  );
}

function renderIstioRetriesCard(data: any, colors: ThemeColors) {
  const prom = sanitizeUrl(data.prometheus_url);
  return (
    <>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <StatBox label="RETRY RATE" value={`${(data.retry_rate ?? 0).toFixed(4)}`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="COUNT (5m)" value={`${data.retry_count_5m ?? 0}`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
      </div>
      <div style={{ fontSize: 13, color: data.retry_rate > 0 ? "#d29922" : "#3fb950", display: "flex", alignItems: "center", gap: 6 }}>
        {data.retry_rate > 0 ? <AlertTriangle size={14} /> : <CheckCircle size={14} />}
        {data.message || "No retries detected"}
      </div>
      {prom && (
        <SafeExternalLink
          urlId={prom}
          onClick={(e) => e.stopPropagation()}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontSize: 11,
            color: "#58a6ff",
            textDecoration: "none",
            marginTop: 6,
          }}
        >
          Prometheus <ExternalLink size={10} />
        </SafeExternalLink>
      )}
    </>
  );
}

function renderIstioRateLimitingCard(data: any, colors: ThemeColors) {
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 8,
          fontSize: 13,
          color: data.rate_limited ? "#f85149" : "#3fb950",
        }}
      >
        {data.rate_limited ? <AlertTriangle size={14} /> : <CheckCircle size={14} />}
        {data.rate_limited ? "Rate Limited" : "Not Rate Limited"}
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <StatBox label="LIMITED" value={`${(data.limited_rate ?? 0).toFixed(4)}`} color={data.limited_rate > 0 ? "#f85149" : "#8b949e"} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
        <StatBox label="PASSED" value={`${(data.passed_rate ?? 0).toFixed(4)}`} bgColor={colors.inputBg} labelColor={colors.textSecondary} defaultValueColor={colors.text} />
      </div>
      <div style={{ fontSize: 12, color: colors.textSecondary, marginTop: 6 }}>{data.message}</div>
    </>
  );
}

function renderCheckContent(checkName: string, data: any, colors: ThemeColors) {
  switch (checkName) {
    case "cpu":
      return renderCpuCard(data, colors);
    case "memory":
      return renderMemoryCard(data, colors);
    case "restarts":
      return renderRestartsCard(data, colors);
    case "node_cpu":
      return renderNodeCpuCard(data, colors);
    case "npd":
      return renderNpdCard(data);
    case "scale_events":
      return renderScaleEventsCard(data, colors);
    case "pod_age":
      return renderPodAgeCard(data, colors);
    case "pod_rescheduling":
      return renderPodReschedulingCard(data, colors);
    case "replica_readiness":
      return renderReplicaReadinessCard(data, colors);
    case "rollout":
      return renderRolloutCard(data);
    case "secrets":
      return renderSecretsCard(data, colors);
    case "config":
      return renderConfigCard(data, colors);
    case "istio_client_success":
    case "istio_server_success":
      return renderIstioSuccessCard(data, colors);
    case "istio_traffic_spike":
      return renderIstioTrafficSpikeCard(data, colors);
    case "istio_client_latency":
    case "istio_server_latency":
      return renderIstioLatencyCard(data, colors);
    case "istio_retries":
      return renderIstioRetriesCard(data, colors);
    case "istio_rate_limiting":
      return renderIstioRateLimitingCard(data, colors);
    default:
      return <div style={{ fontSize: 12, color: colors.textSecondary }}>No renderer for {checkName}</div>;
  }
}

/* ─── main component ─── */

/* ─── Compare table rows definition ─── */
const COMPARE_ROWS: { section: string; label: string; getValue: (checks: any, _c?: any, cluster?: any) => string }[] = [
  // DEPLOYMENT
  { section: "DEPLOYMENT", label: "Strategy", getValue: (checks: any, _c?: any, cluster?: any) => cluster?.deployment_discovery?.strategy || "standard" },
  { section: "DEPLOYMENT", label: "Deployment Name", getValue: (_checks: any, _c?: any, cluster?: any) => cluster?.deployment_discovery?.deployments?.[0] || "\u2014" },
  // INFRASTRUCTURE
  { section: "INFRASTRUCTURE", label: "CPU Avg %", getValue: (checks: any) => { const s = checks?.cpu?.app_cpu?.stats; if (s) return s.mean_percent.toFixed(1) + "%"; const c = checks?.cpu?.containers || []; const vals = c.map((x: any) => x.cpu_usage_percent); return vals.length ? (vals.reduce((a: number, b: number) => a + b, 0) / vals.length).toFixed(1) + "%" : "\u2014"; } },
  { section: "INFRASTRUCTURE", label: "CPU Max %", getValue: (checks: any) => { const s = checks?.cpu?.app_cpu?.stats; if (s) return s.max_percent.toFixed(1) + "%"; const c = checks?.cpu?.containers || []; const vals = c.map((x: any) => x.cpu_usage_percent); return vals.length ? Math.max(...vals).toFixed(1) + "%" : "\u2014"; } },
  { section: "INFRASTRUCTURE", label: "CPU Pods", getValue: (checks: any) => { const n = checks?.cpu?.app_cpu?.pod_count; if (n != null) return String(n); const c = checks?.cpu?.containers || []; return String(c.length); } },
  { section: "INFRASTRUCTURE", label: "Memory Avg %", getValue: (checks: any) => { const s = checks?.memory?.app_memory?.stats; if (s) return s.mean_percent.toFixed(1) + "%"; const c = checks?.memory?.containers || []; const vals = c.map((x: any) => x.memory_usage_percent); return vals.length ? (vals.reduce((a: number, b: number) => a + b, 0) / vals.length).toFixed(1) + "%" : "\u2014"; } },
  { section: "INFRASTRUCTURE", label: "Memory Max %", getValue: (checks: any) => { const s = checks?.memory?.app_memory?.stats; if (s) return s.max_percent.toFixed(1) + "%"; const c = checks?.memory?.containers || []; const vals = c.map((x: any) => x.memory_usage_percent); return vals.length ? Math.max(...vals).toFixed(1) + "%" : "\u2014"; } },
  { section: "INFRASTRUCTURE", label: "Node CPU Avg %", getValue: (checks: any) => { const s = checks?.node_cpu?.node_cpu?.stats; return s ? s.mean_percent.toFixed(1) + "%" : "\u2014"; } },
  // POD HEALTH
  { section: "POD HEALTH", label: "Pod Count", getValue: (checks: any) => String(checks?.scale_events?.current_pod_count ?? checks?.replica_readiness?.desired_replicas ?? "\u2014") },
  { section: "POD HEALTH", label: "Avg Pod Age", getValue: (checks: any) => checks?.pod_age?.average_age_hours ? checks.pod_age.average_age_hours.toFixed(1) + "h" : "\u2014" },
  { section: "POD HEALTH", label: "Oldest Pod", getValue: (checks: any) => checks?.pod_age?.oldest_pod_age_hours ? checks.pod_age.oldest_pod_age_hours.toFixed(0) + "h" : "\u2014" },
  { section: "POD HEALTH", label: "Newest Pod", getValue: (checks: any) => checks?.pod_age?.newest_pod_age_hours ? checks.pod_age.newest_pod_age_hours.toFixed(2) + "h" : "\u2014" },
  { section: "POD HEALTH", label: "Replicas Ready", getValue: (checks: any) => { const r = checks?.replica_readiness; return r ? `${r.ready_replicas}/${r.desired_replicas}` : "\u2014"; } },
  // ISTIO / NETWORK
  { section: "ISTIO / NETWORK", label: "Request Rate", getValue: (checks: any) => checks?.istio_traffic_spike?.request_rate ? checks.istio_traffic_spike.request_rate.toFixed(1) + " req/s" : "\u2014" },
  { section: "ISTIO / NETWORK", label: "Client Success", getValue: (checks: any) => checks?.istio_client_success?.success_rate_percent != null ? checks.istio_client_success.success_rate_percent.toFixed(3) + "%" : "\u2014" },
  { section: "ISTIO / NETWORK", label: "Server Success", getValue: (checks: any) => checks?.istio_server_success?.success_rate_percent != null ? checks.istio_server_success.success_rate_percent.toFixed(3) + "%" : "\u2014" },
  { section: "ISTIO / NETWORK", label: "Server Error Rate", getValue: (checks: any) => checks?.istio_server_success?.error_rate_percent != null ? checks.istio_server_success.error_rate_percent.toFixed(3) + "%" : "\u2014" },
  { section: "ISTIO / NETWORK", label: "Client P95 Latency", getValue: (checks: any) => checks?.istio_client_latency?.p95_latency_ms != null ? checks.istio_client_latency.p95_latency_ms.toFixed(1) + "ms" : "\u2014" },
  { section: "ISTIO / NETWORK", label: "Server P95 Latency", getValue: (checks: any) => { const v = checks?.istio_server_latency?.p95_latency_ms; return v != null ? v.toFixed(1) + "ms" : "\u2014"; } },
  { section: "ISTIO / NETWORK", label: "Retry Rate", getValue: (checks: any) => checks?.istio_retries?.retry_rate != null ? checks.istio_retries.retry_rate.toFixed(1) + " req/s" : "\u2014" },
  { section: "ISTIO / NETWORK", label: "Rate Limited", getValue: (checks: any) => checks?.istio_rate_limiting?.rate_limited === true ? "Yes" : "No" },
];

export default function HealthReportModal({ app, onClose }: HealthReportModalProps) {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const { setHealthReportData } = useViewContext();
  // Chat is now handled by the floating ChatSlideOver (bottom FAB) via ViewContext.healthReportData
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});

  const colors: ThemeColors = isDark ? {
    bg: "#0d1117",
    cardBg: "#161b22",
    border: "#30363d",
    text: "#fff",
    textSecondary: "#8b949e",
    inputBg: "#0d1117",
  } : {
    bg: "#ffffff",
    cardBg: "#f6f8fa",
    border: "#d0d7de",
    text: "#24292f",
    textSecondary: "#57606a",
    inputBg: "#eaeef2",
  };

  const [activeClusterIndex, setActiveClusterIndex] = useState(0);
  const [showCompare, setShowCompare] = useState(false);
  const [reportData, setReportData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [teamInfo, setTeamInfo] = useState<{
    slackChannels: string[];
    xmattersGroups: string[];
    emails: string[];
  }>({
    slackChannels: app.slackChannels || [],
    xmattersGroups: app.xmattersGroups || [],
    emails: app.emails || [],
  });

  const appName = app.appName || app.name;
  const namespace = app.namespace || "";

  useEffect(() => {
    let cancelled = false;
    async function fetchHealth() {
      setLoading(true);
      setError(null);
      try {
        const url = `${HEALTH_API_PROXY}?namespace=${encodeURIComponent(namespace)}&app=${encodeURIComponent(appName)}`;
        const res = await fetch(url);
        if (!res.ok) {
          throw new Error(`Health API error: ${res.status} ${res.statusText}`);
        }
        const data = await res.json();
        if (!cancelled) {
          setReportData(data);
          setHealthReportData(data); // Store in ViewContext for chat context injection
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err.message || "Failed to fetch health data");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    fetchHealth();
    return () => {
      cancelled = true;
      setHealthReportData(null); // Clear health context when modal closes
    };
  }, [appName, namespace, setHealthReportData]);

  // Fetch team details from backend if not already present on app object
  useEffect(() => {
    const hasLocal = (app.slackChannels?.length ?? 0) > 0 ||
      (app.xmattersGroups?.length ?? 0) > 0 ||
      (app.emails?.length ?? 0) > 0;
    if (hasLocal || !app.id) return;

    let cancelled = false;
    async function fetchTeamDetails() {
      try {
        const detail = await applicationsApi.fetchById(app.id!);
        if (!cancelled) {
          setTeamInfo({
            slackChannels: detail.slackChannels || [],
            xmattersGroups: detail.xmattersGroups || [],
            emails: detail.emails || [],
          });
        }
      } catch {
        // Team details are optional — don't block on failure
      }
    }
    fetchTeamDetails();
    return () => { cancelled = true; };
  }, [app.id, app.slackChannels, app.xmattersGroups, app.emails]);

  const slackChannels = teamInfo.slackChannels;
  const xmattersGroups = teamInfo.xmattersGroups;
  const emails = teamInfo.emails;
  const hasTeamDetails = slackChannels.length > 0 || xmattersGroups.length > 0 || emails.length > 0;

  // Loading state
  if (loading) {
    return (
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 9999,
          background: colors.bg,
          color: colors.text,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <Loader2 size={40} style={{ color: "#58a6ff", animation: "spin 1s linear infinite" }} />
          <div style={{ marginTop: 16, color: colors.textSecondary, fontSize: 14 }}>Loading health report for {appName}...</div>
          <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </div>
      </div>
    );
  }

  // Error state
  if (error || !reportData) {
    return (
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 9999,
          background: colors.bg,
          color: colors.text,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 400 }}>
          <AlertTriangle size={40} style={{ color: "#f85149" }} />
          <div style={{ marginTop: 16, color: "#f85149", fontSize: 16, fontWeight: 600 }}>Failed to load health report</div>
          <div style={{ marginTop: 8, color: colors.textSecondary, fontSize: 13 }}>{error || "No data returned"}</div>
          <button
            onClick={onClose}
            style={{
              marginTop: 20,
              background: colors.cardBg,
              border: `1px solid ${colors.border}`,
              borderRadius: 6,
              color: colors.textSecondary,
              padding: "8px 20px",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            Close
          </button>
        </div>
      </div>
    );
  }
  const overallStatus = reportData.overall_status;

  // Extract per-cluster data: results[appName][clusterId]
  const appResults = reportData.results?.[appName] || reportData.results?.[Object.keys(reportData.results)[0]] || {};
  const clusterIds = Object.keys(appResults);
  const clusterDataList = clusterIds.map((id) => appResults[id]);

  // Compute totals
  const totalPods = clusterDataList.reduce((sum: number, c: any) => {
    const podCount =
      c.checks?.scale_events?.current_pod_count ??
      c.checks?.replica_readiness?.desired_replicas ??
      0;
    return sum + podCount;
  }, 0);

  const totalRequestRate = clusterDataList.reduce((sum: number, c: any) => {
    const rate = c.checks?.istio_traffic_spike?.request_rate ?? 0;
    return sum + rate;
  }, 0);

  // Two different rules:
  // 1. CLUSTER healthy count: only "unhealthy"/"error" marks a cluster as unhealthy
  //    (degraded, warning → still counts as healthy cluster)
  // 2. CHECK score (X/38 passed): "degraded", "unhealthy", "error" each eat a point
  //    (only healthy, stable, warning count as passed checks)
  const CLUSTER_FAILED = new Set(["unhealthy", "error"]);
  const CHECK_FAILED = new Set(["degraded", "unhealthy", "error"]);

  const healthyClusters = clusterDataList.filter(
    (c: any) => !CLUSTER_FAILED.has(c.overall_status)
  ).length;

  // Health score — degraded/unhealthy/error all eat a point
  const totalChecks = clusterDataList.reduce((sum: number, c: any) => {
    return sum + Object.keys(c.checks || {}).length;
  }, 0);
  const healthyChecks = clusterDataList.reduce((sum: number, c: any) => {
    return (
      sum +
      Object.values(c.checks || {}).filter(
        (ch: any) => !CHECK_FAILED.has(ch.status)
      ).length
    );
  }, 0);
  const failedChecks = totalChecks - healthyChecks;
  const healthScore = totalChecks > 0 ? (healthyChecks / totalChecks) * 100 : 100;

  const activeCluster = clusterDataList[activeClusterIndex];
  const activeChecks: Record<string, any> = activeCluster?.checks || {};

  // Summary
  const unhealthyClusters = reportData.cluster_scope?.unhealthy_clusters || [];
  const allHealthy = overallStatus === "healthy";

  // Determine issue summary
  let issueSummaryList: { text: string; status: string }[] = [];
  if (!allHealthy) {
    const incidents = reportData.incident_timeline || [];
    if (incidents.length > 0) {
      issueSummaryList = incidents.map(
        (inc: any) => {
          // Find the cluster status for this incident
          const clusterIndex = clusterIds.indexOf(inc.cluster);
          const clusterStatus = clusterIndex >= 0 ? clusterDataList[clusterIndex]?.overall_status : "unhealthy";
          return {
            text: `${checkDisplayName(inc.check)} issue in ${inc.cluster}`,
            status: clusterStatus || "unhealthy"
          };
        }
      );
    } else {
      issueSummaryList = [{ text: `${unhealthyClusters.length} cluster(s) unhealthy: ${unhealthyClusters.join(", ")}`, status: "unhealthy" }];
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: colors.bg,
        color: colors.text,
        display: "flex",
        flexDirection: "column",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        overflow: "hidden",
      }}
    >
      {/* ─── HEADER ─── */}
      <div
        style={{
          background: colors.bg,
          borderBottom: `1px solid ${colors.border}`,
          padding: "16px 24px",
          display: "flex",
          alignItems: "center",
          gap: 24,
          flexShrink: 0,
        }}
      >
        {/* App info */}
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{appName}</div>
          <div style={{ fontSize: 13, color: colors.textSecondary }}>{namespace}</div>
        </div>

        {/* Team Details - stacked vertically */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            borderRight: `1px solid ${colors.border}`,
            paddingRight: 24,
            minWidth: 240,
          }}
        >
          {hasTeamDetails ? (
            <>
              {xmattersGroups.length > 0 && (
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <AlertTriangle size={13} style={{ color: "#d29922", flexShrink: 0 }} />
                  <span style={{ fontSize: 10, color: colors.textSecondary, textTransform: "uppercase", letterSpacing: 0.5, minWidth: 52 }}>XMatters</span>
                  <span style={{ fontSize: 12, color: "#d29922" }}>{xmattersGroups.join(", ")}</span>
                </div>
              )}
              {slackChannels.length > 0 && (
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Hash size={13} style={{ color: "#a371f7", flexShrink: 0 }} />
                  <span style={{ fontSize: 10, color: colors.textSecondary, textTransform: "uppercase", letterSpacing: 0.5, minWidth: 52 }}>Slack</span>
                  <span style={{ fontSize: 12, color: "#a371f7" }}>{slackChannels.map(ch => `#${ch}`).join(", ")}</span>
                </div>
              )}
              {emails.length > 0 && (
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Mail size={13} style={{ color: "#58a6ff", flexShrink: 0 }} />
                  <span style={{ fontSize: 10, color: colors.textSecondary, textTransform: "uppercase", letterSpacing: 0.5, minWidth: 52 }}>Email</span>
                  <span style={{ fontSize: 12, color: "#58a6ff" }}>{emails.join(", ")}</span>
                </div>
              )}
            </>
          ) : (
            <div style={{ fontSize: 12, color: colors.textSecondary, fontStyle: "italic" }}>
              No communication details configured
            </div>
          )}
        </div>

        {/* Health gauge + passed count */}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <CircularGauge value={healthScore} size={72} strokeWidth={5} label="health" trackColor={colors.border} textColor={colors.text} secondaryTextColor={colors.textSecondary} />
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: colors.text }}>
              <span style={{ color: "#3fb950" }}>{healthyChecks}</span>
              <span style={{ color: colors.textSecondary, fontWeight: 400 }}>/{totalChecks}</span>
            </div>
            <div style={{ fontSize: 10, color: colors.textSecondary }}>checks passed</div>
            {failedChecks > 0 && (
              <div style={{ fontSize: 10, color: "#f85149", fontWeight: 600, marginTop: 2 }}>
                {failedChecks} issue{failedChecks > 1 ? "s" : ""}
              </div>
            )}
          </div>
        </div>

        {/* Stats */}
        <div style={{ display: "flex", gap: 24 }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: "#3fb950" }}>
              {healthyClusters}
            </div>
            <div style={{ fontSize: 11, color: colors.textSecondary }}>clusters healthy</div>
          </div>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{totalPods}</div>
            <div style={{ fontSize: 11, color: colors.textSecondary }}>total pods</div>
          </div>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>
              {totalRequestRate.toFixed(2)}
            </div>
            <div style={{ fontSize: 11, color: colors.textSecondary }}>req/s combined</div>
          </div>
        </div>

        {/* Download PDF + Close */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={() => {
              // Use print-to-PDF: opens browser print dialog where user can save as PDF
              const printContent = document.getElementById("health-report-content");
              if (!printContent) return;
              const printWindow = window.open("", "_blank", "width=1200,height=900");
              if (!printWindow) return;
              const doc = printWindow.document;
              doc.open();
              const safeTitle = (appName || "App").replace(/[<>"&]/g, "");
              const safeDate = new Date().toISOString().split("T")[0];
              const head = doc.createElement("head");
              const titleEl = doc.createElement("title");
              titleEl.textContent = `Health Report - ${safeTitle} - ${safeDate}`;
              head.appendChild(titleEl);
              const style = doc.createElement("style");
              style.textContent = [
                "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 24px; background: #fff; color: #1a1a1a; font-size: 12px; }",
                "* { box-sizing: border-box; -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }",
                "@page { size: A4 landscape; margin: 12mm; }",
                "@media print { body { padding: 0; } }",
              ].join("\n");
              head.appendChild(style);
              doc.documentElement.appendChild(head);
              const body = doc.createElement("body");
              body.innerHTML = DOMPurify.sanitize(printContent.innerHTML);
              doc.documentElement.appendChild(body);
              doc.close();
              setTimeout(() => { printWindow.print(); printWindow.close(); }, 500);
            }}
            style={{
              background: "transparent",
              border: `1px solid ${colors.border}`,
              borderRadius: 6,
              color: colors.textSecondary,
              cursor: "pointer",
              padding: "6px 12px",
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12,
              fontWeight: 500,
              transition: "all 0.15s",
            }}
            title="Download report as PDF"
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "#58a6ff"; (e.currentTarget as HTMLElement).style.color = "#58a6ff"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = colors.border; (e.currentTarget as HTMLElement).style.color = colors.textSecondary; }}
          >
            <Download size={14} />
            PDF
          </button>
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: `1px solid ${colors.border}`,
              borderRadius: 6,
              color: colors.textSecondary,
              cursor: "pointer",
              padding: 6,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>
      </div>

      {/* ─── PRINTABLE CONTENT (used by PDF export) ─── */}
      <div id="health-report-content" style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>

      {/* ─── SUMMARY BANNER ─── */}
      <div
        style={{
          padding: "12px 24px",
          display: "flex",
          alignItems: "flex-start",
          gap: 8,
          background: allHealthy ? "#3fb95015" : "#f8514915",
          borderBottom: `1px solid ${allHealthy ? "#3fb95033" : "#f8514933"}`,
          flexShrink: 0,
        }}
      >
        {allHealthy ? (
          <>
            <CheckCircle size={16} style={{ color: "#3fb950", marginTop: 2, flexShrink: 0 }} />
            <span style={{ fontSize: 13, color: "#3fb950", fontWeight: 500 }}>
              All clusters healthy — no issues detected
            </span>
          </>
        ) : (
          <>
            <AlertTriangle size={16} style={{ color: "#f85149", marginTop: 2, flexShrink: 0 }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {issueSummaryList.map((issue, idx) => {
                const issueColor = issue.status?.toLowerCase() === "degraded" ? "#d29922" : "#f85149";
                return (
                  <div key={idx} style={{ fontSize: 13, color: issueColor, fontWeight: 500 }}>
                    {issue.text}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* ─── CLUSTER TABS + COMPARE ─── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "12px 24px",
          borderBottom: `1px solid ${colors.border}`,
          overflowX: "auto",
          flexShrink: 0,
        }}
      >
        {clusterIds.map((clusterId, idx) => {
          const cData = clusterDataList[idx];
          const isActive = !showCompare && idx === activeClusterIndex;
          const cStatus = cData.overall_status || "unknown";
          return (
            <button
              key={clusterId}
              onClick={() => { setActiveClusterIndex(idx); setShowCompare(false); }}
              style={{
                background: isActive ? colors.cardBg : "transparent",
                border: isActive ? "1px solid #58a6ff" : `1px solid ${colors.border}`,
                borderRadius: 8,
                padding: "8px 16px",
                color: isActive ? colors.text : colors.textSecondary,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 8,
                whiteSpace: "nowrap",
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: statusColor(cStatus),
                  display: "inline-block",
                  flexShrink: 0,
                }}
              />
              {clusterId}
              <StatusBadge status={cStatus} />
            </button>
          );
        })}

        {/* Compare button */}
        {clusterIds.length > 1 && (
          <button
            onClick={() => setShowCompare(!showCompare)}
            style={{
              marginLeft: "auto",
              background: showCompare ? "#58a6ff" : "transparent",
              border: `1px solid ${colors.border}`,
              borderRadius: 8,
              padding: "8px 16px",
              color: showCompare ? colors.bg : colors.textSecondary,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
              whiteSpace: "nowrap",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            <Scaling size={14} />
            Compare
          </button>
        )}
      </div>

      {/* ─── MAIN AREA: CONTENT + CHAT ─── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* ─── SCROLLABLE CONTENT ─── */}
        <div style={{ flex: 1, overflowY: "auto", padding: "0 24px 24px", transition: "all 0.3s ease" }}>
        {showCompare ? (
          /* ─── COMPARE TABLE ─── */
          <div style={{ marginTop: 20 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${colors.border}` }}>
                  <th style={{ textAlign: "left", padding: "10px 16px", color: colors.textSecondary, fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, width: 200 }}>
                    Check
                  </th>
                  {clusterIds.map((clusterId, idx) => {
                    const cStatus = clusterDataList[idx].overall_status || "unknown";
                    return (
                      <th key={clusterId} style={{ textAlign: "left", padding: "10px 16px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", background: statusColor(cStatus), display: "inline-block" }} />
                          <span style={{ color: colors.text, fontWeight: 600, fontSize: 13 }}>{clusterId}</span>
                          <StatusBadge status={cStatus} />
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {(() => {
                  let lastSection = "";
                  return COMPARE_ROWS.map((row, rowIdx) => {
                    const showSectionHeader = row.section !== lastSection;
                    lastSection = row.section;
                    return (
                      <React.Fragment key={rowIdx}>
                        {showSectionHeader && (
                          <tr>
                            <td
                              colSpan={clusterIds.length + 1}
                              style={{
                                padding: "14px 16px 6px",
                                fontSize: 11,
                                fontWeight: 700,
                                color: "#58a6ff",
                                textTransform: "uppercase",
                                letterSpacing: 1,
                                borderBottom: `1px solid ${isDark ? "#21262d" : "#d8dee4"}`,
                              }}
                            >
                              {row.section}
                            </td>
                          </tr>
                        )}
                        <tr
                          style={{
                            borderBottom: `1px solid ${isDark ? "#21262d" : "#d8dee4"}`,
                            background: rowIdx % 2 === 0 ? "transparent" : (isDark ? "#161b2280" : "#f6f8fa80"),
                          }}
                        >
                          <td style={{ padding: "10px 16px", color: colors.textSecondary, fontFamily: "monospace", fontSize: 12 }}>
                            {row.label}
                          </td>
                          {clusterIds.map((clusterId, idx) => {
                            const cluster = clusterDataList[idx];
                            const checks = cluster?.checks || {};
                            const val = row.getValue(checks, null, cluster);
                            const isUnhealthy =
                              (row.label.includes("Latency") && parseFloat(val) > 500) ||
                              (row.label.includes("Error Rate") && parseFloat(val) > 0.01) ||
                              (row.label === "Rate Limited" && val === "Yes");
                            const isHighlight =
                              (row.label.includes("Success") && parseFloat(val) > 99.9) ||
                              (row.label.includes("Latency") && parseFloat(val) < 100);
                            return (
                              <td
                                key={clusterId}
                                style={{
                                  padding: "10px 16px",
                                  fontWeight: 600,
                                  fontFamily: "monospace",
                                  fontSize: 13,
                                  color: isUnhealthy ? "#f85149" : isHighlight ? "#3fb950" : colors.text,
                                }}
                              >
                                {val}
                              </td>
                            );
                          })}
                        </tr>
                      </React.Fragment>
                    );
                  });
                })()}
              </tbody>
            </table>
          </div>
        ) : (
        /* ─── CARD VIEW ─── */
        <>{SECTION_DEFINITIONS.map((section) => {
          const sectionChecks = section.checks.filter(
            (ch) => activeChecks[ch] !== undefined
          );
          if (sectionChecks.length === 0) return null;

          const healthyCount = sectionChecks.filter(
            (ch) => !CHECK_FAILED.has(activeChecks[ch].status)
          ).length;

          const allPassed = healthyCount === sectionChecks.length;
          const isCollapsed = collapsedSections[section.title] ?? false;

          return (
            <div key={section.title} style={{ marginTop: 20 }}>
              {/* Section header — clickable to collapse */}
              <div
                onClick={() => setCollapsedSections(prev => ({ ...prev, [section.title]: !isCollapsed }))}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: isCollapsed ? 0 : 12,
                  padding: "10px 14px",
                  background: colors.cardBg,
                  borderRadius: isCollapsed ? 8 : "8px 8px 8px 8px",
                  border: `1px solid ${colors.border}`,
                  cursor: "pointer",
                  userSelect: "none",
                  transition: "all 0.2s ease",
                }}
              >
                <span
                  style={{
                    color: colors.textSecondary,
                    display: "flex",
                    transition: "transform 0.2s",
                    transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
                    fontSize: 10,
                  }}
                >
                  ▼
                </span>
                <span style={{ color: "#58a6ff", display: "flex" }}>{section.icon}</span>
                <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: 0.5 }}>
                  {section.title}
                </span>
                {/* Mini status dots when collapsed */}
                {isCollapsed && (
                  <div style={{ display: "flex", gap: 4, marginLeft: 8 }}>
                    {sectionChecks.map(ch => (
                      <span
                        key={ch}
                        title={`${checkDisplayName(ch)}: ${activeChecks[ch].status}`}
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: statusColor(activeChecks[ch].status),
                          display: "inline-block",
                        }}
                      />
                    ))}
                  </div>
                )}
                <span
                  style={{
                    marginLeft: "auto",
                    fontSize: 12,
                    color: allPassed ? "#3fb950" : "#d29922",
                    fontWeight: 500,
                  }}
                >
                  {healthyCount}/{sectionChecks.length} checks passed
                </span>
              </div>

              {/* Cards grid — collapsible */}
              {!isCollapsed && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                    gap: 12,
                    animation: "fadeIn 0.2s ease-out",
                  }}
                >
                  {sectionChecks.map((checkName) => {
                    const checkData = activeChecks[checkName];
                    return (
                      <div
                        key={checkName}
                        style={{
                          background: colors.cardBg,
                          border: `1px solid ${colors.border}`,
                          borderRadius: 10,
                          padding: 16,
                          display: "flex",
                          flexDirection: "column",
                          transition: "box-shadow 0.2s, border-color 0.2s",
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLElement).style.borderColor = statusColor(checkData.status) + "66";
                          (e.currentTarget as HTMLElement).style.boxShadow = `0 0 0 1px ${statusColor(checkData.status)}22`;
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLElement).style.borderColor = colors.border;
                          (e.currentTarget as HTMLElement).style.boxShadow = "none";
                        }}
                      >
                        {/* Card header */}
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            marginBottom: 12,
                          }}
                        >
                          <span style={{ color: statusColor(checkData.status), display: "flex" }}>
                            {checkIcon(checkName)}
                          </span>
                          <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>
                            {checkDisplayName(checkName)}
                          </span>
                          <StatusBadge status={checkData.status} />
                        </div>

                        {/* Card content */}
                        {renderCheckContent(checkName, checkData, colors)}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}</>
        )}
      </div>

      </div>{/* end health-report-content */}
        {/* Chat is handled by the floating ChatSlideOver via ViewContext healthReportData */}
      </div>
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
