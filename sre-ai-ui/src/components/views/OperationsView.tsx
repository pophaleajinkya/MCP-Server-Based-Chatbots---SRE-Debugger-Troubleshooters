"use client";

import React, { useState, useMemo, useCallback, useRef, useEffect } from "react";
import {
  RefreshCw,
  Download,
  Columns,
  Filter,
  AlignJustify,
  Search,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  X,
  AlertCircle,
  GitPullRequest,
  Info,
  Copy,
  List,
  Layers,
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

type DensityType = "compact" | "standard" | "comfortable";
type ActiveTab = "incidents" | "change-requests";

export type Incident = Record<string, unknown>;
export type ChangeRequest = Record<string, unknown>;

type IncidentColumnKey =
  | "incidentNumber"
  | "priority"
  | "isMajorIncident"
  | "assignedTo"
  | "openedAt"
  | "shortDescription"
  | "notes";

type CRColumnKey =
  | "crqNumber"
  | "state"
  | "assignmentGroup"
  | "plannedStartDate"
  | "plannedEndDate"
  | "shortDescription";

interface ColumnConfig<K extends string> {
  key: K;
  label: string;
  visible: boolean;
}

interface IncidentFilters {
  search: string;
  priority: string;
  state: string;
}

interface CRFilters {
  search: string;
  state: string;
  type: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

// Time-window number options per unit
const TIME_NUM_OPTIONS: Record<"minutes" | "hours", number[]> = {
  minutes: [15, 20, 25, 30, 35, 40, 45, 50, 55, 59],
  hours:   Array.from({ length: 24 }, (_, i) => i + 1), // 1 → 24
};

const DENSITY_CLASSES: Record<DensityType, { py: string; text: string }> = {
  compact:     { py: "py-1.5",  text: "text-[12px]" },
  standard:    { py: "py-2.5",  text: "text-[14px]" },
  comfortable: { py: "py-4",    text: "text-[15px]" },
};

const INCIDENT_COLUMNS: ColumnConfig<IncidentColumnKey>[] = [
  { key: "incidentNumber",  label: "Incident Number", visible: true },
  { key: "priority",        label: "Priority",        visible: true },
  { key: "isMajorIncident", label: "Major Incident",  visible: true },
  { key: "assignedTo",      label: "Assigned To",     visible: true },
  { key: "openedAt",        label: "Created At",      visible: true },
  { key: "shortDescription", label: "Summary",        visible: true },
  { key: "notes",           label: "Notes",           visible: true }, // last
];

const CR_COLUMNS: ColumnConfig<CRColumnKey>[] = [
  { key: "crqNumber",        label: "CRQ Number",        visible: true },
  { key: "state",            label: "State",             visible: true },
  { key: "shortDescription", label: "Description",       visible: true },
  { key: "plannedStartDate", label: "Planned Start Date", visible: true },
  { key: "plannedEndDate",   label: "Planned End Date",  visible: true },
  { key: "assignmentGroup",  label: "Group Name",        visible: true },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────


function str(val: unknown): string {
  if (val == null) return "—";
  if (typeof val === "object") {
    const v = val as Record<string, unknown>;
    return String(v.display_value ?? v.value ?? v.name ?? "—");
  }
  return String(val);
}

function formatDateDisplay(val: unknown): string {
  const s = str(val);
  if (s === "—") return "—";
  // Handle epoch milliseconds (numeric string or number)
  const asNum = Number(s);
  const d = !isNaN(asNum) && s.trim() !== "" ? new Date(asNum) : new Date(s);
  if (isNaN(d.getTime())) return s;
  // Compact: "Apr 9, 2026 12:30 AM"
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

/** Returns a human-readable relative time string, e.g. "3 hours ago", "45 minutes ago". */
function timeAgo(val: unknown): string {
  const s = str(val);
  if (s === "—") return "—";
  // Handle numeric epoch ms — either a raw number or a pure-digit string (13+ chars)
  const asNum = typeof val === "number" ? val : /^\d{13,}$/.test(s) ? Number(s) : NaN;
  const d = isNaN(asNum) ? new Date(s) : new Date(asNum);
  if (isNaN(d.getTime())) return s;

  const diffMs   = Date.now() - d.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHrs  = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHrs  / 24);

  if (diffSecs < 60)  return `${diffSecs} second${diffSecs !== 1 ? "s" : ""} ago`;
  if (diffMins < 60)  return `${diffMins} minute${diffMins !== 1 ? "s" : ""} ago`;
  if (diffHrs  < 24)  return `${diffHrs} hour${diffHrs   !== 1 ? "s" : ""} ago`;
  if (diffDays < 30)  return `${diffDays} day${diffDays   !== 1 ? "s" : ""} ago`;
  // Older than 30 days — fall back to a short date
  return d.toLocaleDateString();
}

/**
 * Parses and prettifies the workNotes JSON string into readable timestamped entries.
 * e.g. {"2025-03-24 04:44:37": "system (Work notes)\nThis incident was..."}
 */
function beautifyWorkNotes(workNotes: unknown): string {
  const raw = str(workNotes);
  if (raw === "—") return "—";

  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const entries = Object.entries(parsed);
    if (entries.length === 0) return raw;

    return entries
      .map(([ts, text]) => {
        const d = new Date(ts);
        const label = isNaN(d.getTime()) ? ts : d.toLocaleString();
        const body = String(text).replace(/\\n/g, "\n").trim();
        return `[${label}]\n${body}`;
      })
      .join("\n\n─────────────────────\n\n");
  } catch {
    return raw;
  }
}

/** Normalize priority display: translate any localized terms to English. */
const PRIORITY_L10N_MAP: Record<string, string> = {
  // Spanish
  "muy alto":  "Very High",
  "alto":      "High",
  "medio":     "Medium",
  "bajo":      "Low",
  "muy bajo":  "Very Low",
  // Chinese (Simplified)
  "极高":      "Very High",
  "紧急":      "Critical",
  "高":        "High",
  "中":        "Medium",
  "低":        "Low",
  "极低":      "Very Low",
  "非常低":    "Very Low",
};

function normalizePriorityDisplay(val: unknown): string {
  const raw = str(val);
  if (raw === "—") return "—";

  // Handle "N - <text>" format (e.g. "4 - 低", "5 - Muy bajo", "3 - Medio")
  const numMatch = raw.match(/^(\d+)\s*-\s*(.+)$/);
  if (numMatch) {
    const num = numMatch[1];
    const text = numMatch[2].trim();
    const english = PRIORITY_L10N_MAP[text.toLowerCase()] ?? PRIORITY_L10N_MAP[text] ?? text;
    return `${num} - ${english}`;
  }

  // Bare text (e.g. "bajo", "低", "Medium")
  return PRIORITY_L10N_MAP[raw.toLowerCase()] ?? PRIORITY_L10N_MAP[raw] ?? raw;
}

// ─── Badge Components ─────────────────────────────────────────────────────────

function PriorityBadge({ value, category }: { value: unknown; category?: unknown }) {
  // Normalize first so Spanish terms map to English before severity detection
  const normalized = normalizePriorityDisplay(value).toLowerCase();
  const num = parseInt(normalized.charAt(0));
  // Strip leading "N - " to get text portion (already in English after normalize)
  const label = normalized.replace(/^\d\s*-\s*/, "");

  // Severity from numeric prefix OR English text
  const isCritical = num === 1 || label.includes("critical") || label.includes("very high") || label.includes("p1");
  const isHigh     = num === 2 || label.includes("high")     || label.includes("p2");
  const isMedium   = num === 3 || label.includes("medium")   || label.includes("moderate") || label.includes("p3");
  const isLow      = num === 4 || label.includes("low")      || label.includes("p4");
  const isVeryLow  = num === 5 || label.includes("very low") || label.includes("p5");

  // Fallback: color by category if priority is ambiguous
  const cat = str(category).toLowerCase();
  const catIsUrgent = cat.includes("security") || cat.includes("outage") || cat.includes("critical");

  let cls = "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300";
  if (isCritical || (catIsUrgent && !isHigh && !isMedium && !isLow && !isVeryLow)) {
    cls = "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300";
  } else if (isHigh) {
    cls = "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300";
  } else if (isMedium) {
    cls = "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300";
  } else if (isLow) {
    cls = "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300";
  } else if (isVeryLow) {
    cls = "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400";
  }

  // Display the normalized (English) label
  const displayLabel = normalizePriorityDisplay(value);

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {displayLabel}
    </span>
  );
}

function StateBadge({ value }: { value: unknown }) {
  const label = str(value).toLowerCase().replace(/\s+/g, "_");
  const map: Record<string, string> = {
    new: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300",
    open: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300",
    in_progress: "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300",
    work_in_progress: "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300",
    implement: "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300",
    resolved: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300",
    closed: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300",
    completed: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300",
    cancelled: "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400",
    canceled: "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400",
    on_hold: "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300",
    planned: "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300",
    scheduled: "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300",
    review: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300",
  };
  const cls = map[label] ?? "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300";
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {str(value)}
    </span>
  );
}

// ─── Copy Button ──────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API unavailable (non-HTTPS dev context) — silent fail
    }
  };

  return (
    <button
      onClick={(e) => { e.stopPropagation(); void handleCopy(); }}
      className="flex-shrink-0 text-gray-400 hover:text-[#002244] dark:hover:text-[#90EE90] transition-colors"
      title={copied ? "Copied!" : "Copy"}
    >
      {copied
        ? <Check className="w-3.5 h-3.5 text-green-500" />
        : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}

// ─── Description Popup Modal ──────────────────────────────────────────────────

function DescriptionModal({ text, title = "Full Description", onClose }: { text: string; title?: string; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-[#30363d] bg-[#002244] rounded-t-lg">
          <h3 className="text-base font-semibold text-white">{title}</h3>
          <button
            onClick={onClose}
            className="text-white/80 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-6 py-5 overflow-y-auto">
          {!text || text === "—" ? (
            <p className="text-sm text-gray-400 dark:text-gray-500 italic text-center py-4">
              No work notes recorded for this incident.
            </p>
          ) : (
            <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap leading-relaxed">
              {text}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function OperationsView() {
  // Tab
  const [activeTab, setActiveTab] = useState<ActiveTab>("incidents");

  // Shared hours-ago param — Apply fetches both tabs at once
  const [hoursAgo, setHoursAgo] = useState(24);
  // Keep aliases so existing fetch callbacks compile unchanged
  const incHoursAgo = hoursAgo;
  const crHoursAgo = hoursAgo;

  // Data
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [changeRequests, setChangeRequests] = useState<ChangeRequest[]>([]);
  const [incidentsLoading, setIncidentsLoading] = useState(false);
  const [crLoading, setCrLoading] = useState(false);
  const [incidentsError, setIncidentsError] = useState<string | null>(null);
  const [crError, setCrError] = useState<string | null>(null);
  const [incidentsFetched, setIncidentsFetched] = useState(false);
  const [crFetched, setCrFetched] = useState(false);

  // Toolbar — incidents
  const [incColumns, setIncColumns] = useState(INCIDENT_COLUMNS);
  const [incFilters, setIncFilters] = useState<IncidentFilters>({ search: "", priority: "all", state: "all" });
  const [showIncColumnsMenu, setShowIncColumnsMenu] = useState(false);
  const [showIncFiltersPanel, setShowIncFiltersPanel] = useState(false);
  const [showIncDensityMenu, setShowIncDensityMenu] = useState(false);
  const [incDensity, setIncDensity] = useState<DensityType>("standard");
  const [incPage, setIncPage] = useState(0);
  const [incPageSize, setIncPageSize] = useState(25);
  const [incScrollMode, setIncScrollMode] = useState<"paginated" | "virtual">("paginated");

  // Toolbar — change requests
  const [crColumns, setCrColumns] = useState(CR_COLUMNS);
  const [crFilters, setCrFilters] = useState<CRFilters>({ search: "", state: "all", type: "all" });
  const [showCrColumnsMenu, setShowCrColumnsMenu] = useState(false);
  const [showCrFiltersPanel, setShowCrFiltersPanel] = useState(false);
  const [showCrDensityMenu, setShowCrDensityMenu] = useState(false);
  const [crDensity, setCrDensity] = useState<DensityType>("standard");
  const [crPage, setCrPage] = useState(0);
  const [crPageSize, setCrPageSize] = useState(25);
  const [crScrollMode, setCrScrollMode] = useState<"paginated" | "virtual">("paginated");

  // Refs for click-outside
  const incColumnsRef = useRef<HTMLDivElement>(null);
  const incDensityRef = useRef<HTMLDivElement>(null);
  const crColumnsRef = useRef<HTMLDivElement>(null);
  const crDensityRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on click outside
  React.useEffect(() => {
    function handler(e: MouseEvent) {
      if (incColumnsRef.current && !incColumnsRef.current.contains(e.target as Node)) setShowIncColumnsMenu(false);
      if (incDensityRef.current && !incDensityRef.current.contains(e.target as Node)) setShowIncDensityMenu(false);
      if (crColumnsRef.current && !crColumnsRef.current.contains(e.target as Node)) setShowCrColumnsMenu(false);
      if (crDensityRef.current && !crDensityRef.current.contains(e.target as Node)) setShowCrDensityMenu(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ── Fetch ────────────────────────────────────────────────────────────────────

  const fetchIncidents = useCallback(async () => {
    setIncidentsLoading(true);
    setIncidentsError(null);
    try {
      const url = `/api/operations/incidents?hours_ago=${incHoursAgo}`;
      const res = await fetch(url);
      if (!res.ok) {
        const errBody = await res.text().catch(() => "");
        console.error(`[Operations/Incidents] ✕ ${res.status} ${res.statusText}`);
        console.error(`[Operations/Incidents] URL: ${url}`);
        console.error(`[Operations/Incidents] Response:`, errBody.slice(0, 1000));
        throw new Error(`HTTP ${res.status}: ${errBody.slice(0, 200) || res.statusText}`);
      }
      const json = await res.json();
      const arr = Array.isArray(json) ? json : json.result ?? json.data ?? json.incidents ?? [];
      setIncidents(arr);
      setIncidentsFetched(true);
      setIncPage(0);
    } catch (err) {
      setIncidentsError(err instanceof Error ? err.message : "Failed to fetch incidents");
    } finally {
      setIncidentsLoading(false);
    }
  }, [incHoursAgo]);

  const fetchChangeRequests = useCallback(async () => {
    setCrLoading(true);
    setCrError(null);
    try {
      const url = `/api/operations/change-requests?hours_ago=${crHoursAgo}`;
      const res = await fetch(url);
      if (!res.ok) {
        const errBody = await res.text().catch(() => "");
        console.error(`[Operations/Deployments] ✕ ${res.status} ${res.statusText}`);
        console.error(`[Operations/Deployments] URL: ${url}`);
        console.error(`[Operations/Deployments] Response:`, errBody.slice(0, 1000));
        throw new Error(`HTTP ${res.status}: ${errBody.slice(0, 200) || res.statusText}`);
      }
      const json = await res.json();
      const arr = Array.isArray(json) ? json : json.crqs ?? json.result ?? json.data ?? json.change_requests ?? [];
      setChangeRequests(arr);
      setCrFetched(true);
      setCrPage(0);
    } catch (err) {
      setCrError(err instanceof Error ? err.message : "Failed to fetch deployments");
    } finally {
      setCrLoading(false);
    }
  }, [crHoursAgo]);

  // ── Filter helpers ────────────────────────────────────────────────────────────

  const filteredIncidents = useMemo(() => {
    return incidents.filter((inc) => {
      const s = incFilters.search.toLowerCase();
      const matchSearch =
        !s ||
        str(inc.incidentNumber).toLowerCase().includes(s) ||
        str(inc.shortDescription).toLowerCase().includes(s) ||
        str(inc.assignmentGroupDirectorId).toLowerCase().includes(s);
      const matchPriority = incFilters.priority === "all" || str(inc.priority).toLowerCase() === incFilters.priority.toLowerCase();
      const matchState    = incFilters.state    === "all" || str(inc.state).toLowerCase()    === incFilters.state.toLowerCase();

      return matchSearch && matchPriority && matchState;
    });
  }, [incidents, incFilters]);

  const filteredCRs = useMemo(() => {
    return changeRequests.filter((cr) => {
      const s = crFilters.search.toLowerCase();
      const matchSearch =
        !s ||
        str(cr.crqNumber).toLowerCase().includes(s) ||
        str(cr.shortDescription).toLowerCase().includes(s) ||
        str(cr.assignmentGroup).toLowerCase().includes(s);
      const matchState = crFilters.state === "all" || str(cr.state).toLowerCase() === crFilters.state.toLowerCase();
      const matchType = crFilters.type === "all" || str(cr.type).toLowerCase() === crFilters.type.toLowerCase();
      return matchSearch && matchState && matchType;
    });
  }, [changeRequests, crFilters]);

  // Unique filter options
  const incPriorityOpts = useMemo(() => [...new Set(incidents.map((i) => str(i.priority)).filter((v) => v !== "—"))], [incidents]);
  const incStateOpts = useMemo(() => [...new Set(incidents.map((i) => str(i.state)).filter((v) => v !== "—"))], [incidents]);
  const crStateOpts = useMemo(() => [...new Set(changeRequests.map((c) => str(c.state)).filter((v) => v !== "—"))], [changeRequests]);
  const crTypeOpts = useMemo(() => [...new Set(changeRequests.map((c) => str(c.type)).filter((v) => v !== "—"))], [changeRequests]);

  const hasIncActiveFilters = Boolean(
    incFilters.search || incFilters.priority !== "all" || incFilters.state !== "all"
  );
  const hasCRActiveFilters = Boolean(crFilters.search || crFilters.state !== "all" || crFilters.type !== "all");

  // Pagination
  const incTotalPages = Math.ceil(filteredIncidents.length / incPageSize);
  const incStart = incPage * incPageSize;
  const incEnd = Math.min(incStart + incPageSize, filteredIncidents.length);
  const paginatedIncidents = useMemo(() => filteredIncidents.slice(incStart, incEnd), [filteredIncidents, incStart, incEnd]);

  const crTotalPages = Math.ceil(filteredCRs.length / crPageSize);
  const crStart = crPage * crPageSize;
  const crEnd = Math.min(crStart + crPageSize, filteredCRs.length);
  const paginatedCRs = useMemo(() => filteredCRs.slice(crStart, crEnd), [filteredCRs, crStart, crEnd]);

  // Export CSV
  const handleExportIncidents = useCallback(() => {
    const visibleCols = incColumns.filter((c) => c.visible);
    const headers = visibleCols.map((c) => c.label).join(",");
    const rows = filteredIncidents.map((inc) =>
      visibleCols.map((col) => {
        let val: string;
        if      (col.key === "openedAt")        val = timeAgo(inc.startedAt ?? inc.openedAt ?? inc.createdAt);
        else if (col.key === "assignedTo")       val = str(inc.assignmentGroupDirectorId);
        else if (col.key === "isMajorIncident")  val = String(inc.isMajorIncident).toLowerCase() === "true" ? "Yes" : "No";
        else if (col.key === "notes")            val = beautifyWorkNotes(inc.workNotes);
        else val = str(inc[col.key]);
        return `"${val.replace(/"/g, '""')}"`;
      }).join(",")
    );
    downloadCsv([headers, ...rows].join("\n"), "incidents");
  }, [incColumns, filteredIncidents]);

  const handleExportCRs = useCallback(() => {
    const visibleCols = crColumns.filter((c) => c.visible);
    const headers = visibleCols.map((c) => c.label).join(",");
    const rows = filteredCRs.map((cr) => {
      const keyMap: Record<CRColumnKey, string> = {
        crqNumber:        str(cr.crqNumber),
        state:            str(cr.state),
        assignmentGroup: str(cr.assignmentGroup),
        plannedStartDate: formatDateDisplay(cr.plannedStartDate),
        plannedEndDate:   formatDateDisplay(cr.plannedEndDate),
        shortDescription: str(cr.shortDescription),
      };
      return visibleCols.map((col) => `"${(keyMap[col.key] ?? "—").replace(/"/g, '""')}"`).join(",");
    });
    downloadCsv([headers, ...rows].join("\n"), "change-requests");
  }, [crColumns, filteredCRs]);

  const isLoading = incidentsLoading || crLoading;

  // Fetch both tabs simultaneously
  const fetchBoth = useCallback(() => {
    fetchIncidents();
    fetchChangeRequests();
  }, [fetchIncidents, fetchChangeRequests]);

  // Auto-fetch on mount
  useEffect(() => {
    fetchBoth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="h-full flex flex-col bg-[#f8f9fa] dark:bg-[#0d1117]">
      <div className="flex-1 px-4 pt-3 pb-4 overflow-hidden flex flex-col">
      <div className={`flex-1 flex flex-col rounded-lg shadow-sm overflow-hidden bg-white dark:bg-[#161b22] dark:border dark:border-[#30363d]`}>

      {/* ── Row 1: Title + Search + Time Controls ── */}
      <div className="flex-shrink-0 bg-[#f8f9fa] dark:bg-[#0d1117] px-4 py-2 flex items-center gap-3 border-b border-gray-200 dark:border-[#30363d]">
        <h1 className="text-lg font-bold text-[#002244] dark:text-gray-100 whitespace-nowrap">Operations</h1>
        {/* Inline search */}
        <div className="flex items-center gap-2 px-2.5 h-7 rounded-md border w-[220px] transition-all focus-within:ring-2 bg-white dark:bg-[#161b22] border-gray-200 dark:border-[#30363d] focus-within:border-[#0071CE] focus-within:ring-[#0071CE]/10 dark:focus-within:border-blue-500 dark:focus-within:ring-blue-500/20">
          <Search className="w-3.5 h-3.5 flex-shrink-0 text-gray-400 dark:text-gray-500" />
          <input
            type="text"
            placeholder="Search all columns…"
            value={activeTab === "incidents" ? incFilters.search : crFilters.search}
            onChange={(e) =>
              activeTab === "incidents"
                ? setIncFilters((f) => ({ ...f, search: e.target.value }))
                : setCrFilters((f) => ({ ...f, search: e.target.value }))
            }
            className="flex-1 text-xs bg-transparent outline-none text-gray-800 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
          />
        </div>
        <div className="flex-1" />
        {/* Time + Apply + Refresh */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 px-2.5 h-7 rounded-md border border-gray-300 dark:border-[#30363d] bg-white dark:bg-[#21262d]">
            <span className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">Time:</span>
            <input
              type="number"
              min={1}
              max={168}
              value={hoursAgo}
              onChange={(e) => setHoursAgo(Math.max(1, Math.min(168, Number(e.target.value) || 1)))}
              className="w-10 text-sm text-center bg-transparent text-gray-900 dark:text-gray-100 focus:outline-none"
            />
            <span className="text-xs text-gray-500 dark:text-gray-400">Hours</span>
          </div>
          <button
            onClick={fetchBoth}
            disabled={isLoading}
            className="h-7 px-3 bg-[#002244] hover:bg-[#003366] text-white text-xs font-semibold rounded transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {isLoading && <RefreshCw className="w-3 h-3 animate-spin" />}
            Apply
          </button>
          <div className="h-4 w-px bg-gray-200 dark:bg-[#30363d]" />
          <button
            onClick={fetchBoth}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-2 h-7 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#21262d] rounded transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* ── Row 2: Toolbar (left) + Tab Switcher (right) ── */}
      <div className="flex-shrink-0 bg-[#f3f4f6] dark:bg-[#161b22] border-b border-gray-100 dark:border-[#30363d]/50 flex items-center">
        {activeTab === "incidents" ? (
          <Toolbar
            bare
            columns={incColumns} density={incDensity} hasActiveFilters={hasIncActiveFilters}
            showColumnsMenu={showIncColumnsMenu} showFiltersPanel={showIncFiltersPanel}
            showDensityMenu={showIncDensityMenu} columnsRef={incColumnsRef} densityRef={incDensityRef}
            filteredCount={filteredIncidents.length} totalCount={incidents.length}
            label="incidents" fetched={incidentsFetched} hideCount
            scrollMode={incScrollMode}
            onToggleColumnsMenu={() => { setShowIncColumnsMenu((v) => !v); setShowIncDensityMenu(false); }}
            onToggleFiltersPanel={() => setShowIncFiltersPanel((v) => !v)}
            onToggleDensityMenu={() => { setShowIncDensityMenu((v) => !v); setShowIncColumnsMenu(false); }}
            onToggleColumn={(k) => setIncColumns((c) => c.map((col) => col.key === k ? { ...col, visible: !col.visible } : col))}
            onSetDensity={setIncDensity}
            onToggleScrollMode={() => setIncScrollMode(m => m === "paginated" ? "virtual" : "paginated")}
            onExport={handleExportIncidents}
          />
        ) : (
          <Toolbar
            bare
            columns={crColumns} density={crDensity} hasActiveFilters={hasCRActiveFilters}
            showColumnsMenu={showCrColumnsMenu} showFiltersPanel={showCrFiltersPanel}
            showDensityMenu={showCrDensityMenu} columnsRef={crColumnsRef} densityRef={crDensityRef}
            filteredCount={filteredCRs.length} totalCount={changeRequests.length}
            label="change requests" fetched={crFetched} hideCount
            scrollMode={crScrollMode}
            onToggleColumnsMenu={() => { setShowCrColumnsMenu((v) => !v); setShowCrDensityMenu(false); }}
            onToggleFiltersPanel={() => setShowCrFiltersPanel((v) => !v)}
            onToggleDensityMenu={() => { setShowCrDensityMenu((v) => !v); setShowCrColumnsMenu(false); }}
            onToggleColumn={(k) => setCrColumns((c) => c.map((col) => col.key === k ? { ...col, visible: !col.visible } : col))}
            onSetDensity={setCrDensity}
            onToggleScrollMode={() => setCrScrollMode(m => m === "paginated" ? "virtual" : "paginated")}
            onExport={handleExportCRs}
          />
        )}
        {/* Tab switcher on right */}
        <div className="flex items-center gap-1 ml-auto px-4 py-1.5">
          <button
            onClick={() => setActiveTab("incidents")}
            className={`flex items-center gap-1.5 px-3 h-6 rounded text-xs font-medium transition-colors ${
              activeTab === "incidents"
                ? "bg-[#002244] dark:bg-[#002244] text-white"
                : "text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-[#21262d]"
            }`}
          >
            <AlertCircle className="w-3.5 h-3.5" />
            Incidents
            {incidentsFetched && (
              <span className={`ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                activeTab === "incidents"
                  ? "bg-white/20 text-white"
                  : "bg-gray-200 dark:bg-[#30363d] text-gray-600 dark:text-gray-300"
              }`}>
                {incidents.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("change-requests")}
            className={`flex items-center gap-1.5 px-3 h-6 rounded text-xs font-medium transition-colors ${
              activeTab === "change-requests"
                ? "bg-[#002244] dark:bg-[#002244] text-white"
                : "text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-[#21262d]"
            }`}
          >
            <GitPullRequest className="w-3.5 h-3.5" />
            Change Requests
            {crFetched && (
              <span className={`ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                activeTab === "change-requests"
                  ? "bg-white/20 text-white"
                  : "bg-gray-200 dark:bg-[#30363d] text-gray-600 dark:text-gray-300"
              }`}>
                {changeRequests.length}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* ── Table Content ── */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {activeTab === "incidents" ? (
          <IncidentsTable
            loading={incidentsLoading}
            error={incidentsError}
            fetched={incidentsFetched}
            data={paginatedIncidents}
            filteredCount={filteredIncidents.length}
            totalCount={incidents.length}
            columns={incColumns}
            filters={incFilters}
            density={incDensity}
            hasActiveFilters={hasIncActiveFilters}
            priorityOpts={incPriorityOpts}
            stateOpts={incStateOpts}
            pageSize={incPageSize}
            currentPage={incPage}
            totalPages={incTotalPages}
            startIndex={incStart}
            endIndex={incEnd}
            showColumnsMenu={showIncColumnsMenu}
            showFiltersPanel={showIncFiltersPanel}
            showDensityMenu={showIncDensityMenu}
            columnsRef={incColumnsRef}
            densityRef={incDensityRef}
            onToggleColumn={(k) => setIncColumns((c) => c.map((col) => col.key === k ? { ...col, visible: !col.visible } : col))}
            onSetFilters={setIncFilters}
            onClearFilters={() => setIncFilters({ search: "", priority: "all", state: "all" })}
            onSetDensity={setIncDensity}
            onSetPageSize={(s) => { setIncPageSize(s); setIncPage(0); }}
            onPrevPage={() => setIncPage((p) => Math.max(0, p - 1))}
            onNextPage={() => setIncPage((p) => Math.min(incTotalPages - 1, p + 1))}
            onToggleColumnsMenu={() => { setShowIncColumnsMenu((v) => !v); setShowIncDensityMenu(false); }}
            onToggleFiltersPanel={() => setShowIncFiltersPanel((v) => !v)}
            onToggleDensityMenu={() => { setShowIncDensityMenu((v) => !v); setShowIncColumnsMenu(false); }}
            onExport={handleExportIncidents}
            onFetch={fetchIncidents}
            hideToolbar
            scrollModeProp={incScrollMode}
          />
        ) : (
          <ChangeRequestsTable
            loading={crLoading}
            error={crError}
            fetched={crFetched}
            data={paginatedCRs}
            filteredCount={filteredCRs.length}
            totalCount={changeRequests.length}
            columns={crColumns}
            filters={crFilters}
            density={crDensity}
            hasActiveFilters={hasCRActiveFilters}
            stateOpts={crStateOpts}
            typeOpts={crTypeOpts}
            pageSize={crPageSize}
            currentPage={crPage}
            totalPages={crTotalPages}
            startIndex={crStart}
            endIndex={crEnd}
            showColumnsMenu={showCrColumnsMenu}
            showFiltersPanel={showCrFiltersPanel}
            showDensityMenu={showCrDensityMenu}
            columnsRef={crColumnsRef}
            densityRef={crDensityRef}
            onToggleColumn={(k) => setCrColumns((c) => c.map((col) => col.key === k ? { ...col, visible: !col.visible } : col))}
            onSetFilters={setCrFilters}
            onClearFilters={() => setCrFilters({ search: "", state: "all", type: "all" })}
            onSetDensity={setCrDensity}
            onSetPageSize={(s) => { setCrPageSize(s); setCrPage(0); }}
            onPrevPage={() => setCrPage((p) => Math.max(0, p - 1))}
            onNextPage={() => setCrPage((p) => Math.min(crTotalPages - 1, p + 1))}
            onToggleColumnsMenu={() => { setShowCrColumnsMenu((v) => !v); setShowCrDensityMenu(false); }}
            onToggleFiltersPanel={() => setShowCrFiltersPanel((v) => !v)}
            onToggleDensityMenu={() => { setShowCrDensityMenu((v) => !v); setShowCrColumnsMenu(false); }}
            onExport={handleExportCRs}
            onFetch={fetchChangeRequests}
            hideToolbar
            scrollModeProp={crScrollMode}
          />
        )}
      </div>
      </div>{/* card */}
      </div>{/* px-4 pt-3 pb-4 */}
    </div>
  );
}

// ─── Shared Toolbar ────────────────────────────────────────────────────────────

function Toolbar<K extends string>({
  columns,
  density,
  hasActiveFilters,
  showColumnsMenu,
  showFiltersPanel,
  showDensityMenu,
  columnsRef,
  densityRef,
  filteredCount,
  totalCount,
  label,
  fetched,
  hideCount = false,
  bare = false,
  scrollMode = "paginated",
  onToggleColumnsMenu,
  onToggleFiltersPanel,
  onToggleDensityMenu,
  onToggleColumn,
  onSetDensity,
  onToggleScrollMode,
  onExport,
}: {
  columns: ColumnConfig<K>[];
  density: DensityType;
  hasActiveFilters: boolean;
  showColumnsMenu: boolean;
  showFiltersPanel: boolean;
  showDensityMenu: boolean;
  columnsRef: React.MutableRefObject<HTMLDivElement | null>;
  densityRef: React.MutableRefObject<HTMLDivElement | null>;
  filteredCount: number;
  totalCount: number;
  label: string;
  fetched: boolean;
  hideCount?: boolean;
  bare?: boolean;
  scrollMode?: "paginated" | "virtual";
  onToggleColumnsMenu: () => void;
  onToggleFiltersPanel: () => void;
  onToggleDensityMenu: () => void;
  onToggleColumn: (key: K) => void;
  onSetDensity: (d: DensityType) => void;
  onToggleScrollMode?: () => void;
  onExport: () => void;
}) {
  return (
    <div className={bare
      ? "flex items-center gap-1.5 px-4 py-1.5"
      : "px-4 py-1.5 border-b border-gray-200 dark:border-[#30363d] bg-[#f8f9fa] dark:bg-[#161b22] flex items-center gap-1.5"
    }>
      {/* Columns */}
      <div className="relative" ref={columnsRef}>
        <button
          onClick={onToggleColumnsMenu}
          className={`h-7 flex items-center gap-1.5 px-2.5 text-[#002244] dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-[#21262d] rounded-md transition-colors text-xs font-medium ${showColumnsMenu ? "bg-gray-100 dark:bg-[#21262d]" : ""}`}
        >
          <Columns className="w-3.5 h-3.5" />
          Columns
        </button>
        {showColumnsMenu && (
          <div className="absolute top-full left-0 mt-1 bg-white dark:bg-[#21262d] rounded-lg shadow-lg border border-gray-200 dark:border-[#30363d] py-2 min-w-[180px] z-20">
            {columns.map((col) => (
              <button
                key={col.key}
                onClick={() => onToggleColumn(col.key)}
                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-[#161b22] flex items-center justify-between text-gray-900 dark:text-gray-100"
              >
                <span>{col.label}</span>
                {col.visible && <Check className="w-4 h-4 text-[#52c41a]" />}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Pages / Scroll toggle */}
      {onToggleScrollMode && (
        <button
          onClick={onToggleScrollMode}
          title={scrollMode === "paginated" ? "Switch to virtual scroll" : "Switch to pagination"}
          className="h-7 flex items-center gap-1.5 px-2.5 text-[#002244] dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-[#21262d] rounded-md transition-colors text-xs font-medium"
        >
          {scrollMode === "paginated" ? <List className="w-3.5 h-3.5" /> : <Layers className="w-3.5 h-3.5" />}
          {scrollMode === "paginated" ? "Pages" : "Scroll"}
        </button>
      )}

      {/* Density */}
      <div className="relative" ref={densityRef}>
        <button
          onClick={onToggleDensityMenu}
          className={`h-7 flex items-center gap-1.5 px-2.5 text-[#002244] dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-[#21262d] rounded-md transition-colors text-xs font-medium ${showDensityMenu ? "bg-gray-100 dark:bg-[#21262d]" : ""}`}
        >
          <AlignJustify className="w-3.5 h-3.5" />
          Density
        </button>
        {showDensityMenu && (
          <div className="absolute top-full left-0 mt-1 bg-white dark:bg-[#21262d] rounded-lg shadow-lg border border-gray-200 dark:border-[#30363d] py-2 min-w-[140px] z-20">
            {(["compact", "standard", "comfortable"] as DensityType[]).map((d) => (
              <button
                key={d}
                onClick={() => onSetDensity(d)}
                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-[#161b22] flex items-center justify-between capitalize text-gray-900 dark:text-gray-100"
              >
                <span>{d}</span>
                {density === d && <Check className="w-4 h-4 text-[#52c41a]" />}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Export */}
      <button
        onClick={onExport}
        className="h-7 flex items-center gap-1.5 px-2.5 text-[#002244] dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-[#21262d] rounded-md transition-colors text-xs font-medium"
      >
        <Download className="w-3.5 h-3.5" />
        Export
      </button>

      {/* Count — only show after first successful fetch */}
      {!hideCount && fetched && (
        <div className="ml-auto text-sm text-gray-500 dark:text-gray-400">
          {filteredCount !== totalCount && <span>{filteredCount} of </span>}
          {totalCount} {label}
        </div>
      )}
    </div>
  );
}

// ─── Pagination Footer ─────────────────────────────────────────────────────────

function PaginationFooter({
  pageSize,
  currentPage,
  totalPages,
  startIndex,
  endIndex,
  filteredCount,
  onSetPageSize,
  onPrevPage,
  onNextPage,
}: {
  pageSize: number;
  currentPage: number;
  totalPages: number;
  startIndex: number;
  endIndex: number;
  filteredCount: number;
  onSetPageSize: (s: number) => void;
  onPrevPage: () => void;
  onNextPage: () => void;
}) {
  return (
    <div className="px-4 py-3 border-t border-gray-200 dark:border-[#30363d] bg-[#fafafa] dark:bg-[#0d1117] flex items-center justify-end gap-6">
      <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
        <span>Rows per page:</span>
        <select
          value={pageSize}
          onChange={(e) => onSetPageSize(Number(e.target.value))}
          className="border border-gray-300 dark:border-[#30363d] rounded px-2 py-1 text-sm text-[#002244] dark:text-gray-100 bg-white dark:bg-[#21262d] focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500"
        >
          {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
      <div className="text-sm text-gray-600 dark:text-gray-300">
        {filteredCount === 0 ? "0–0" : `${startIndex + 1}–${endIndex}`} of {filteredCount}
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={onPrevPage}
          disabled={currentPage === 0}
          className="p-1 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#21262d] rounded disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
        <button
          onClick={onNextPage}
          disabled={currentPage >= totalPages - 1}
          className="p-1 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#21262d] rounded disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
}

// ─── Empty / Loading / Error States ───────────────────────────────────────────

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="flex flex-col items-center gap-4">
        <div className="w-12 h-12 border-4 border-[#002244] dark:border-blue-400 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-gray-400 dark:text-gray-300">Loading {label}…</p>
      </div>
    </div>
  );
}

function ErrorState({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6 max-w-md">
        <h3 className="text-red-800 dark:text-red-300 font-semibold mb-2">Error</h3>
        <p className="text-red-600 dark:text-red-400 text-sm">{error}</p>
        <button
          onClick={onRetry}
          className="mt-4 px-4 py-2 bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 rounded hover:bg-red-200 dark:hover:bg-red-900/60 transition-colors"
        >
          Try Again
        </button>
      </div>
    </div>
  );
}

function EmptyState({ fetched, label, icon }: { fetched: boolean; label: string; icon: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="text-center">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-100 dark:bg-[#21262d] flex items-center justify-center text-gray-400 dark:text-gray-500">
          {icon}
        </div>
        <p className="text-gray-500 dark:text-gray-400">
          {fetched ? `No ${label} found` : `Use the controls above to fetch ${label}`}
        </p>
      </div>
    </div>
  );
}

// ─── Incidents Table ───────────────────────────────────────────────────────────

function IncidentsTable({
  loading, error, fetched, data, filteredCount, totalCount,
  columns, filters, density, hasActiveFilters,
  priorityOpts, stateOpts,
  pageSize, currentPage, totalPages, startIndex, endIndex,
  showColumnsMenu, showFiltersPanel, showDensityMenu,
  columnsRef, densityRef,
  onToggleColumn, onSetFilters, onClearFilters, onSetDensity,
  onSetPageSize, onPrevPage, onNextPage,
  onToggleColumnsMenu, onToggleFiltersPanel, onToggleDensityMenu,
  onExport, onFetch, hideToolbar = false, scrollModeProp,
}: {
  loading: boolean; error: string | null; fetched: boolean;
  data: Incident[]; filteredCount: number; totalCount: number;
  columns: ColumnConfig<IncidentColumnKey>[];
  filters: IncidentFilters; density: DensityType; hasActiveFilters: boolean;
  priorityOpts: string[]; stateOpts: string[];
  pageSize: number; currentPage: number; totalPages: number; startIndex: number; endIndex: number;
  showColumnsMenu: boolean; showFiltersPanel: boolean; showDensityMenu: boolean;
  columnsRef: React.MutableRefObject<HTMLDivElement | null>; densityRef: React.MutableRefObject<HTMLDivElement | null>;
  onToggleColumn: (k: IncidentColumnKey) => void;
  onSetFilters: React.Dispatch<React.SetStateAction<IncidentFilters>>;
  onClearFilters: () => void;
  onSetDensity: (d: DensityType) => void;
  onSetPageSize: (s: number) => void; onPrevPage: () => void; onNextPage: () => void;
  onToggleColumnsMenu: () => void; onToggleFiltersPanel: () => void; onToggleDensityMenu: () => void;
  onExport: () => void; onFetch: () => void; hideToolbar?: boolean; scrollModeProp?: "paginated" | "virtual";
}) {
  const visibleCols = columns.filter((c) => c.visible);
  const { py: pyClass, text: textClass } = DENSITY_CLASSES[density];

  // Summary + Notes popup state
  const [summaryPopup, setSummaryPopup] = useState<string | null>(null);
  const [notesPopup, setNotesPopup] = useState<string | null>(null);

  // Column-level sort + filter state
  const [sortState, setSortState] = useState<{ col: string | null; dir: "asc" | "desc" }>({ col: null, dir: "asc" });
  const [colFilters, setColFilters] = useState<Record<string, string>>({});
  const scrollMode = scrollModeProp ?? "paginated";

  const handleSort = (col: string) => {
    setSortState(prev => prev.col === col ? { col, dir: prev.dir === "asc" ? "desc" : "asc" } : { col, dir: "asc" });
  };

  const filteredSortedData = useMemo(() => {
    let d = data;
    if (colFilters.incidentNumber) d = d.filter(r => str(r.incidentNumber).toLowerCase().includes(colFilters.incidentNumber.toLowerCase()));
    if (colFilters.assignedTo)     d = d.filter(r => str(r.assignmentGroupDirectorId).toLowerCase().includes(colFilters.assignedTo.toLowerCase()));
    if (colFilters.priority && colFilters.priority !== "all") d = d.filter(r => str(r.priority).toLowerCase().includes(colFilters.priority.toLowerCase()));
    if (colFilters.isMajorIncident && colFilters.isMajorIncident !== "all") {
      const isMaj = colFilters.isMajorIncident === "yes";
      d = d.filter(r => (String(r.isMajorIncident).toLowerCase() === "true") === isMaj);
    }
    if (sortState.col) {
      d = [...d].sort((a, b) => {
        let av: string | number = "", bv: string | number = "";
        if (sortState.col === "incidentNumber") { av = str(a.incidentNumber); bv = str(b.incidentNumber); }
        else if (sortState.col === "priority")  { av = str(a.priority); bv = str(b.priority); }
        else if (sortState.col === "assignedTo") { av = str(a.assignmentGroupDirectorId); bv = str(b.assignmentGroupDirectorId); }
        else if (sortState.col === "openedAt")  { av = new Date(str(a.startedAt ?? a.openedAt ?? a.createdAt)).getTime(); bv = new Date(str(b.startedAt ?? b.openedAt ?? b.createdAt)).getTime(); }
        if (av < bv) return sortState.dir === "asc" ? -1 : 1;
        if (av > bv) return sortState.dir === "asc" ? 1 : -1;
        return 0;
      });
    }
    return d;
  }, [data, colFilters, sortState]);

  return (
    <>
      {!hideToolbar && (
        <Toolbar
          columns={columns} density={density} hasActiveFilters={hasActiveFilters}
          showColumnsMenu={showColumnsMenu} showFiltersPanel={showFiltersPanel}
          showDensityMenu={showDensityMenu} columnsRef={columnsRef} densityRef={densityRef}
          filteredCount={filteredCount} totalCount={totalCount} label="incidents" fetched={fetched}
          scrollMode={scrollMode}
          onToggleColumnsMenu={onToggleColumnsMenu} onToggleFiltersPanel={onToggleFiltersPanel}
          onToggleDensityMenu={onToggleDensityMenu} onToggleColumn={onToggleColumn}
          onSetDensity={onSetDensity} onExport={onExport}
        />
      )}

      {/* Filters Panel */}
      {showFiltersPanel && (
        <div className="px-4 py-4 border-b border-gray-200 dark:border-[#30363d] bg-gray-50 dark:bg-[#0d1117] flex flex-wrap items-end gap-4">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Search</label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search by number, summary, category…"
                value={filters.search}
                onChange={(e) => onSetFilters((f) => ({ ...f, search: e.target.value }))}
                className="w-full pl-9 pr-4 py-2 border border-gray-300 dark:border-[#30363d] rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
              />
            </div>
          </div>
          <div className="w-[160px]">
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Priority</label>
            <select
              value={filters.priority}
              onChange={(e) => onSetFilters((f) => ({ ...f, priority: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100"
            >
              <option value="all">All Priorities</option>
              {priorityOpts.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="w-[160px]">
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">State</label>
            <select
              value={filters.state}
              onChange={(e) => onSetFilters((f) => ({ ...f, state: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100"
            >
              <option value="all">All States</option>
              {stateOpts.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          {hasActiveFilters && (
            <button onClick={onClearFilters} className="px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors flex items-center gap-1">
              <X className="w-3.5 h-3.5" /> Clear All
            </button>
          )}
        </div>
      )}

      {/* Table Body */}
      {loading ? (
        <LoadingState label="incidents" />
      ) : error ? (
        <ErrorState error={error} onRetry={onFetch} />
      ) : data.length === 0 && !hasActiveFilters ? (
        <EmptyState fetched={fetched} label="incidents" icon={<AlertCircle className="w-8 h-8" />} />
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full font-sans">
            <thead className="sticky top-0 z-10" style={{ transform: "translateZ(0)" }}>
              <tr className="bg-[#002244]">
                {visibleCols.map((col, idx) => {
                  const sortable = col.key !== "notes" && col.key !== "shortDescription";
                  return (
                    <th
                      key={col.key}
                      onClick={sortable ? () => handleSort(col.key) : undefined}
                      className={`px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap bg-[#002244] ${sortable ? "cursor-pointer group hover:bg-[#003366] transition-colors" : ""} ${sortState.col === col.key ? "!bg-[#001a33]" : ""} ${idx < visibleCols.length - 1 ? "border-r border-white/10" : ""}`}
                    >
                      <div className="flex items-center gap-1.5">
                        {col.label}
                        {sortable && (sortState.col === col.key
                          ? sortState.dir === "asc" ? <ChevronUp className="w-3.5 h-3.5 text-[#90EE90]" /> : <ChevronDown className="w-3.5 h-3.5 text-[#90EE90]" />
                          : <ChevronsUpDown className="w-3.5 h-3.5 opacity-30 group-hover:opacity-60" />
                        )}
                      </div>
                    </th>
                  );
                })}
              </tr>
              {/* ── Column filter row ── */}
              <tr className="bg-gray-50 dark:bg-[#161b22] border-b border-gray-200 dark:border-[#30363d]">
                {visibleCols.map((col) => (
                  <th key={col.key} className={`px-2 py-1 ${colFilters[col.key] ? "border-b-2 border-[#0071CE]" : ""}`}>
                    {col.key === "incidentNumber" || col.key === "assignedTo" ? (
                      <input
                        type="text"
                        placeholder="Filter..."
                        value={colFilters[col.key] ?? ""}
                        onChange={e => setColFilters(f => ({ ...f, [col.key]: e.target.value }))}
                        onClick={e => e.stopPropagation()}
                        className="w-full px-1.5 py-0.5 rounded border text-[10px] outline-none transition-colors bg-white dark:bg-[#0d1117] border-gray-200 dark:border-[#30363d] text-gray-700 dark:text-gray-200 placeholder:text-gray-400 dark:placeholder:text-gray-600 focus:border-[#0071CE] dark:focus:border-blue-500"
                      />
                    ) : col.key === "priority" ? (
                      <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                        <Filter className={`w-3 h-3 flex-shrink-0 ${colFilters.priority ? "text-[#0071CE]" : "text-gray-400"}`} />
                        <select
                          value={colFilters.priority || "all"}
                          onChange={e => setColFilters(f => ({ ...f, priority: e.target.value === "all" ? "" : e.target.value }))}
                          className="flex-1 text-[10px] bg-transparent border-none outline-none text-gray-700 dark:text-gray-200 cursor-pointer"
                        >
                          <option value="all">All</option>
                          {["1","2","3","4","5"].map(v => <option key={v} value={v}>{v}</option>)}
                        </select>
                      </div>
                    ) : col.key === "isMajorIncident" ? (
                      <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                        <Filter className={`w-3 h-3 flex-shrink-0 ${colFilters.isMajorIncident ? "text-[#0071CE]" : "text-gray-400"}`} />
                        <select
                          value={colFilters.isMajorIncident || "all"}
                          onChange={e => setColFilters(f => ({ ...f, isMajorIncident: e.target.value === "all" ? "" : e.target.value }))}
                          className="flex-1 text-[10px] bg-transparent border-none outline-none text-gray-700 dark:text-gray-200 cursor-pointer"
                        >
                          <option value="all">All</option>
                          <option value="yes">Yes</option>
                          <option value="no">No</option>
                        </select>
                      </div>
                    ) : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredSortedData.length === 0 ? (
                <tr>
                  <td colSpan={visibleCols.length} className="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                    No incidents match your filters
                  </td>
                </tr>
              ) : filteredSortedData.map((inc, index) => (
                <tr
                  key={str(inc.sys_id ?? inc.id ?? inc.incidentNumber) + index}
                  className={`border-b border-gray-100 dark:border-[#30363d] hover:bg-[#f0f6ff] dark:hover:bg-[#1c2128] transition-colors ${
                    index % 2 === 1 ? "bg-[#fafbfc] dark:bg-[#0d1117]" : "bg-white dark:bg-[#161b22]"
                  }`}
                >
                  {visibleCols.map((col) => (
                    <td key={col.key} className={`px-4 ${pyClass} ${textClass} text-[#1a1a1a] dark:text-gray-100`}>
                      {col.key === "priority" ? (
                        <PriorityBadge value={inc.priority} category={inc.category} />
                      ) : col.key === "openedAt" ? (
                        <span className="text-gray-500 dark:text-gray-400 text-xs whitespace-nowrap">
                          {timeAgo(inc.startedAt ?? inc.openedAt ?? inc.createdAt)}
                        </span>
                      ) : col.key === "incidentNumber" ? (
                        <div className="flex items-center justify-between gap-3 min-w-[150px]">
                          <span className="font-mono text-xs font-semibold text-[#002244] dark:text-blue-300">
                            {str(inc.incidentNumber)}
                          </span>
                          <CopyButton text={str(inc.incidentNumber)} />
                        </div>
                      ) : col.key === "assignedTo" ? (
                        <span className="text-sm">{str(inc.assignmentGroupDirectorId)}</span>
                      ) : col.key === "isMajorIncident" ? (
                        (() => {
                          const isMajor = String(inc.isMajorIncident).toLowerCase() === "true";
                          return (
                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                              isMajor
                                ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300"
                                : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
                            }`}>
                              {isMajor ? "Yes" : "No"}
                            </span>
                          );
                        })()
                      ) : col.key === "shortDescription" ? (
                        /* Truncated single line + info icon → popup for full text */
                        <div className="flex items-center gap-2 max-w-xs">
                          <span className="truncate text-sm whitespace-nowrap">{str(inc.shortDescription)}</span>
                          {str(inc.shortDescription) !== "—" && (
                            <button
                              onClick={() => setSummaryPopup(str(inc.shortDescription))}
                              className="flex-shrink-0 text-gray-400 hover:text-[#002244] dark:hover:text-[#90EE90] transition-colors"
                              title="View full summary"
                            >
                              <Info className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      ) : col.key === "notes" ? (
                        /* Notes from workNotes — icon only, opens beautified popup */
                        (() => {
                          const notes = beautifyWorkNotes(inc.workNotes);
                          return notes === "—" ? (
                            <span className="text-gray-400 text-xs">—</span>
                          ) : (
                            <button
                              onClick={() => setNotesPopup(notes)}
                              className="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors"
                              title="View notes"
                            >
                              <Info className="w-3.5 h-3.5" />
                              View
                            </button>
                          );
                        })()
                      ) : (
                        <span className="line-clamp-1">{str(inc[col.key])}</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {fetched && scrollMode === "paginated" && (
        <PaginationFooter
          pageSize={pageSize} currentPage={currentPage} totalPages={totalPages}
          startIndex={startIndex} endIndex={endIndex} filteredCount={filteredCount}
          onSetPageSize={onSetPageSize} onPrevPage={onPrevPage} onNextPage={onNextPage}
        />
      )}

      {/* Summary Popup */}
      {summaryPopup !== null && (
        <DescriptionModal
          title="Full Summary"
          text={summaryPopup}
          onClose={() => setSummaryPopup(null)}
        />
      )}

      {/* Notes Popup */}
      {notesPopup !== null && (
        <DescriptionModal
          title="Work Notes"
          text={notesPopup}
          onClose={() => setNotesPopup(null)}
        />
      )}
    </>
  );
}

// ─── Change Requests Table ─────────────────────────────────────────────────────

function ChangeRequestsTable({
  loading, error, fetched, data, filteredCount, totalCount,
  columns, filters, density, hasActiveFilters,
  stateOpts, typeOpts,
  pageSize, currentPage, totalPages, startIndex, endIndex,
  showColumnsMenu, showFiltersPanel, showDensityMenu,
  columnsRef, densityRef,
  onToggleColumn, onSetFilters, onClearFilters, onSetDensity,
  onSetPageSize, onPrevPage, onNextPage,
  onToggleColumnsMenu, onToggleFiltersPanel, onToggleDensityMenu,
  onExport, onFetch, hideToolbar = false, scrollModeProp,
}: {
  loading: boolean; error: string | null; fetched: boolean;
  data: ChangeRequest[]; filteredCount: number; totalCount: number;
  columns: ColumnConfig<CRColumnKey>[];
  filters: CRFilters; density: DensityType; hasActiveFilters: boolean;
  stateOpts: string[]; typeOpts: string[];
  pageSize: number; currentPage: number; totalPages: number; startIndex: number; endIndex: number;
  showColumnsMenu: boolean; showFiltersPanel: boolean; showDensityMenu: boolean;
  columnsRef: React.MutableRefObject<HTMLDivElement | null>; densityRef: React.MutableRefObject<HTMLDivElement | null>;
  onToggleColumn: (k: CRColumnKey) => void;
  onSetFilters: React.Dispatch<React.SetStateAction<CRFilters>>;
  onClearFilters: () => void;
  onSetDensity: (d: DensityType) => void;
  onSetPageSize: (s: number) => void; onPrevPage: () => void; onNextPage: () => void;
  onToggleColumnsMenu: () => void; onToggleFiltersPanel: () => void; onToggleDensityMenu: () => void;
  onExport: () => void; onFetch: () => void; hideToolbar?: boolean; scrollModeProp?: "paginated" | "virtual";
}) {
  const visibleCols = columns.filter((c) => c.visible);
  const { py: pyClass, text: textClass } = DENSITY_CLASSES[density];

  // Description popup state — local to this table
  const [descriptionPopup, setDescriptionPopup] = useState<string | null>(null);

  // Column-level sort + filter state
  const [sortState, setSortState] = useState<{ col: string | null; dir: "asc" | "desc" }>({ col: null, dir: "asc" });
  const [colFilters, setColFilters] = useState<Record<string, string>>({});
  const scrollMode = scrollModeProp ?? "paginated";

  const handleSort = (col: string) => {
    setSortState(prev => prev.col === col ? { col, dir: prev.dir === "asc" ? "desc" : "asc" } : { col, dir: "asc" });
  };

  const filteredSortedData = useMemo(() => {
    let d = data;
    if (colFilters.crqNumber)        d = d.filter(r => str(r.crqNumber).toLowerCase().includes(colFilters.crqNumber.toLowerCase()));
    if (colFilters.shortDescription) d = d.filter(r => str(r.shortDescription).toLowerCase().includes(colFilters.shortDescription.toLowerCase()));
    if (colFilters.assignmentGroup) d = d.filter(r => str(r.assignmentGroup).toLowerCase().includes(colFilters.assignmentGroup.toLowerCase()));
    if (colFilters.state && colFilters.state !== "all") d = d.filter(r => str(r.state).toLowerCase().includes(colFilters.state.toLowerCase()));
    if (sortState.col) {
      d = [...d].sort((a, b) => {
        let av: string | number = "", bv: string | number = "";
        if (sortState.col === "crqNumber")        { av = str(a.crqNumber); bv = str(b.crqNumber); }
        else if (sortState.col === "state")       { av = str(a.state); bv = str(b.state); }
        else if (sortState.col === "shortDescription") { av = str(a.shortDescription); bv = str(b.shortDescription); }
        else if (sortState.col === "assignmentGroup") { av = str(a.assignmentGroup); bv = str(b.assignmentGroup); }
        else if (sortState.col === "plannedStartDate") { av = new Date(str(a.plannedStartDate)).getTime(); bv = new Date(str(b.plannedStartDate)).getTime(); }
        else if (sortState.col === "plannedEndDate")   { av = new Date(str(a.plannedEndDate)).getTime(); bv = new Date(str(b.plannedEndDate)).getTime(); }
        if (av < bv) return sortState.dir === "asc" ? -1 : 1;
        if (av > bv) return sortState.dir === "asc" ? 1 : -1;
        return 0;
      });
    }
    return d;
  }, [data, colFilters, sortState]);

  return (
    <>
      {!hideToolbar && (
        <Toolbar
          columns={columns} density={density} hasActiveFilters={hasActiveFilters}
          showColumnsMenu={showColumnsMenu} showFiltersPanel={showFiltersPanel}
          showDensityMenu={showDensityMenu} columnsRef={columnsRef} densityRef={densityRef}
          filteredCount={filteredCount} totalCount={totalCount} label="change requests" fetched={fetched}
          scrollMode={scrollMode}
          onToggleColumnsMenu={onToggleColumnsMenu} onToggleFiltersPanel={onToggleFiltersPanel}
          onToggleDensityMenu={onToggleDensityMenu} onToggleColumn={onToggleColumn}
          onSetDensity={onSetDensity} onExport={onExport}
        />
      )}

      {/* Filters Panel */}
      {showFiltersPanel && (
        <div className="px-4 py-4 border-b border-gray-200 dark:border-[#30363d] bg-gray-50 dark:bg-[#0d1117] flex flex-wrap items-end gap-4">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Search</label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search by CRQ number, description, group…"
                value={filters.search}
                onChange={(e) => onSetFilters((f) => ({ ...f, search: e.target.value }))}
                className="w-full pl-9 pr-4 py-2 border border-gray-300 dark:border-[#30363d] rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
              />
            </div>
          </div>
          <div className="w-[160px]">
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">State</label>
            <select
              value={filters.state}
              onChange={(e) => onSetFilters((f) => ({ ...f, state: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100"
            >
              <option value="all">All States</option>
              {stateOpts.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="w-[160px]">
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Type</label>
            <select
              value={filters.type}
              onChange={(e) => onSetFilters((f) => ({ ...f, type: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100"
            >
              <option value="all">All Types</option>
              {typeOpts.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          {hasActiveFilters && (
            <button onClick={onClearFilters} className="px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors flex items-center gap-1">
              <X className="w-3.5 h-3.5" /> Clear All
            </button>
          )}
        </div>
      )}

      {/* Table Body */}
      {loading ? (
        <LoadingState label="change requests" />
      ) : error ? (
        <ErrorState error={error} onRetry={onFetch} />
      ) : data.length === 0 && !hasActiveFilters ? (
        <EmptyState fetched={fetched} label="change requests" icon={<GitPullRequest className="w-8 h-8" />} />
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full font-sans">
            <thead className="sticky top-0 z-10" style={{ transform: "translateZ(0)" }}>
              <tr className="bg-[#002244]">
                {visibleCols.map((col, idx) => (
                  <th
                    key={col.key}
                    onClick={() => ["crqNumber","state"].includes(col.key) ? undefined : handleSort(col.key)}
                    className={`px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap bg-[#002244] transition-colors ${!["crqNumber","state"].includes(col.key) ? "cursor-pointer group hover:bg-[#003366]" : ""} ${sortState.col === col.key ? "!bg-[#001a33]" : ""} ${idx < visibleCols.length - 1 ? "border-r border-white/10" : ""}`}
                  >
                    <div className="flex items-center gap-1">
                      {col.label}
                      {!["crqNumber","state"].includes(col.key) && (
                        sortState.col === col.key
                          ? sortState.dir === "asc" ? <ChevronUp className="w-3 h-3 text-[#90EE90]" /> : <ChevronDown className="w-3 h-3 text-[#90EE90]" />
                          : <ChevronsUpDown className="w-3 h-3 opacity-30 group-hover:opacity-60" />
                      )}
                    </div>
                  </th>
                ))}
              </tr>
              {/* ── Column filter row ── */}
              <tr className="bg-gray-50 dark:bg-[#161b22] border-b border-gray-200 dark:border-[#30363d]">
                {visibleCols.map((col) => (
                  <th key={col.key} className={`px-2 py-1 ${colFilters[col.key] ? "border-b-2 border-[#0071CE]" : ""}`}>
                    {col.key === "crqNumber" || col.key === "assignmentGroup" ? (
                      <input
                        type="text"
                        placeholder="Filter..."
                        value={colFilters[col.key] ?? ""}
                        onChange={e => setColFilters(f => ({ ...f, [col.key]: e.target.value }))}
                        onClick={e => e.stopPropagation()}
                        className="w-full px-1.5 py-0.5 rounded border text-[10px] outline-none transition-colors bg-white dark:bg-[#0d1117] border-gray-200 dark:border-[#30363d] text-gray-700 dark:text-gray-200 placeholder:text-gray-400 dark:placeholder:text-gray-600 focus:border-[#0071CE] dark:focus:border-blue-500"
                      />
                    ) : col.key === "state" ? (
                      <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                        <Filter className={`w-3 h-3 flex-shrink-0 ${colFilters.state ? "text-[#0071CE]" : "text-gray-400"}`} />
                        <select
                          value={colFilters.state || "all"}
                          onChange={e => setColFilters(f => ({ ...f, state: e.target.value === "all" ? "" : e.target.value }))}
                          className="flex-1 text-[10px] bg-transparent border-none outline-none text-gray-700 dark:text-gray-200 cursor-pointer"
                        >
                          <option value="all">All</option>
                          <option value="Implement">Implement</option>
                          <option value="Scheduled">Scheduled</option>
                          <option value="Closed">Closed</option>
                        </select>
                      </div>
                    ) : (
                      <span />
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredSortedData.length === 0 ? (
                <tr>
                  <td colSpan={visibleCols.length} className="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                    No change requests match your filters
                  </td>
                </tr>
              ) : filteredSortedData.map((cr, index) => (
                <tr
                  key={str(cr.sys_id ?? cr.id ?? cr.crqNumber) + index}
                  className={`border-b border-gray-100 dark:border-[#30363d] hover:bg-[#f0f6ff] dark:hover:bg-[#1c2128] transition-colors ${
                    index % 2 === 1 ? "bg-[#fafbfc] dark:bg-[#0d1117]" : "bg-white dark:bg-[#161b22]"
                  }`}
                >
                  {visibleCols.map((col) => (
                    <td key={col.key} className={`px-4 ${pyClass} ${textClass} text-[#1a1a1a] dark:text-gray-100`}>
                      {col.key === "state" ? (
                        <StateBadge value={cr.state} />
                      ) : col.key === "plannedStartDate" ? (
                        <span className="text-gray-500 dark:text-gray-400 text-xs whitespace-nowrap">
                          {formatDateDisplay(cr.plannedStartDate)}
                        </span>
                      ) : col.key === "plannedEndDate" ? (
                        <span className="text-gray-500 dark:text-gray-400 text-xs whitespace-nowrap">
                          {formatDateDisplay(cr.plannedEndDate)}
                        </span>
                      ) : col.key === "crqNumber" ? (
                        <div className="flex items-center justify-between gap-3 min-w-[150px]">
                          <span className="font-mono text-xs font-semibold text-[#002244] dark:text-blue-300">
                            {str(cr.crqNumber)}
                          </span>
                          <CopyButton text={str(cr.crqNumber)} />
                        </div>
                      ) : col.key === "shortDescription" ? (
                        /* Single-line truncated + info icon for full description */
                        <div className="flex items-center gap-2 max-w-xs">
                          <span className="truncate text-sm whitespace-nowrap">{str(cr.shortDescription)}</span>
                          {str(cr.shortDescription) !== "—" && (
                            <button
                              onClick={() => setDescriptionPopup(str(cr.shortDescription))}
                              className="flex-shrink-0 text-gray-400 hover:text-[#002244] dark:hover:text-[#90EE90] transition-colors"
                              title="View full description"
                            >
                              <Info className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      ) : (
                        <span className="line-clamp-1">{str(cr[col.key])}</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {fetched && scrollMode === "paginated" && (
        <PaginationFooter
          pageSize={pageSize} currentPage={currentPage} totalPages={totalPages}
          startIndex={startIndex} endIndex={endIndex} filteredCount={filteredCount}
          onSetPageSize={onSetPageSize} onPrevPage={onPrevPage} onNextPage={onNextPage}
        />
      )}

      {/* Description Popup */}
      {descriptionPopup !== null && (
        <DescriptionModal text={descriptionPopup} onClose={() => setDescriptionPopup(null)} />
      )}
    </>
  );
}

// ─── CSV helper ───────────────────────────────────────────────────────────────

function downloadCsv(csv: string, name: string) {
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}-${new Date().toISOString().split("T")[0]}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
