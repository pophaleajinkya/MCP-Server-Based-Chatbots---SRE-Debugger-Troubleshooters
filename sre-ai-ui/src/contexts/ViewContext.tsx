"use client";

import React, { createContext, useContext, useState, useMemo, useCallback } from "react";
import type { Application, ManagedServiceData } from "@/lib/api-client";

// ─── Types ─────────────────────────────────────────────────────────────────

type ActiveView = "chat" | "applications" | "managed-services" | "alerts" | "operations" | "approvals";

interface AppStats {
  total: number;
  active: number;
  inactive: number;
  certified: number;
  notCertified: number;
  byTenant: Record<string, number>;
  byTier: Record<string, number>;
  byType: Record<string, number>;
  /** Cross-dimensional: "Tier-0|certified", "Tier-1|notCertified", etc. */
  byTierCertified: Record<string, number>;
  /** Cross-dimensional: "Tier-0|wcnp", "Tier-1|oneops", etc. */
  byTierType: Record<string, number>;
}

interface ManagedServiceStats {
  total: number;
  byServiceType: Record<string, number>;
}

interface ApplicationFilterState {
  search: string;
  tenant: string;
  tier: string;
  certifiedStatus: "all" | "certified" | "notCertified";
}

interface ManagedServiceFilterState {
  search: string;
  serviceType: string;
}

interface ViewContextValue {
  // Current view
  activeView: ActiveView;
  setActiveView: (view: ActiveView) => void;

  // Application context
  applicationData: Application[];
  setApplicationData: (data: Application[]) => void;
  selectedApplication: Application | null;
  setSelectedApplication: (app: Application | null) => void;
  applicationFilters: ApplicationFilterState;
  setApplicationFilters: (filters: ApplicationFilterState) => void;
  filteredApplicationCount: number;
  setFilteredApplicationCount: (count: number) => void;
  appStats: AppStats;

  // Managed Services context
  managedServiceData: ManagedServiceData[];
  setManagedServiceData: (data: ManagedServiceData[]) => void;
  selectedManagedService: ManagedServiceData | null;
  setSelectedManagedService: (svc: ManagedServiceData | null) => void;
  managedServiceFilters: ManagedServiceFilterState;
  setManagedServiceFilters: (filters: ManagedServiceFilterState) => void;
  filteredManagedServiceCount: number;
  setFilteredManagedServiceCount: (count: number) => void;
  msStats: ManagedServiceStats;

  // Health report context — set when HealthReportModal fetches data
  healthReportData: any | null;
  setHealthReportData: (data: any | null) => void;

  // Context summary builder for chat injection
  getContextSummary: () => string;
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function groupAndCount<T>(items: T[], keyFn: (item: T) => string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    const key = keyFn(item) || "Unknown";
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

function formatCounts(counts: Record<string, number>): string {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k}: ${v.toLocaleString()}`)
    .join(", ");
}

/** Build a context summary of health report data for chat injection */
function summarizeHealthReport(data: any): string[] {
  const lines: string[] = [];
  lines.push("", "--- LIVE HEALTH REPORT DATA (from health-mcp endpoint) ---");
  lines.push(`Overall Status: ${data.overall_status}`);
  const scope = data.cluster_scope;
  if (scope) {
    lines.push(`Clusters: ${scope.total_clusters} total, healthy=[${(scope.healthy_clusters || []).join(", ")}], unhealthy=[${(scope.unhealthy_clusters || []).join(", ")}]`);
  }
  lines.push(`Total Checks: ${data.total_checks || "N/A"}`);
  const summary = data.summary;
  if (summary) {
    lines.push(`Summary: healthy=${summary.healthy}, degraded=${summary.degraded}, unhealthy=${summary.unhealthy}, error=${summary.error}`);
  }

  const results = data.results || {};
  for (const appKey of Object.keys(results)) {
    const clusters = results[appKey] || {};
    for (const clusterId of Object.keys(clusters)) {
      const cluster = clusters[clusterId];
      const checks = cluster?.checks || {};
      const issues: string[] = [];
      for (const [checkName, checkData] of Object.entries(checks) as [string, any][]) {
        const st = checkData.status?.toLowerCase();
        // Only "unhealthy" and "error" are true failures — degraded/warning are not negative
        if (st === "unhealthy" || st === "error") {
          let detail = `${checkName}: ${checkData.status}`;
          if (checkName === "cpu" || checkName === "memory") {
            const containers = checkData.containers || [];
            const vals = containers.map((c: any) => c.cpu_usage_percent ?? c.memory_usage_percent);
            if (vals.length) {
              const avg = vals.reduce((a: number, b: number) => a + b, 0) / vals.length;
              const max = Math.max(...vals);
              detail += ` (avg=${avg.toFixed(1)}%, max=${max.toFixed(1)}%)`;
            }
          } else if (checkName.includes("latency")) {
            detail += ` (p95=${checkData.p95_latency_ms?.toFixed(1)}ms)`;
          } else if (checkName.includes("success")) {
            detail += ` (rate=${(checkData.success_rate_percent ?? 0).toFixed(2)}%)`;
          } else if (checkName === "istio_traffic_spike") {
            detail += ` (req/s=${(checkData.request_rate ?? 0).toFixed(2)})`;
          } else if (checkData.message) {
            detail += ` — ${checkData.message}`;
          }
          issues.push(detail);
        }
      }
      if (issues.length > 0) {
        lines.push(`\nCluster ${clusterId} issues:`);
        issues.forEach(issue => lines.push(`  - ${issue}`));
      } else {
        lines.push(`\nCluster ${clusterId}: all checks healthy`);
      }
    }
  }

  const timeline = data.incident_timeline || [];
  if (timeline.length > 0) {
    lines.push("\nIncident Timeline:");
    timeline.forEach((inc: any) => lines.push(`  - ${inc.check} in ${inc.cluster}: ${inc.description || inc.status}`));
  }
  lines.push("--- END HEALTH REPORT DATA ---");
  return lines;
}

function computeAppStats(apps: Application[]): AppStats {
  const total = apps.length;
  const active = apps.filter(a => a.active).length;
  const certified = apps.filter(a => a.certified).length;

  const byTenant = groupAndCount(apps, a => a.tenant);
  const byTier = groupAndCount(apps, a => a.tier);
  const byType = groupAndCount(apps, a => a.applicationType);

  const byTierCertified: Record<string, number> = {};
  const byTierType: Record<string, number> = {};

  for (const app of apps) {
    const tier = app.tier || "Unknown";
    const certKey = `${tier}|${app.certified ? "certified" : "notCertified"}`;
    byTierCertified[certKey] = (byTierCertified[certKey] || 0) + 1;

    const typeKey = `${tier}|${app.applicationType || "Unknown"}`;
    byTierType[typeKey] = (byTierType[typeKey] || 0) + 1;
  }

  return {
    total,
    active,
    inactive: total - active,
    certified,
    notCertified: total - certified,
    byTenant,
    byTier,
    byType,
    byTierCertified,
    byTierType,
  };
}

function computeMsStats(data: ManagedServiceData[]): ManagedServiceStats {
  return {
    total: data.length,
    byServiceType: groupAndCount(data, d => d.serviceType),
  };
}

// ─── Default values ────────────────────────────────────────────────────────

const DEFAULT_APP_FILTERS: ApplicationFilterState = {
  search: "",
  tenant: "",
  tier: "",
  certifiedStatus: "all",
};

const DEFAULT_MS_FILTERS: ManagedServiceFilterState = {
  search: "",
  serviceType: "all",
};

const EMPTY_APP_STATS: AppStats = {
  total: 0, active: 0, inactive: 0, certified: 0, notCertified: 0,
  byTenant: {}, byTier: {}, byType: {}, byTierCertified: {}, byTierType: {},
};

const EMPTY_MS_STATS: ManagedServiceStats = { total: 0, byServiceType: {} };

// ─── Context ───────────────────────────────────────────────────────────────

const ViewContext = createContext<ViewContextValue>({
  activeView: "chat",
  setActiveView: () => {},
  applicationData: [],
  setApplicationData: () => {},
  selectedApplication: null,
  setSelectedApplication: () => {},
  applicationFilters: DEFAULT_APP_FILTERS,
  setApplicationFilters: () => {},
  filteredApplicationCount: 0,
  setFilteredApplicationCount: () => {},
  appStats: EMPTY_APP_STATS,
  managedServiceData: [],
  setManagedServiceData: () => {},
  selectedManagedService: null,
  setSelectedManagedService: () => {},
  managedServiceFilters: DEFAULT_MS_FILTERS,
  setManagedServiceFilters: () => {},
  filteredManagedServiceCount: 0,
  setFilteredManagedServiceCount: () => {},
  msStats: EMPTY_MS_STATS,
  healthReportData: null,
  setHealthReportData: () => {},
  getContextSummary: () => "",
});

// ─── Provider ──────────────────────────────────────────────────────────────

export function ViewContextProvider({ children }: { children: React.ReactNode }) {
  const [activeView, setActiveView] = useState<ActiveView>("chat");

  // Application state
  const [applicationData, setApplicationData] = useState<Application[]>([]);
  const [selectedApplication, setSelectedApplication] = useState<Application | null>(null);
  const [applicationFilters, setApplicationFilters] = useState<ApplicationFilterState>(DEFAULT_APP_FILTERS);
  const [filteredApplicationCount, setFilteredApplicationCount] = useState(0);

  // Managed Services state
  const [managedServiceData, setManagedServiceData] = useState<ManagedServiceData[]>([]);
  const [selectedManagedService, setSelectedManagedService] = useState<ManagedServiceData | null>(null);
  const [managedServiceFilters, setManagedServiceFilters] = useState<ManagedServiceFilterState>(DEFAULT_MS_FILTERS);
  const [filteredManagedServiceCount, setFilteredManagedServiceCount] = useState(0);

  // Health report state — populated by HealthReportModal on fetch
  const [healthReportData, setHealthReportData] = useState<any | null>(null);

  // Pre-computed stats (useMemo — only recomputes when data changes)
  const appStats = useMemo(() =>
    applicationData.length > 0 ? computeAppStats(applicationData) : EMPTY_APP_STATS,
    [applicationData]
  );

  const msStats = useMemo(() =>
    managedServiceData.length > 0 ? computeMsStats(managedServiceData) : EMPTY_MS_STATS,
    [managedServiceData]
  );

  // Context summary builder — generates the ~200-300 token context for chat
  const getContextSummary = useCallback((): string => {
    // ── LEVEL 2: Specific application selected ──
    if (activeView === "applications" && selectedApplication) {
      const app = selectedApplication;
      const lines = [
        `User is asking about a specific application: "${app.name}".`,
        `Type: ${app.applicationType || "N/A"}`,
        `Namespace: ${app.namespace || "N/A"}, AppName: ${app.appName || "N/A"}`,
        `Tenant: ${app.tenant || "N/A"}, Tier: ${app.tier || "N/A"}`,
        `Cluster: ${app.cluster || "N/A"}`,
        `Active: ${app.active}, Certified: ${app.certified}`,
        `Team: ${app.team?.jira || "N/A"}`,
        `Slack: ${app.slackChannels?.join(", ") || "none"}`,
        `xMatters: ${app.xmattersGroups?.join(", ") || "none"}`,
        `Emails: ${app.emails?.join(", ") || "none"}`,
        app.oneOpsOrg ? `OneOps: org=${app.oneOpsOrg}, assembly=${app.oneOpsAssembly}, platform=${app.oneOpsPlatform}` : "",
      ].filter(Boolean);

      // Append health report data when the modal is open
      if (healthReportData) {
        lines.push(...summarizeHealthReport(healthReportData));
      }

      return lines.join("\n");
    }

    // ── LEVEL 1: On Applications tab, no selection ──
    if (activeView === "applications") {
      // Handle empty data — still tell the LLM the user is on this tab
      if (appStats.total === 0) {
        return "User is on the Applications tab. No application data is loaded yet.";
      }
      const hasFilters = applicationFilters.search || applicationFilters.tier || applicationFilters.tenant || applicationFilters.certifiedStatus !== "all";

      const lines = [
        `User is on the Applications tab.`,
        `Total: ${appStats.total.toLocaleString()} apps, Active: ${appStats.active.toLocaleString()}, Inactive: ${appStats.inactive.toLocaleString()}, Certified: ${appStats.certified.toLocaleString()}, Not Certified: ${appStats.notCertified.toLocaleString()}.`,
        `By Tier: ${formatCounts(appStats.byTier)}`,
        `By Tenant: ${formatCounts(appStats.byTenant)}`,
        `By Type: ${formatCounts(appStats.byType)}`,
        `Tier×Certified: ${formatCounts(appStats.byTierCertified)}`,
      ];

      if (hasFilters) {
        lines.push("");
        const filterParts = [];
        if (applicationFilters.search) filterParts.push(`search="${applicationFilters.search}"`);
        if (applicationFilters.tier) filterParts.push(`tier=${applicationFilters.tier}`);
        if (applicationFilters.tenant) filterParts.push(`tenant=${applicationFilters.tenant}`);
        if (applicationFilters.certifiedStatus !== "all") filterParts.push(`certified=${applicationFilters.certifiedStatus}`);
        lines.push(`Active Filters: ${filterParts.join(", ")}`);
        lines.push(`Filtered result count: ${filteredApplicationCount.toLocaleString()} applications matching these criteria.`);
      }

      lines.push(`\nFor questions about a specific app, the user should select one from the table or mention the app name.`);

      return lines.join("\n");
    }

    // ── LEVEL 2: Specific managed service selected ──
    if (activeView === "managed-services" && selectedManagedService) {
      const svc = selectedManagedService;
      return [
        `User is asking about a specific managed service: "${svc.name}".`,
        `Service Type: ${svc.serviceType || "N/A"}`,
        svc.subscriptionId ? `Subscription ID: ${svc.subscriptionId}` : "",
        svc.resourceGroup ? `Resource Group: ${svc.resourceGroup}` : "",
        svc.assembly ? `Assembly: ${svc.assembly}` : "",
        svc.platform ? `Platform: ${svc.platform}` : "",
        svc.databaseName ? `Database: ${svc.databaseName}` : "",
        svc.dns ? `DNS: ${svc.dns}` : "",
        svc.topicName ? `Topic: ${svc.topicName}` : "",
      ].filter(Boolean).join("\n");
    }

    // ── LEVEL 1: On Managed Services tab, no selection ──
    if (activeView === "managed-services") {
      if (msStats.total === 0) {
        return "User is on the Managed Services tab. No managed service data is loaded yet.";
      }
      const hasFilters = managedServiceFilters.serviceType !== "all";

      const lines = [
        `User is on the Managed Services tab.`,
        `Total: ${msStats.total.toLocaleString()} services.`,
        `By Service Type: ${formatCounts(msStats.byServiceType)}`,
      ];

      if (hasFilters) {
        lines.push("");
        lines.push(`Active Filter: serviceType=${managedServiceFilters.serviceType}`);
        lines.push(`Filtered result count: ${filteredManagedServiceCount.toLocaleString()} services matching.`);
      }

      return lines.join("\n");
    }

    // ── FALLBACK: Health report open without a selected application ──
    if (healthReportData) {
      const lines = [
        `User is viewing a Health Report.`,
        `App: ${healthReportData.app_filter || "unknown"}`,
        `Namespace: ${healthReportData.namespace || "unknown"}`,
        ...summarizeHealthReport(healthReportData),
      ];
      return lines.join("\n");
    }

    // ── No view context (chat tab or empty data) ──
    // Timezone is passed via x-user-timezone request header — not injected here.
    return "";
  }, [
    activeView,
    selectedApplication, appStats, applicationFilters, filteredApplicationCount,
    selectedManagedService, msStats, managedServiceFilters, filteredManagedServiceCount,
    healthReportData,
  ]);

  const value = useMemo<ViewContextValue>(() => ({
    activeView, setActiveView,
    applicationData, setApplicationData,
    selectedApplication, setSelectedApplication,
    applicationFilters, setApplicationFilters,
    filteredApplicationCount, setFilteredApplicationCount,
    appStats,
    managedServiceData, setManagedServiceData,
    selectedManagedService, setSelectedManagedService,
    managedServiceFilters, setManagedServiceFilters,
    filteredManagedServiceCount, setFilteredManagedServiceCount,
    msStats,
    healthReportData, setHealthReportData,
    getContextSummary,
  }), [
    activeView, applicationData, selectedApplication, applicationFilters, filteredApplicationCount, appStats,
    managedServiceData, selectedManagedService, managedServiceFilters, filteredManagedServiceCount, msStats,
    healthReportData,
    getContextSummary,
  ]);

  return (
    <ViewContext.Provider value={value}>
      {children}
    </ViewContext.Provider>
  );
}

// ─── Hook ──────────────────────────────────────────────────────────────────

export function useViewContext() {
  return useContext(ViewContext);
}
