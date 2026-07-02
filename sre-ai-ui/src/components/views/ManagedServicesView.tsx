"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { managedServicesApi, applicationsApi, dependencyApprovalsApi, type ManagedServiceData, type DependencyData, type Application } from "@/lib/api-client";
import { useAuth } from "@/contexts/AuthContext";
import { useViewContext } from "@/contexts/ViewContext";
import MermaidDiagram from "@/components/MermaidDiagram";
import { safeMermaidLabel, safeMermaidId } from "@/lib/mermaid-utils";
import { Search, GitMerge, X, GitBranch, Table, Maximize2, Minimize2, Plus, Trash2, Eye, Bell, Check, ChevronDown } from "lucide-react";
import { AlertsSidebar } from "@/components/AlertsSidebar";
import { DataTable, CellBadge, CellTruncated, CellCopyable, CellList, multiSelectFilterFn } from "@/components/ui/DataTable";
import { type ColumnDef } from "@tanstack/react-table";

export function ManagedServicesView() {
  const { user } = useAuth();
  const viewContext = useViewContext();
  const [data, setData] = useState<ManagedServiceData[]>(() => managedServicesApi.getCached() ?? []);
  const [loading, setLoading] = useState(() => managedServicesApi.getCached() === null);
  const [error, setError] = useState<string | null>(null);
  const [upstreamModal, setUpstreamModal] = useState<{ item: ManagedServiceData; dependencies: DependencyData[] } | null>(null);
  const [upstreamLoading, setUpstreamLoading] = useState(false);
  const [upstreamError, setUpstreamError] = useState<string | null>(null);
  const [detailModalItem, setDetailModalItem] = useState<ManagedServiceData | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info" } | null>(null);

  // Alerts sidebar state
  const [alertsService, setAlertsService] = useState<ManagedServiceData | null>(null);
  const [showAlertsSidebar, setShowAlertsSidebar] = useState(false);

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Clear selected managed service when leaving this view
  useEffect(() => {
    return () => {
      viewContext.setSelectedManagedService(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync filtered count to ViewContext
  useEffect(() => {
    viewContext.setFilteredManagedServiceCount(data.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.length]);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await managedServicesApi.fetchAll();
      setData(result);
      // Sync to ViewContext for chat context awareness
      viewContext.setManagedServiceData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch managed services");
    } finally {
      setLoading(false);
    }
  };

  const handleViewDetails = useCallback((item: ManagedServiceData) => {
    setDetailModalItem(item);
  }, []);

  const handleAlerts = useCallback((item: ManagedServiceData) => {
    setAlertsService(item);
    setShowAlertsSidebar(true);
  }, []);

  const tableColumns = useMemo<ColumnDef<ManagedServiceData, unknown>[]>(() => [
    {
      id: "subscriptionIdAssembly",
      accessorFn: (row) => row.subscriptionId || row.assembly || row.topicName || "",
      header: "Subscription / Assembly / Topic",
      size: 240,
      meta: { filterType: "text" },
      cell: ({ getValue }) => <CellCopyable text={getValue() as string} />,
    },
    {
      id: "resourceGroupPlatformTopic",
      accessorFn: (row) => row.resourceGroup || row.platform || "",
      header: "Resource Group / Platform",
      size: 200,
      meta: { filterType: "text" },
      cell: ({ getValue }) => <CellCopyable text={getValue() as string} />,
    },
    {
      accessorKey: "serviceType",
      header: "Tenant",
      size: 100,
      filterFn: multiSelectFilterFn as never,
      meta: { filterType: "facet" },
      cell: ({ getValue }) => {
        const v = getValue() as string;
        return v ? <CellBadge variant="purple">{v}</CellBadge> : <span className="text-gray-400">—</span>;
      },
    },
    {
      accessorKey: "databaseName",
      header: "Database",
      size: 160,
      meta: { filterType: "text" },
      cell: ({ getValue }) => <CellCopyable text={getValue() as string} />,
    },
    {
      accessorKey: "dns",
      header: "DNS",
      size: 180,
      meta: { filterType: "text" },
      cell: ({ getValue }) => <CellCopyable text={getValue() as string} />,
    },
    {
      id: "actions",
      header: "Actions",
      enableSorting: false,
      cell: ({ row }) => {
        const item = row.original;
        return (
          <div className="flex items-center justify-center gap-1.5" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => handleViewDetails(item)}
              className="p-1.5 text-[#002244] dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-[#21262d] hover:text-[#0071CE] rounded-md transition-colors"
              title="View service details"
            >
              <Eye className="w-4 h-4" />
            </button>
            {item.appId != null && (
              <button
                onClick={() => handleUpstream(item)}
                className="p-1.5 text-[#002244] dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-[#21262d] hover:text-[#0071CE] rounded-md transition-colors"
                title="View upstream dependencies"
              >
                <GitMerge className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={() => handleAlerts(item)}
              className="p-1.5 text-[#002244] dark:text-gray-300 hover:bg-orange-50 dark:hover:bg-[#21262d] hover:text-orange-500 rounded-md transition-colors"
              title="View active alerts"
            >
              <Bell className="w-4 h-4" />
            </button>
          </div>
        );
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], []);

  const handleUpstream = useCallback((item: ManagedServiceData) => {
    if (item.appId == null) return;

    // Open modal immediately with synchronous state update
    setUpstreamModal({ item, dependencies: [] });
    setUpstreamError(null);
    setUpstreamLoading(true);

    // Pre-warm applications cache so "Add Dependency" form loads instantly
    applicationsApi.fetchAll().catch(() => {});

    // Fetch dependencies asynchronously
    const fetchData = async () => {
      try {
        if (!item.appId) return;
        const deps = await applicationsApi.fetchUpstream(item.appId);
        // Only update if modal is still open for this item
        setUpstreamModal((prev) => {
          if (!prev || prev.item.appId !== item.appId) return prev;
          return { ...prev, dependencies: deps || [] };
        });
      } catch (err) {
        setUpstreamError(err instanceof Error ? err.message : "Failed to fetch upstream dependencies");
      } finally {
        setUpstreamLoading(false);
      }
    };

    // Start the fetch immediately (don't defer)
    fetchData();
  }, []);

  const closeUpstreamModal = () => {
    setUpstreamModal(null);
    setUpstreamError(null);
  };

  const handleDeleteDependency = async (dep: DependencyData, reason?: string) => {
    if (!upstreamModal?.item.appId) return;
    try {
      setUpstreamLoading(true);
      const dependencyId = dep.application_id;
      if (!dependencyId) {
        throw new Error("Cannot delete: application_id not found. Available fields: " + Object.keys(dep).join(", "));
      }

      const result = await dependencyApprovalsApi.submitRequest({
        applicationId: upstreamModal.item.appId,
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
      const errorMessage = err instanceof Error ? err.message : "Failed to submit removal request";
      setUpstreamError(errorMessage);
      throw err; // Re-throw for wrapper to handle
    } finally {
      setUpstreamLoading(false);
    }
  };

  const handleAddDependency = async (dep: Partial<DependencyData>, reason?: string) => {
    if (!upstreamModal?.item.appId) return;
    try {
      setUpstreamLoading(true);
      if (dep.id) {
        const result = await dependencyApprovalsApi.submitRequest({
          applicationId: upstreamModal.item.appId,
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
      const errorMessage = err instanceof Error ? err.message : "Failed to submit approval request";
      setUpstreamError(errorMessage);
      throw err; // Re-throw for wrapper to handle
    } finally {
      setUpstreamLoading(false);
    }
  };

  const getAppType = (dep: DependencyData) => {
    if (dep.namespace || dep.app_name) {
      const ns = dep.namespace ?? "";
      const appName = dep.app_name ?? "";
      return { type: "WCNP" as const, detail: [ns, appName].filter(Boolean).join(" / ") || dep.application_name || dep.name || "Unknown" };
    }
    if (dep.platform || dep.org || dep.assembly) {
      const parts = [dep.org, dep.assembly, dep.platform].filter(Boolean).join(" / ");
      return { type: "OneOps" as const, detail: parts || dep.application_name || dep.name || "Unknown" };
    }
    if (dep.wcnp) return { type: "WCNP" as const, detail: dep.wcnp.namespace };
    if (dep.oneOpsPlatform) return { type: "OneOps" as const, detail: dep.oneOpsPlatform.name };
    if (dep.pageFlow) return { type: "PageFlow" as const, detail: dep.name || "Unknown" };
    return { type: "App" as const, detail: dep.application_name || dep.name || "Unknown" };
  };

  return (
    <>
      <DataTable
        data={data}
        columns={tableColumns}
        title="Managed Services"
        loading={loading}
        error={error}
        onRetry={fetchData}
        onRowClick={(item) => {
          const currentId = viewContext.selectedManagedService?.id ?? viewContext.selectedManagedService?.managedServiceId;
          const clickedId = item.id ?? item.managedServiceId;
          viewContext.setSelectedManagedService(currentId === clickedId ? null : item);
        }}
        selectedRowId={viewContext.selectedManagedService?.id ?? viewContext.selectedManagedService?.managedServiceId ?? null}
        getRowId={(row) => String(row.managedServiceId)}
        defaultColumnVisibility={{
          dns: false,
        }}
        emptyMessage="No managed services found"
        filterEmptyMessage="No managed services match your filters"
      />

      {/* Upstream Dependencies Modal */}
      {upstreamModal && (
        <UpstreamModal
          item={upstreamModal.item}
          dependencies={upstreamModal.dependencies}
          loading={upstreamLoading}
          error={upstreamError}
          getAppType={getAppType}
          onClose={closeUpstreamModal}
          onDeleteDependency={handleDeleteDependency}
          onAddDependency={handleAddDependency}
        />
      )}

      {detailModalItem && (
        <ManagedServiceDetailModal item={detailModalItem} onClose={() => setDetailModalItem(null)} />
      )}

      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}

      {alertsService && (
        <AlertsSidebar
          isOpen={showAlertsSidebar}
          onClose={() => {
            setShowAlertsSidebar(false);
            setAlertsService(null);
          }}
          app={alertsService}
        />
      )}
    </>
  );
}

function ManagedServiceDetailModal({ item, onClose }: { item: ManagedServiceData; onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-3xl mx-4 max-h-[85vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-[#30363d] bg-[#002244]">
          <div>
            <h2 className="text-lg font-semibold text-white">Managed Service Details</h2>
            <p className="text-sm text-white/70">{item.name}</p>
          </div>
          <button onClick={onClose} className="text-white/80 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6 space-y-6">
          <div>
            <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-3">General</h3>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Tenant</label>
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{item.serviceType || "—"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Linked App ID</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{item.appId ?? "—"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Assembly</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{item.assembly || "—"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Platform</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{item.platform || "—"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Subscription ID</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{item.subscriptionId || "—"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Resource Group</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{item.resourceGroup || "—"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Database Name</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{item.databaseName || "—"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">DNS</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{item.dns || "—"}</p>
              </div>
              <div>
                <label className="text-xs text-gray-500 dark:text-gray-400">Topic Name</label>
                <p className="text-sm text-gray-900 dark:text-gray-100">{item.topicName || "—"}</p>
              </div>
            </div>
          </div>
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

function UpstreamModal({
  item,
  dependencies,
  loading,
  error,
  getAppType,
  onClose,
  onDeleteDependency,
  onAddDependency,
}: {
  item: ManagedServiceData;
  dependencies: DependencyData[];
  loading: boolean;
  error: string | null;
  getAppType: (dep: DependencyData) => { type: string; detail: string };
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
  const [showTypeDropdown, setShowTypeDropdown] = useState(false);
  const [showDependencyDropdown, setShowDependencyDropdown] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const appId = safeMermaidId(item.name || "app");
  const diagramLines = [
    "flowchart LR",
    `  ${appId}["${safeMermaidLabel(item.name)}"]`,
    ...dependencies.map((dep, index) => {
      const depId = `dep_${index}`;
      const appType = getAppType(dep);
      const mainText = safeMermaidLabel(appType.detail || dep.application_name || dep.name);
      const metaParts: string[] = [];
      if (dep.tenant) metaParts.push(safeMermaidLabel(dep.tenant));
      if (dep.tier) metaParts.push(safeMermaidLabel(dep.tier));
      const meta = metaParts.length ? ` ❨${metaParts.join(" / ")}❩` : "";
      return `  ${depId}["${mainText}${meta}"] --> ${appId}`;
    }),
  ];
  const diagram = dependencies.length > 0 ? diagramLines.join("\n") : null;

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
      return `Cannot add: This would create a circular dependency with an existing downstream relationship.`;
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

  // Pre-fetch apps as soon as the modal mounts so data is ready before "Add Dependency" click
  useEffect(() => {
    applicationsApi.fetchAll()
      .then((allApps) => {
        setAllFetchedApps(allApps.filter((appItem) => !(item.appId && appItem.id === item.appId)));
      })
      .catch(() => {
        setAllFetchedApps([]);
      })
      .finally(() => {
        setLoadingDependencies(false);
      });
  }, [item.appId]);

  // Filter apps by selected type client-side — no re-fetch when type changes
  const availableDependencies = useMemo(() => {
    return allFetchedApps.filter((appItem) => {
      switch (selectedDependencyType) {
        case "WCNP": return appItem.applicationType === "wcnp";
        case "OneOps": return appItem.applicationType === "oneops";
        case "PageFlow": return appItem.applicationType === "pageflow";
        default: return false;
      }
    });
  }, [allFetchedApps, selectedDependencyType]);

  // Helper function to check if an app is already a dependency
  const isAppAlreadyDependency = (appId: number): boolean => {
    return dependencies.some((dep) => dep.application_id === appId);
  };

  // Memoize filtered dropdown items to avoid re-filtering on every render
  const filteredDropdownItems = useMemo(() => {
    return availableDependencies
      .filter((dep: Application) =>
        dep.name.toLowerCase().includes(searchQuery.toLowerCase()) &&
        !dependencies.some((d) => d.application_id === dep.id)
      );
  }, [availableDependencies, searchQuery, dependencies]);

  return (
    <>
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={(e) => {
      // Only close if the click is directly on the backdrop, not on the modal
      if (e.target === e.currentTarget) {
        onClose();
      }
    }}>
      <div
        className={
          expanded
            ? "bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-[95vw] h-[90vh] mx-4 flex flex-col"
            : "bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-3xl mx-4 max-h-[85vh] flex flex-col"
        }
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-[#30363d] bg-[#002244]">
          <div className="flex items-center gap-3 text-white">
            <GitMerge className="w-5 h-5" />
            <div>
              <h2 className="text-lg font-semibold">Upstream Dependencies</h2>
              <p className="text-sm text-white/70">{item.name}</p>
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
              onClick={() => setExpanded((prev) => !prev)}
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

        <div className="flex-1 overflow-auto p-6">
          {dialogError && (
            <div className="mb-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg p-4 flex items-start gap-3">
              <div className="text-amber-600 dark:text-amber-400 mt-0.5">
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="flex-1">
                <p className="text-amber-800 dark:text-amber-300 font-medium text-sm">{dialogError}</p>
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
              <p className="mt-4 text-gray-500 dark:text-gray-400">Loading upstream dependencies...</p>
            </div>
          ) : error ? (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-center">
              <p className="text-red-600 dark:text-red-400">{error}</p>
            </div>
          ) : dependencies.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-100 dark:bg-[#21262d] flex items-center justify-center">
                <GitMerge className="w-8 h-8 text-gray-400 dark:text-gray-500" />
              </div>
              <p className="text-gray-500 dark:text-gray-400">No upstream dependencies found</p>
              <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">This application has no upstream connections</p>
            </div>
          ) : (
            <div className="space-y-4 w-full">
              {viewMode === "diagram" && diagram && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Upstream Dependency Flow</h3>
                  <div className={expanded ? "w-full" : ""}>
                    <MermaidDiagram diagram={diagram} />
                  </div>
                </div>
              )}
              {viewMode === "table" && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Upstream Dependencies</h3>
                  <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-[#30363d]">
                    <table className="w-full font-sans">
                      <thead>
                        <tr className="bg-[#002244] dark:bg-[#002244]">
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">Name</th>
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">Type</th>
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">Namespace / Assembly</th>
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">App Name / Platform</th>
                          <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap">Tier</th>
                          <th className="px-3 py-2 text-center text-[10px] font-semibold text-[#90EE90] tracking-wide whitespace-nowrap w-[80px]">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dependencies.map((dep, index) => {
                          const appType = getAppType(dep);
                          return (
                            <tr
                              key={dep.id ?? index}
                              className={`border-b border-gray-100 dark:border-[#30363d] hover:bg-[#f5f9ff] dark:hover:bg-[#21262d] transition-colors ${
                                index % 2 === 1 ? "bg-[#fafbfc] dark:bg-[#0d1117]" : "bg-white dark:bg-[#161b22]"
                              }`}
                            >
                              <td className="px-5 py-3 text-sm text-[#1a1a1a] dark:text-gray-100 font-medium">{appType.detail}</td>
                              <td className="px-5 py-3 text-sm">
                                <span
                                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                                    appType.type === "WCNP"
                                      ? "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300"
                                      : appType.type === "OneOps"
                                        ? "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300"
                                        : appType.type === "PageFlow"
                                          ? "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300"
                                          : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300"
                                  }`}
                                >
                                  {appType.type}
                                </span>
                              </td>
                              <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">
                                {dep.namespace ?? dep.assembly ?? dep.wcnp?.namespace ?? "—"}
                              </td>
                              <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">
                                {dep.app_name ?? dep.platform ?? dep.wcnp?.app ?? "—"}
                              </td>
                              <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">{dep.tier ?? "—"}</td>
                              <td className="px-5 py-3 text-center">
                                {onDeleteDependency && (
                                  <button
                                    onClick={() => setDepToDelete(dep)}
                                    className="p-1.5 rounded text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                                    title="Delete dependency"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </button>
                                )}
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
                Found {dependencies.length} upstream {dependencies.length === 1 ? "dependency" : "dependencies"}
              </p>
            </div>
          )}
        </div>

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
        message={`Submit a removal request for the upstream dependency "${getAppType(depToDelete).detail}"? A reviewer must approve before the change takes effect.`}
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
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Add Upstream Dependency</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">Add a new upstream dependency for {item.name}</p>
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (selectedDependencyId) {
                try {
                  const selectedApp = availableDependencies.find((d) => d.id === selectedDependencyId);
                  await handleAddWithErrorHandling({
                    id: selectedDependencyId,
                    application_id: selectedApp?.id,
                    application_name: selectedApp?.name,
                    name: selectedApp?.name,
                    tenant: selectedApp?.tenant,
                    tier: selectedApp?.tier,
                    namespace: selectedApp?.namespace,
                    app_name: selectedApp?.appName,
                    org: selectedApp?.oneOpsOrg,
                    assembly: selectedApp?.oneOpsAssembly,
                    platform: selectedApp?.oneOpsPlatform,
                  }, addReason || undefined);
                  // Only close if successful
                  setShowAddForm(false);
                  setSelectedDependencyId(null);
                  setSearchQuery("");
                  setAddReason("");
                } catch {
                  // Error is already handled by handleAddWithErrorHandling
                }
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
                  <ChevronDown className="w-4 h-4 text-gray-400 dark:text-gray-500" />
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
                        className="w-full text-left px-3 py-2 text-sm border-b border-gray-100 dark:border-[#30363d] hover:bg-gray-50 dark:hover:bg-[#161b22] transition-colors flex items-center gap-2 last:border-b-0 font-medium text-gray-900 dark:text-gray-100"
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
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Select Dependency
                {loadingDependencies && <span className="text-xs text-gray-400 dark:text-gray-500 ml-1">(Loading...)</span>}
              </label>

              <div className="space-y-2">
                {!selectedDependencyId ? (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => { setShowDependencyDropdown(!showDependencyDropdown); setShowTypeDropdown(false); }}
                      className="w-full flex items-center gap-2 px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded-lg bg-white dark:bg-[#21262d] hover:border-gray-400 dark:hover:border-gray-500 transition-colors text-left"
                    >
                      <Search className="w-4 h-4 text-gray-400 dark:text-gray-500" />
                      <span className="flex-1 text-sm text-gray-500 dark:text-gray-400">
                        {loadingDependencies ? "Loading dependencies..." : "Select a dependency..."}
                      </span>
                      <ChevronDown className="w-4 h-4 text-gray-400 dark:text-gray-500" />
                    </button>

                    {showDependencyDropdown && (loadingDependencies || availableDependencies.length > 0) && (
                      <div className="absolute top-full left-0 right-0 mt-1 border border-gray-300 dark:border-[#30363d] rounded-lg bg-white dark:bg-[#21262d] shadow-lg z-20 max-h-48 overflow-y-auto">
                        {loadingDependencies ? (
                          <div className="flex items-center justify-center gap-2 px-3 py-4">
                            <div className="w-4 h-4 border-2 border-[#002244] dark:border-blue-400 border-t-transparent dark:border-t-transparent rounded-full animate-spin" />
                            <span className="text-sm text-gray-500 dark:text-gray-400">Fetching dependencies...</span>
                          </div>
                        ) : (() => {
                            const MAX_VISIBLE = 50;
                            const visible = filteredDropdownItems.slice(0, MAX_VISIBLE);
                            const remaining = filteredDropdownItems.length - visible.length;
                            return (
                            <>
                            <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-200 dark:border-[#30363d] sticky top-0 bg-white dark:bg-[#21262d]">
                              <Search className="w-4 h-4 text-gray-400 dark:text-gray-500" />
                              <input
                                type="text"
                                placeholder="Search..."
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                autoFocus
                                className="flex-1 outline-none text-sm bg-transparent text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
                              />
                            </div>
                            {visible.map((dep: Application) => (
                              <button
                                key={dep.id}
                                type="button"
                                onClick={() => {
                                  setSelectedDependencyId(dep.id);
                                  setSearchQuery("");
                                  setShowDependencyDropdown(false);
                                }}
                                className="w-full text-left px-3 py-2 text-sm border-b border-gray-100 dark:border-[#30363d] hover:bg-gray-50 dark:hover:bg-[#161b22] transition-colors flex items-center gap-2 last:border-b-0"
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
                            {filteredDropdownItems.length === 0 && (
                              <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400 text-center">
                                {availableDependencies.length > 0
                                  ? "All available applications are already dependencies"
                                  : "No dependencies found"}
                              </div>
                            )}
                            </>
                            );
                          })()}
                      </div>
                    )}

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

function ConfirmModal({
  title,
  message,
  onConfirm,
  onCancel,
  confirmText = "Confirm",
  variant = "default",
  reasonLabel,
}: {
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]" onClick={onCancel}>
      <div className="bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
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
            className={`px-4 py-2 text-white rounded transition-colors ${variant === "danger" ? "bg-red-600 hover:bg-red-700" : "bg-[#002244] hover:bg-[#003366]"}`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
