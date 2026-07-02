"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { applicationsApi, dependencyApprovalsApi, type Application, type DependencyData } from "@/lib/api-client";
import { useAuth } from "@/contexts/AuthContext";
import { useViewContext } from "@/contexts/ViewContext";
import MermaidDiagram from "@/components/MermaidDiagram";
import { safeMermaidLabel, safeMermaidId } from "@/lib/mermaid-utils";
import { ChatSlideOver, type ChatSlideOverMode } from "@/components/ChatSlideOver";
import {
  Eye,
  GitBranch,
  GitMerge,
  Bell,
  ChevronLeft,
  ChevronRight,
  Columns,
  Filter,
  AlignJustify,
  Download,
  Trash2,
  X,
  Search,
  Check,
  Maximize2,
  Minimize2,
  Table,
  Plus,
  ChevronDown,
  Activity,
  MessageCircle
} from "lucide-react";
import HealthReportModal from "@/components/HealthReportModal";
import { AlertsSidebar } from "@/components/AlertsSidebar";
import { DataTable, CellBadge, CellBoolean, CellTruncated, CellCopyable, CellList, multiSelectFilterFn, booleanFilterFn } from "@/components/ui/DataTable";
import { type ColumnDef, type SortingState } from "@tanstack/react-table";

interface ApplicationsViewProps {
  onNavigateToChat?: () => void;
}

// Detail Modal Component
function DetailModal({ app, onClose }: { app: Application; onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-3xl mx-4 max-h-[85vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-[#30363d] bg-[#002244]">
          <div>
            <h2 className="text-lg font-semibold text-white">Application Details</h2>
            <p className="text-sm text-white/70">{app.name}</p>
          </div>
          <button onClick={onClose} className="text-white/80 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6 space-y-6">
          {/* Basic Info */}
          <div>
            <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider mb-3">General</h3>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Status</label>
                <p className={`text-sm font-medium ${app.active ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                  {app.active ? 'Active' : 'Inactive'}
                </p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Type</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{app.applicationType || '—'}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Certified</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{app.certified ? 'Yes' : 'No'}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Tenant</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{app.tenant || '—'}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Tier</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{app.tier || '—'}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Functional Domain</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{app.functionalDomain || '—'}</p>
              </div>
              {app.cluster && (
                <div className="col-span-3">
                  <label className="text-xs text-gray-500 dark:text-gray-400">Cluster</label>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{app.cluster}</p>
                </div>
              )}
            </div>
          </div>

          {/* WCNP / OneOps Info */}
          {app.applicationType === "wcnp" && (app.namespace || app.appName) && (
            <div>
              <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider mb-3">WCNP</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-gray-500 dark:text-gray-400">Namespace</label>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{app.namespace || '—'}</p>
                </div>
                <div>
                  <label className="text-xs text-gray-500 dark:text-gray-400">App Name</label>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{app.appName || '—'}</p>
                </div>
              </div>
            </div>
          )}
          {app.applicationType === "oneops" && (app.oneOpsOrg || app.oneOpsAssembly || app.oneOpsPlatform) && (
            <div>
              <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider mb-3">OneOps</h3>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="text-xs text-gray-500 dark:text-gray-400">Org</label>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{app.oneOpsOrg || '—'}</p>
                </div>
                <div>
                  <label className="text-xs text-gray-500 dark:text-gray-400">Assembly</label>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{app.oneOpsAssembly || '—'}</p>
                </div>
                <div>
                  <label className="text-xs text-gray-500 dark:text-gray-400">Platform</label>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{app.oneOpsPlatform || '—'}</p>
                </div>
              </div>
            </div>
          )}

          {/* Team Info */}
          {app.team && (
            <div>
              <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider mb-3">Team</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-gray-500 dark:text-gray-400">Primary Team</label>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{app.team.isPrimaryTeam ? 'Yes' : 'No'}</p>
                </div>
                <div>
                  <label className="text-xs text-gray-500 dark:text-gray-400">Jira</label>
                  {app.team.jira ? (
                    <a href={app.team.jira} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-600 dark:text-blue-400 hover:underline truncate block">
                      Jira Board
                    </a>
                  ) : <p className="text-sm text-gray-400 dark:text-gray-500">—</p>}
                </div>
              </div>
              {app.team.members && app.team.members.length > 0 && (
                <div className="mt-3">
                  <label className="text-xs text-gray-500 dark:text-gray-400">Members</label>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {app.team.members.map((m) => (
                      <span key={m.id} className="px-2 py-1 bg-gray-100 dark:bg-[#21262d] rounded text-xs text-gray-700 dark:text-gray-300">
                        {m.name}{m.email ? ` (${m.email})` : ''}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Communication */}
          {(app.slackChannels?.length > 0 || app.xmattersGroups?.length > 0 || app.emails?.length > 0) && (
            <div>
              <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider mb-3">Communication</h3>
              <div className="grid grid-cols-3 gap-4">
                {app.slackChannels?.length > 0 && (
                  <div>
                    <label className="text-xs text-gray-500 dark:text-gray-400">Slack Channels</label>
                    <div className="flex flex-wrap gap-2 mt-1">
                      {app.slackChannels.map((ch, i) => (
                        <span key={i} className="px-2 py-1 bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded text-xs">#{ch}</span>
                      ))}
                    </div>
                  </div>
                )}
                {app.xmattersGroups?.length > 0 && (
                  <div>
                    <label className="text-xs text-gray-500 dark:text-gray-400">XMatters Groups</label>
                    <div className="flex flex-wrap gap-2 mt-1">
                      {app.xmattersGroups.map((g, i) => (
                        <span key={i} className="px-2 py-1 bg-orange-50 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 rounded text-xs">{g}</span>
                      ))}
                    </div>
                  </div>
                )}
                {app.emails?.length > 0 && (
                  <div>
                    <label className="text-xs text-gray-500 dark:text-gray-400">Emails</label>
                    <div className="flex flex-wrap gap-2 mt-1">
                      {app.emails.map((e, i) => (
                        <span key={i} className="px-2 py-1 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded text-xs">{e}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="px-6 py-4 border-t border-gray-200 dark:border-[#30363d] bg-gray-50 dark:bg-[#0d1117] flex justify-end">
          <button onClick={onClose} className="px-4 py-2 bg-[#002244] text-white rounded hover:bg-[#003366] transition-colors">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// Confirmation Modal
function ConfirmModal({ title, message, onConfirm, onCancel, confirmText = "Confirm", variant = "default", reasonLabel }: {
  title: string;
  message: string;
  onConfirm: (reason?: string) => void;
  onCancel: () => void;
  confirmText?: string;
  variant?: "default" | "danger";
  /** When provided, renders an optional reason textarea above the action buttons */
  reasonLabel?: string;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onCancel}>
      <div className="bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-gray-200 dark:border-[#30363d]">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h2>
        </div>
        <div className="p-6 space-y-4">
          <p className="text-gray-600 dark:text-gray-300">{message}</p>
          {reasonLabel && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {reasonLabel}
              </label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Add a reason for this request..."
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded-lg text-sm bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 resize-none"
              />
            </div>
          )}
        </div>
        <div className="px-6 py-4 border-t border-gray-200 dark:border-[#30363d] bg-gray-50 dark:bg-[#0d1117] flex justify-end gap-3">
          <button onClick={onCancel} className="px-4 py-2 text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-[#21262d] rounded hover:bg-gray-200 dark:hover:bg-[#30363d] transition-colors">
            Cancel
          </button>
          <button
            onClick={() => onConfirm(reason || undefined)}
            className={`px-4 py-2 text-white rounded transition-colors ${
              variant === "danger" ? "bg-red-600 hover:bg-red-700" : "bg-[#002244] hover:bg-[#003366]"
            }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

// Toast notification
function Toast({ message, type, onClose }: { message: string; type: "success" | "error" | "info"; onClose: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 3000);
    return () => clearTimeout(timer);
  }, [onClose]);

  const bgColor = type === "success" ? "bg-green-600" : type === "error" ? "bg-red-600" : "bg-blue-600";

  return (
    <div className={`fixed bottom-4 right-4 ${bgColor} text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 z-50`}>
      <span>{message}</span>
      <button onClick={onClose} className="text-white/80 hover:text-white">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// Dependency Modal (Upstream/Downstream)
function DependencyModal({
  app,
  type,
  dependencies,
  loading,
  error,
  onClose,
  onDeleteDependency,
  onAddDependency,
}: {
  app: Application;
  type: "upstream" | "downstream";
  dependencies: DependencyData[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onDeleteDependency?: (dep: DependencyData, reason?: string) => void;
  onAddDependency?: (dep: Partial<DependencyData>, reason?: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [viewMode, setViewMode] = useState<"diagram" | "table">("diagram");
  const [depToDelete, setDepToDelete] = useState<DependencyData | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [addReason, setAddReason] = useState("");
  const [selectedDependencyType, setSelectedDependencyType] = useState<"WCNP" | "OneOps" | "PageFlow">("WCNP");
  const [selectedDependencyId, setSelectedDependencyId] = useState<number | null>(null);
  const [allFetchedApps, setAllFetchedApps] = useState<Application[]>([]);
  const [loadingDependencies, setLoadingDependencies] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [showTypeDropdown, setShowTypeDropdown] = useState(false);
  const [showDependencyDropdown, setShowDependencyDropdown] = useState(false);

  // Track opposite direction dependencies to prevent circular relationships
  const [oppositeDependencies, setOppositeDependencies] = useState<DependencyData[]>([]);
  const title = type === "upstream" ? "Upstream Dependencies" : "Downstream Dependencies";
  const icon = type === "upstream" ? <GitMerge className="w-5 h-5" /> : <GitBranch className="w-5 h-5" />;

  // Filter apps by selected type client-side — no re-fetch needed when type changes
  const availableDependencies = useMemo(() => {
    return allFetchedApps.filter((appItem) => {
      if (appItem.id === app.id) return false;
      switch (selectedDependencyType) {
        case "WCNP": return appItem.applicationType === "wcnp";
        case "OneOps": return appItem.applicationType === "oneops";
        case "PageFlow": return appItem.applicationType === "pageflow";
        default: return false;
      }
    });
  }, [allFetchedApps, selectedDependencyType, app.id]);

  // Helper function to check if an app is already a dependency (in either direction)
  const isAppAlreadyDependency = (appId: number): boolean => {
    // Check if already in current direction
    const inCurrentDirection = dependencies.some((dep) => dep.application_id === appId);
    if (inCurrentDirection) return true;

    // Check if exists in opposite direction (would create circular dependency)
    const inOppositeDirection = oppositeDependencies.some((dep) => dep.application_id === appId);
    if (inOppositeDirection) return true;

    return false;
  };

  // Pre-fetch apps and opposite-direction deps as soon as the modal mounts,
  // so data is ready before the user clicks "Add Dependency".
  useEffect(() => {
    applicationsApi.fetchAll()
      .then((allApps) => {
        setAllFetchedApps(allApps.filter((appItem) => appItem.id !== app.id));
      })
      .catch((err) => {
        console.error("Failed to fetch available dependencies:", err);
        setAllFetchedApps([]);
      })
      .finally(() => {
        setLoadingDependencies(false);
      });

    const oppositeFetch = type === "upstream"
      ? applicationsApi.fetchDownstream(app.id)
      : applicationsApi.fetchUpstream(app.id);

    oppositeFetch
      .then((oppositeDeps) => setOppositeDependencies(oppositeDeps || []))
      .catch(() => setOppositeDependencies([]));
  }, [app.id, type]);

  const getAppType = (dep: DependencyData) => {
    // Prefer new API shape first
    if (dep.namespace || dep.app_name) {
      const ns = dep.namespace ?? "";
      const appName = dep.app_name ?? "";
      const detail = [ns, appName].filter(Boolean).join(" / ") || dep.application_name || dep.name || "Unknown";
      return { type: "WCNP", detail };
    }
    if (dep.platform || dep.org || dep.assembly) {
      const parts = [dep.org, dep.assembly, dep.platform].filter(Boolean).join(" / ");
      return { type: "OneOps", detail: parts || dep.application_name || dep.name || "Unknown" };
    }

    // Fallback to legacy fields
    if (dep.wcnp) return { type: "WCNP", detail: dep.wcnp.namespace };
    if (dep.oneOpsPlatform) return { type: "OneOps", detail: dep.oneOpsPlatform.name };
    if (dep.pageFlow) return { type: "PageFlow", detail: dep.name || "Unknown" };

    return { type: "App", detail: dep.application_name || dep.name || "Unknown" };
  };

  const buildDiagram = () => {
    if (!dependencies.length) return null;

    const appId = safeMermaidId(app.name || "app");
    const lines: string[] = [
      "flowchart LR",
      `  ${appId}["${safeMermaidLabel(app.name)}"]`,
    ];

    dependencies.forEach((dep, index) => {
      const depId = `dep_${index}`;
      const appType = getAppType(dep);
      const mainText = safeMermaidLabel(appType.detail || dep.application_name || dep.name);
      const metaParts: string[] = [];
      if (dep.tenant) metaParts.push(safeMermaidLabel(dep.tenant));
      if (dep.tier) metaParts.push(safeMermaidLabel(dep.tier));
      const meta = metaParts.length ? ` ❨${metaParts.join(" / ")}❩` : "";
      const label = `${mainText}${meta}`;

      if (type === "upstream") {
        // upstream: dependency -> app
        lines.push(`  ${depId}["${label}"] --> ${appId}`);
      } else {
        // downstream: app -> dependency
        lines.push(`  ${appId} --> ${depId}["${label}"]`);
      }
    });

    return lines.join("\n");
  };

  const diagram = buildDiagram();

  // Helper to parse and improve error messages
  const parseErrorMessage = (error: unknown, _context: "add" | "delete"): string => {
    let errorMessage = error instanceof Error ? error.message : "An error occurred";

    // Remove generic API error prefix
    const prefix = "An unexpected error occurred: ";
    if (errorMessage.startsWith(prefix)) {
      errorMessage = errorMessage.slice(prefix.length);
    }

    // Parse and improve specific error scenarios
    if (errorMessage.includes("already exists") || errorMessage.includes("Dependency already exists")) {
      return `This dependency already exists. You cannot add the same relationship twice.`;
    }

    if (errorMessage.includes("circular") || errorMessage.includes("Circular dependency")) {
      const oppositeType = type === "upstream" ? "downstream" : "upstream";
      return `Cannot add: This would create a circular dependency with an existing ${oppositeType} relationship.`;
    }

    if (errorMessage.includes("not found") || errorMessage.includes("404")) {
      return `Application not found. It may have been deleted or you don't have permission to access it.`;
    }

    if (errorMessage.includes("400") || errorMessage.includes("Bad Request")) {
      return `Invalid dependency configuration. Please check the application and try again.`;
    }

    return errorMessage;
  };

  // Wrapper for delete callback with error handling
  const handleDeleteWithErrorHandling = async (dep: DependencyData, reason?: string) => {
    try {
      setDialogError(null);
      await onDeleteDependency?.(dep, reason);
    } catch (err) {
      const errorMessage = parseErrorMessage(err, "delete");
      setDialogError(errorMessage);
    }
  };

  // Wrapper for add callback with error handling
  const handleAddWithErrorHandling = async (dep: Partial<DependencyData>, reason?: string) => {
    try {
      setDialogError(null);
      await onAddDependency?.(dep, reason);
    } catch (err) {
      const errorMessage = parseErrorMessage(err, "add");
      setDialogError(errorMessage);
    }
  };

  return (
    <>
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className={
          expanded
            ? "bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-[95vw] h-[90vh] mx-4 flex flex-col"
            : "bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-3xl mx-4 max-h-[85vh] flex flex-col"
        }
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-[#30363d] bg-[#002244]">
          <div className="flex items-center gap-3 text-white">
            {icon}
            <div>
              <h2 className="text-lg font-semibold">{title}</h2>
              <p className="text-sm text-white/70">{app.name}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!loading && !error && dependencies.length > 0 && (
              <div className="flex rounded-lg border border-white/40 overflow-hidden">
                <button
                  onClick={() => setViewMode("diagram")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm transition-colors ${
                    viewMode === "diagram" ? "bg-white/20 text-white" : "text-white/70 hover:text-white"
                  }`}
                  title="Flow diagram"
                >
                  <GitBranch className="w-3.5 h-3.5" />
                  <span>Flow</span>
                </button>
                <button
                  onClick={() => setViewMode("table")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm transition-colors ${
                    viewMode === "table" ? "bg-white/20 text-white" : "text-white/70 hover:text-white"
                  }`}
                  title="Table view"
                >
                  <Table className="w-3.5 h-3.5" />
                  <span>Table</span>
                </button>
              </div>
            )}
            <button
              onClick={() => setExpanded(prev => !prev)}
              className="text-white/80 hover:text-white p-1.5 rounded border border-white/40"
              title={expanded ? "Shrink" : "Expand"}
            >
              {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
            <button onClick={onClose} className="text-white/80 hover:text-white">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6">
          {dialogError && (
            <div className="mb-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg p-4 flex items-start gap-3">
              <div className="text-amber-600 dark:text-amber-400 mt-0.5">
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="flex-1">
                <p className="text-amber-800 dark:text-amber-200 font-medium text-sm">{dialogError}</p>
              </div>
              <button
                onClick={() => setDialogError(null)}
                className="text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 p-0.5"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}
          {loading ? (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-10 h-10 border-4 border-[#002244] dark:border-blue-400 border-t-transparent dark:border-t-transparent rounded-full animate-spin" />
              <p className="mt-4 text-gray-500 dark:text-gray-400">Loading {type} dependencies...</p>
            </div>
          ) : error ? (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-center">
              <p className="text-red-600 dark:text-red-400">{error}</p>
            </div>
          ) : dependencies.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-100 dark:bg-[#21262d] flex items-center justify-center">
                {type === "upstream" ? <GitMerge className="w-8 h-8 text-gray-400" /> : <GitBranch className="w-8 h-8 text-gray-400" />}
              </div>
              <p className="text-gray-500 dark:text-gray-400">No {type} dependencies found</p>
              <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">This application has no {type} connections</p>
            </div>
          ) : (
            <div className="space-y-4 w-full">
              {viewMode === "diagram" && diagram && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                    {type === "upstream" ? "Upstream Dependency Flow" : "Downstream Dependency Flow"}
                  </h3>
                  <div className={expanded ? "w-full" : ""}>
                    <MermaidDiagram diagram={diagram} />
                  </div>
                </div>
              )}
              {viewMode === "table" && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                    {type === "upstream" ? "Upstream Dependencies" : "Downstream Dependencies"}
                  </h3>
                  <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-[#30363d]">
                    <table className="w-full font-sans">
                      <thead>
                        <tr className="bg-[#002244]">
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">
                            Name
                          </th>
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">
                            Type
                          </th>
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">
                            Namespace / Assembly
                          </th>
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">
                            App Name / Platform
                          </th>
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">
                            Tier
                          </th>
                          <th className="px-3 py-2 text-center text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap w-[80px]">
                            Actions
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {dependencies.map((dep, index) => {
                          const appType = getAppType(dep);
                          return (
                            <tr
                              key={dep.id ?? index}
                              className={`border-b border-gray-100 dark:border-[#30363d] hover:bg-[#f5f9ff] dark:hover:bg-[#1c2128] transition-colors ${
                                index % 2 === 1 ? "bg-[#fafbfc] dark:bg-[#161b22]" : "bg-white dark:bg-[#0d1117]"
                              }`}
                            >
                              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-100 font-medium">
                                {appType.detail}
                              </td>
                              <td className="px-5 py-3 text-sm">
                                <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                                  appType.type === "WCNP" ? "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300" :
                                  appType.type === "OneOps" ? "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300" :
                                  appType.type === "PageFlow" ? "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300" :
                                  "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300"
                                }`}>
                                  {appType.type}
                                </span>
                              </td>
                              <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">
                                {dep.namespace ?? dep.assembly ?? dep.wcnp?.namespace ?? "—"}
                              </td>
                              <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">
                                {dep.app_name ?? dep.platform ?? dep.wcnp?.app ?? "—"}
                              </td>
                              <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">
                                {dep.tier ?? "—"}
                              </td>
                              <td className="px-5 py-3 text-center">
                                <button
                                  onClick={() => setDepToDelete(dep)}
                                  className="p-1.5 rounded text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                                  title="Delete dependency"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Found {dependencies.length} {type}{" "}
                {dependencies.length === 1 ? "dependency" : "dependencies"}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 dark:border-[#30363d] bg-gray-50 dark:bg-[#0d1117] flex justify-between">
          <div>
            {!loading && !error && onAddDependency && (
              <button
                onClick={() => setShowAddForm(true)}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Add Dependency
              </button>
            )}
          </div>
          <button onClick={onClose} className="px-4 py-2 bg-[#002244] text-white rounded hover:bg-[#003366] transition-colors">
            Close
          </button>
        </div>
      </div>
    </div>

    {depToDelete && (
      <ConfirmModal
        title="Request Dependency Removal"
        message={`Submit a removal request for the ${type} dependency "${getAppType(depToDelete).detail}"? A reviewer must approve before the change takes effect.`}
        onConfirm={(reason) => {
          handleDeleteWithErrorHandling(depToDelete, reason);
          setDepToDelete(null);
        }}
        onCancel={() => setDepToDelete(null)}
        confirmText="Submit Request"
        variant="danger"
        reasonLabel="Reason (optional)"
      />
    )}

    {showAddForm && (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]" onClick={() => setShowAddForm(false)}>
        <div className="bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
          <div className="px-6 py-4 border-b border-gray-200 dark:border-[#30363d]">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Add {type === "upstream" ? "Upstream" : "Downstream"} Dependency</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">Add a new dependency for {app.name}</p>
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (selectedDependencyId) {
                await handleAddWithErrorHandling({ id: selectedDependencyId }, addReason || undefined);
                setShowAddForm(false);
                setSelectedDependencyId(null);
                setSearchQuery("");
                setAddReason("");
              }
            }}
            className="p-6 space-y-4"
          >
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Type</label>
              <div className="relative">
                <button
                  type="button"
                  onClick={() => { setShowTypeDropdown(!showTypeDropdown); setShowDependencyDropdown(false); }}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded-lg bg-white dark:bg-[#21262d] text-left flex items-center justify-between hover:border-gray-400 dark:hover:border-gray-500 transition-colors focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 focus:border-[#002244] dark:focus:border-blue-500 outline-none"
                >
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">{selectedDependencyType}</span>
                  <ChevronDown className="w-4 h-4 text-gray-400" />
                </button>

                {showTypeDropdown && (
                  <div className="absolute top-full left-0 right-0 mt-1 border border-gray-300 dark:border-[#30363d] rounded-lg bg-white dark:bg-[#21262d] shadow-lg z-20">
                    {['WCNP', 'OneOps', 'PageFlow'].map((type) => (
                      <button
                        key={type}
                        type="button"
                        onClick={() => {
                          setSelectedDependencyType(type as "WCNP" | "OneOps" | "PageFlow");
                          setSelectedDependencyId(null);
                          setSearchQuery("");
                          setShowTypeDropdown(false);
                        }}
                        className="w-full text-left px-3 py-2 text-sm border-b border-gray-100 dark:border-[#30363d] hover:bg-gray-50 dark:hover:bg-[#30363d] transition-colors flex items-center gap-2 last:border-b-0 font-medium text-gray-900 dark:text-gray-100"
                      >
                        {selectedDependencyType === type && <Check className="w-4 h-4 text-[#002244] dark:text-blue-400" />}
                        {selectedDependencyType === type ? <span>{type}</span> : <span className="ml-6">{type}</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Select Dependency</label>

              {loadingDependencies ? (
                <div className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded-lg bg-gray-50 dark:bg-[#21262d] flex items-center justify-center gap-2">
                  <div className="w-4 h-4 border-2 border-[#002244] dark:border-blue-400 border-t-transparent dark:border-t-transparent rounded-full animate-spin" />
                  <span className="text-sm text-gray-500 dark:text-gray-400">Loading...</span>
                </div>
              ) : (
                <div className="space-y-2">
                  {!selectedDependencyId ? (
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => { setShowDependencyDropdown(!showDependencyDropdown); setShowTypeDropdown(false); }}
                        className="w-full flex items-center gap-2 px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded-lg bg-white dark:bg-[#21262d] hover:border-gray-400 dark:hover:border-gray-500 transition-colors text-left"
                      >
                        <Search className="w-4 h-4 text-gray-400" />
                        <span className="flex-1 text-sm text-gray-500 dark:text-gray-400">Select a dependency...</span>
                        <ChevronDown className="w-4 h-4 text-gray-400" />
                      </button>

                      {showDependencyDropdown && availableDependencies.length > 0 && (() => {
                        const MAX_VISIBLE = 50;
                        const filtered = availableDependencies.filter((dep) =>
                          dep.name.toLowerCase().includes(searchQuery.toLowerCase()) &&
                          !isAppAlreadyDependency(dep.id)
                        );
                        const visible = filtered.slice(0, MAX_VISIBLE);
                        const remaining = filtered.length - visible.length;
                        return (
                        <div className="absolute top-full left-0 right-0 mt-1 border border-gray-300 dark:border-[#30363d] rounded-lg bg-white dark:bg-[#21262d] shadow-lg z-20 max-h-48 overflow-y-auto">
                          <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-200 dark:border-[#30363d] sticky top-0 bg-white dark:bg-[#21262d]">
                            <Search className="w-4 h-4 text-gray-400" />
                            <input
                              type="text"
                              placeholder="Search..."
                              value={searchQuery}
                              onChange={(e) => setSearchQuery(e.target.value)}
                              autoFocus
                              className="flex-1 outline-none text-sm bg-transparent dark:text-gray-100 dark:placeholder-gray-500"
                            />
                          </div>
                          {visible.map((dep) => (
                              <button
                                key={dep.id}
                                type="button"
                                onClick={() => {
                                  setSelectedDependencyId(dep.id);
                                  setSearchQuery("");
                                  setShowDependencyDropdown(false);
                                }}
                                className="w-full text-left px-3 py-2 text-sm border-b border-gray-100 dark:border-[#30363d] hover:bg-gray-50 dark:hover:bg-[#30363d] transition-colors flex items-center gap-2 last:border-b-0"
                              >
                                <div className="flex-1">
                                  <div className="font-medium text-gray-900 dark:text-gray-100">
                                    {dep.name}
                                  </div>
                                  {dep.tier && (
                                    <div className="text-xs text-gray-500 dark:text-gray-400">
                                      {dep.tier}
                                    </div>
                                  )}
                                </div>
                              </button>
                            ))}
                          {remaining > 0 && (
                            <div className="px-3 py-2 text-xs text-gray-400 dark:text-gray-500 text-center border-t border-gray-100 dark:border-[#30363d]">
                              {remaining} more — type to search
                            </div>
                          )}
                          {filtered.length === 0 && (
                            <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400 text-center">
                              {availableDependencies.length > 0
                                ? "All available applications are already dependencies"
                                : "No dependencies found"}
                            </div>
                          )}
                        </div>
                        );
                      })()}

                      {showDependencyDropdown && availableDependencies.length === 0 && !loadingDependencies && (
                        <div className="absolute top-full left-0 right-0 mt-1 px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded-lg bg-gray-50 dark:bg-[#21262d] text-sm text-gray-500 dark:text-gray-400 text-center">
                          No {selectedDependencyType} applications available
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="px-3 py-2 border border-blue-200 dark:border-blue-800 rounded-lg bg-blue-50 dark:bg-blue-900/20 text-sm flex items-center justify-between">
                      <div>
                        <span className="text-gray-700 dark:text-gray-300">Selected: </span>
                        <span className="font-medium text-blue-700 dark:text-blue-300">
                          {availableDependencies.find((d) => d.id === selectedDependencyId)?.name}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedDependencyId(null);
                          setSearchQuery("");
                        }}
                        className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 text-xs underline"
                      >
                        Change
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Reason <span className="text-gray-400 dark:text-gray-500 font-normal">(optional)</span>
              </label>
              <textarea
                value={addReason}
                onChange={(e) => setAddReason(e.target.value)}
                placeholder="Why is this dependency needed?"
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded-lg text-sm bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-[#002244] dark:focus:ring-blue-500 resize-none"
              />
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowAddForm(false);
                  setSelectedDependencyId(null);
                  setSearchQuery("");
                  setAddReason("");
                }}
                className="px-4 py-2 text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-[#21262d] rounded hover:bg-gray-200 dark:hover:bg-[#30363d] transition-colors text-sm"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!selectedDependencyId}
                className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                Submit Request
              </button>
            </div>
          </form>
        </div>
      </div>
    )}
    </>
  );
}

function getTenantVariant(tenant: string): "orange" | "blue" | "purple" | "cyan" | "pink" | "indigo" | "green" | "red" | "default" {
  switch ((tenant || "").trim().toLowerCase()) {
    case "wcnp":    return "orange";
    case "na":      return "blue";
    case "mx":      return "purple";
    case "ca":      return "cyan";
    case "cl":      return "pink";
    case "us":      return "indigo";
    case "test":    return "green";
    default:        return "red";
  }
}

export function ApplicationsView({ onNavigateToChat: _onNavigateToChat }: ApplicationsViewProps) {
  const { user } = useAuth();
  const viewContext = useViewContext();
  // Initialize from cache for instant render (stale-while-revalidate)
  const [applications, setApplications] = useState<Application[]>(() => applicationsApi.getCached() ?? []);
  const [loading, setLoading] = useState(() => applicationsApi.getCached() === null);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [selectedApp, setSelectedApp] = useState<Application | null>(null);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info" } | null>(null);

  // Health report modal state
  const [healthReportApp, setHealthReportApp] = useState<Application | null>(null);

  // Alerts sidebar state
  const [alertsApp, setAlertsApp] = useState<Application | null>(null);
  const [showAlertsSidebar, setShowAlertsSidebar] = useState(false);

  // Dependency modal state
  const [dependencyModal, setDependencyModal] = useState<{
    app: Application;
    type: "upstream" | "downstream";
  } | null>(null);
  const [dependencies, setDependencies] = useState<DependencyData[]>([]);
  const [dependencyLoading, setDependencyLoading] = useState(false);
  const [dependencyError, setDependencyError] = useState<string | null>(null);

  useEffect(() => {
    fetchApplications();
    // Clear selected application when leaving this view
    return () => {
      viewContext.setSelectedApplication(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync filtered count to ViewContext
  useEffect(() => {
    viewContext.setFilteredApplicationCount(applications.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applications.length]);

  const fetchApplications = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await applicationsApi.fetchAll();
      setApplications(data);
      // Sync to ViewContext for chat context awareness
      viewContext.setApplicationData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch applications");
    } finally {
      setLoading(false);
    }
  };

  // Action handlers
  const handleViewDetails = (app: Application) => {
    setSelectedApp(app);
    setShowDetailModal(true);
  };

  const handleDownstream = async (app: Application) => {
    setDependencyModal({ app, type: "downstream" });
    setDependencies([]);
    setDependencyError(null);
    setDependencyLoading(true);

    // Pre-warm applications cache so "Add Dependency" form loads instantly
    applicationsApi.fetchAll().catch(() => {});

    try {
      const data = await applicationsApi.fetchDownstream(app.id);
      setDependencies(data || []);
    } catch (err) {
      setDependencyError(err instanceof Error ? err.message : "Failed to fetch downstream dependencies");
    } finally {
      setDependencyLoading(false);
    }
  };

  const handleUpstream = async (app: Application) => {
    setDependencyModal({ app, type: "upstream" });
    setDependencies([]);
    setDependencyError(null);
    setDependencyLoading(true);

    // Pre-warm applications cache so "Add Dependency" form loads instantly
    applicationsApi.fetchAll().catch(() => {});

    try {
      const data = await applicationsApi.fetchUpstream(app.id);
      setDependencies(data || []);
    } catch (err) {
      setDependencyError(err instanceof Error ? err.message : "Failed to fetch upstream dependencies");
    } finally {
      setDependencyLoading(false);
    }
  };

  const closeDependencyModal = () => {
    setDependencyModal(null);
    setDependencies([]);
    setDependencyError(null);
  };

  const handleAlerts = (app: Application) => {
    setAlertsApp(app);
    setShowAlertsSidebar(true);
  };



  // eslint-disable-next-line react-hooks/exhaustive-deps
  const tableColumns = useMemo<ColumnDef<Application, unknown>[]>(() => [
    {
      id: "namespace",
      accessorFn: (row) => row.applicationType === "oneops" ? (row.oneOpsAssembly || "") : (row.namespace || ""),
      header: "Namespace",
      size: 198,
      cell: ({ getValue }) => <CellCopyable text={getValue() as string} />,
      meta: { filterType: "text" },
    },
    {
      id: "appName",
      accessorFn: (row) => row.applicationType === "oneops" ? (row.oneOpsPlatform || "") : (row.appName || ""),
      header: "App Name",
      size: 242,
      cell: ({ getValue }) => <CellCopyable text={getValue() as string} />,
      meta: { filterType: "text" },
    },
    {
      accessorKey: "name",
      header: "Name",
      size: 180,
      cell: ({ getValue }) => <span className="font-medium">{getValue() as string}</span>,
      meta: { filterType: "text" },
    },
    {
      accessorKey: "oneOpsOrg",
      header: "OneOps Org",
      size: 100,
      cell: ({ getValue }) => <CellTruncated text={getValue() as string} maxWidth="100px" />,
      meta: { filterType: "text" },
    },
    {
      accessorKey: "tenant",
      header: "Tenant",
      size: 100,
      filterFn: multiSelectFilterFn as never,
      meta: { filterType: "facet" },
      cell: ({ getValue }) => {
        const v = getValue() as string;
        return v ? <CellBadge variant={getTenantVariant(v)}>{v}</CellBadge> : <span className="text-gray-400">—</span>;
      },
    },
    {
      accessorKey: "tier",
      header: "Tier",
      size: 60,
      filterFn: multiSelectFilterFn as never,
      meta: { filterType: "facet" },
      cell: ({ getValue }) => {
        const v = getValue() as string;
        return v ? <span className="text-xs font-medium">{v}</span> : <span className="text-gray-400">—</span>;
      },
    },
    {
      accessorKey: "functionalDomain",
      header: "Domain",
      size: 120,
      cell: ({ getValue }) => <CellTruncated text={getValue() as string} maxWidth="120px" />,
      meta: { filterType: "text" },
    },
    {
      accessorKey: "cluster",
      header: "Cluster",
      size: 140,
      cell: ({ getValue }) => <CellCopyable text={getValue() as string} />,
      meta: { filterType: "text" },
    },
    {
      id: "team",
      accessorFn: (row) => row.team?.jira || "",
      header: "Team",
      size: 90,
      cell: ({ row }) => {
        const t = row.original.team;
        if (!t) return <span className="text-gray-400">—</span>;
        return (
          <span className="text-xs font-medium">
            {t.jira ? "Jira" : "—"}
            {t.members?.length > 0 && <span className="text-gray-400 ml-1">({t.members.length})</span>}
          </span>
        );
      },
    },
    {
      id: "slack",
      accessorFn: (row) => row.slackChannels?.join(", ") || "",
      header: "Slack",
      size: 110,
      cell: ({ row }) => <CellList items={row.original.slackChannels} variant="blue" prefix="#" truncateAt={8} />,
    },
    {
      id: "xmatters",
      accessorFn: (row) => row.xmattersGroups?.join(", ") || "",
      header: "xMatters",
      size: 110,
      cell: ({ row }) => <CellList items={row.original.xmattersGroups} variant="purple" truncateAt={8} />,
    },
    {
      id: "email",
      accessorFn: (row) => row.emails?.join(", ") || "",
      header: "Emails",
      size: 110,
      cell: ({ row }) => <CellList items={row.original.emails} truncateAt={8} />,
    },
    {
      accessorKey: "certified",
      header: "Certified",
      size: 95,
      filterFn: booleanFilterFn as never,
      meta: { filterType: "boolean" },
      cell: ({ getValue }) => <CellBoolean value={getValue() as boolean} />,
    },
    {
      accessorKey: "active",
      header: "Active",
      size: 80,
      filterFn: booleanFilterFn as never,
      meta: { filterType: "boolean" },
      cell: ({ getValue }) => {
        const v = getValue() as boolean;
        return v ? <CellBadge variant="green">✓ Active</CellBadge> : <CellBadge variant="red">✗ Inactive</CellBadge>;
      },
    },
    {
      id: "actions",
      header: "Actions",
      enableSorting: false,
      cell: ({ row }) => {
        const app = row.original;
        return (
          <div className="flex items-center justify-center gap-1.5" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => handleViewDetails(app)} className="p-1.5 text-[#002244] dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-[#21262d] hover:text-[#0071CE] rounded-md transition-colors" title="View application details">
              <Eye className="w-4 h-4" />
            </button>
            <button onClick={() => handleDownstream(app)} className="p-1.5 text-[#002244] dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-[#21262d] hover:text-[#0071CE] rounded-md transition-colors" title="View downstream dependencies">
              <GitBranch className="w-4 h-4" />
            </button>
            <button onClick={() => handleUpstream(app)} className="p-1.5 text-[#002244] dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-[#21262d] hover:text-[#0071CE] rounded-md transition-colors" title="View upstream dependencies">
              <GitMerge className="w-4 h-4" />
            </button>
            <button onClick={() => handleAlerts(app)} className="p-1.5 text-[#002244] dark:text-gray-300 hover:bg-orange-50 dark:hover:bg-[#21262d] hover:text-orange-500 rounded-md transition-colors" title="View active alerts">
              <Bell className="w-4 h-4" />
            </button>
            {app.applicationType === "wcnp" && (
              <button
                onClick={() => {
                  setHealthReportApp(app);
                  viewContext.setSelectedApplication(app);
                }}
                className="p-1.5 text-[#002244] dark:text-gray-300 hover:bg-green-50 dark:hover:bg-[#21262d] hover:text-green-600 rounded-md transition-colors"
                title="Run health check report"
              >
                <Activity className="w-4 h-4" />
              </button>
            )}
          </div>
        );
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], []);

  return (
    <>
      <DataTable
        data={applications}
        columns={tableColumns}
        title="Applications"
        loading={loading}
        error={error}
        onRetry={fetchApplications}
        onRowClick={(app) => {
          viewContext.setSelectedApplication(
            viewContext.selectedApplication?.id === app.id ? null : app
          );
        }}
        selectedRowId={viewContext.selectedApplication?.id ?? null}
        getRowId={(row) => String(row.id)}
        defaultColumnVisibility={{
          name: false,
          oneOpsOrg: false,
          functionalDomain: false,
          team: false,
          active: false,
        }}
        defaultSorting={[{ id: "certified", desc: true }]}
        emptyMessage="No applications found"
        filterEmptyMessage="No applications match your filters"
      />

      {/* Modals */}
      {showDetailModal && selectedApp && (
        <DetailModal app={selectedApp} onClose={() => { setShowDetailModal(false); setSelectedApp(null); }} />
      )}

      {dependencyModal && (
        <DependencyModal
          app={dependencyModal.app}
          type={dependencyModal.type}
          dependencies={dependencies}
          loading={dependencyLoading}
          error={dependencyError}
          onClose={closeDependencyModal}
          onDeleteDependency={async (dep, reason) => {
            try {
              setDependencyLoading(true);
              const dependencyId = dep.application_id;
              if (!dependencyId) {
                throw new Error("Cannot delete: application_id not found. Available fields: " + Object.keys(dep).join(", "));
              }

              const result = await dependencyApprovalsApi.submitRequest({
                applicationId: dependencyModal.app.id,
                dependencyId,
                action: "DELETE",
                requestedBy: user?.loginId ?? 'unknown',
                reason,
              });
              const approval = result.data;
              if (approval.status === "REJECTED" && approval.approvedBy === "system") {
                setToast({ message: `Auto-rejected: ${approval.reason}`, type: "error" });
              } else {
                setToast({ message: "Removal request submitted — pending review", type: "info" });
              }
              // No optimistic update — dependency remains active until a reviewer approves
            } catch (err) {
              console.error("Delete dependency error:", err);
              // Re-throw so wrapper function can handle it and display in dialog
              throw err;
            } finally {
              setDependencyLoading(false);
            }
          }}
          onAddDependency={async (dep, reason) => {
            try {
              setDependencyLoading(true);
              if (dep.id) {
                const result = await dependencyApprovalsApi.submitRequest({
                  applicationId: dependencyModal.app.id,
                  dependencyId: dep.id,
                  action: "ADD",
                  requestedBy: user?.loginId ?? 'unknown',
                  reason,
                });
                const approval = result.data;
                if (approval.status === "REJECTED" && approval.approvedBy === "system") {
                  setToast({ message: `Auto-rejected: ${approval.reason}`, type: "error" });
                } else {
                  setToast({ message: "Approval request submitted — pending review", type: "info" });
                }
                // No optimistic update — dependency not active until a reviewer approves
              }
            } catch (err) {
              console.error("Add dependency error:", err);
              // Re-throw so wrapper function can handle it and display in dialog
              throw err;
            } finally {
              setDependencyLoading(false);
            }
          }}
        />
      )}

      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}

      {healthReportApp && (
        <HealthReportModal
          app={{
            id: healthReportApp.id,
            name: healthReportApp.name,
            namespace: healthReportApp.namespace || undefined,
            appName: healthReportApp.appName || undefined,
          }}
          onClose={() => setHealthReportApp(null)}
        />
      )}

      {alertsApp && (
        <AlertsSidebar
          isOpen={showAlertsSidebar}
          onClose={() => {
            setShowAlertsSidebar(false);
            setAlertsApp(null);
          }}
          app={alertsApp}
        />
      )}
    </>
  );
}
