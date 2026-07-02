"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { dependencyApprovalsApi, type DependencyApproval } from "@/lib/api-client";
import { useAuth } from "@/contexts/AuthContext";
import {
  RefreshCw,
  X,
  ClipboardList,
  User,
  Check,
  XCircle,
  ShieldCheck,
  Undo2,
  Search,
} from "lucide-react";

type ActiveTab = "my-requests" | "admin-panel";
type StatusFilter = "all" | "PENDING" | "APPROVED" | "REJECTED";
type ActionFilter = "all" | "ADD" | "DELETE";

// ── Helpers ────────────────────────────────────────────────────────────────────

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  const diffMs = Date.now() - d.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHrs = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHrs / 24);
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHrs < 24) return `${diffHrs}h ago`;
  if (diffDays < 30) return `${diffDays}d ago`;
  return d.toLocaleDateString();
}

// ── Badge Components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: DependencyApproval["status"] }) {
  const styles: Record<DependencyApproval["status"], string> = {
    PENDING: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300",
    APPROVED: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300",
    REJECTED: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300",
  };
  const labels: Record<DependencyApproval["status"], string> = {
    PENDING: "🟡 Pending",
    APPROVED: "✅ Approved",
    REJECTED: "❌ Rejected",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  );
}

function ActionBadge({ action }: { action: DependencyApproval["action"] }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        action === "ADD"
          ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
          : "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300"
      }`}
    >
      {action === "ADD" ? "➕ ADD" : "🗑️ DELETE"}
    </span>
  );
}


// ── Toast ──────────────────────────────────────────────────────────────────────

function Toast({
  message,
  type,
  onClose,
}: {
  message: string;
  type: "success" | "error";
  onClose: () => void;
}) {
  useEffect(() => {
    const t = setTimeout(onClose, 3500);
    return () => clearTimeout(t);
  }, [onClose]);

  return (
    <div
      className={`fixed bottom-4 right-4 ${
        type === "success" ? "bg-green-600" : "bg-red-600"
      } text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 z-50`}
    >
      <span className="text-sm">{message}</span>
      <button onClick={onClose} className="text-white/80 hover:text-white">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// ── Reject Modal ───────────────────────────────────────────────────────────────

function RejectModal({
  approval,
  onConfirm,
  onCancel,
  loading,
}: {
  approval: DependencyApproval;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [reason, setReason] = useState("");

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onCancel}
    >
      <div
        className="bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-200 dark:border-[#30363d] bg-[#002244]">
          <h2 className="text-lg font-semibold text-white">Reject Request</h2>
          <p className="text-sm text-white/70 mt-0.5">
            {approval.applicationName} → {approval.dependencyName}
          </p>
        </div>

        <div className="p-6 space-y-4">
          <div className="flex flex-wrap gap-4 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-gray-400">Action:</span>
              <ActionBadge action={approval.action} />
            </div>
            <div>
              <span className="text-gray-400">Requested by: </span>
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {approval.requestedBy}
              </span>
            </div>
          </div>

          {approval.reason && (
            <div className="text-sm bg-gray-50 dark:bg-[#0d1117] rounded-lg p-3 text-gray-600 dark:text-gray-300">
              <span className="text-xs text-gray-400 block mb-1">Requester&apos;s reason:</span>
              {approval.reason}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Rejection Reason <span className="text-red-500">*</span>
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why this request is being rejected..."
              rows={3}
              autoFocus
              className="w-full px-3 py-2 border border-gray-300 dark:border-[#30363d] rounded-lg text-sm bg-white dark:bg-[#21262d] text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-red-500 resize-none"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-200 dark:border-[#30363d] bg-gray-50 dark:bg-[#0d1117] flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-[#21262d] rounded hover:bg-gray-200 dark:hover:bg-[#30363d] transition-colors text-sm"
          >
            Cancel
          </button>
          <button
            onClick={() => reason.trim() && onConfirm(reason.trim())}
            disabled={!reason.trim() || loading}
            className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm flex items-center gap-2"
          >
            {loading && (
              <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            )}
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Withdraw Modal ─────────────────────────────────────────────────────────────

function WithdrawModal({
  approval,
  onConfirm,
  onCancel,
  loading,
}: {
  approval: DependencyApproval;
  onConfirm: () => void;
  onCancel: () => void;
  loading: boolean;
}) {
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onCancel}
    >
      <div
        className="bg-white dark:bg-[#161b22] rounded-lg shadow-xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-200 dark:border-[#30363d]">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Withdraw Request
          </h2>
        </div>
        <div className="p-6 space-y-2">
          <p className="text-gray-600 dark:text-gray-300">
            Are you sure you want to withdraw your{" "}
            <span className="font-medium">
              {approval.action === "ADD" ? "add" : "delete"}
            </span>{" "}
            request for{" "}
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {approval.dependencyName}
            </span>
            ?
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500">
            The request will be cancelled. You can submit a new one anytime.
          </p>
        </div>
        <div className="px-6 py-4 border-t border-gray-200 dark:border-[#30363d] bg-gray-50 dark:bg-[#0d1117] flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-[#21262d] rounded hover:bg-gray-200 dark:hover:bg-[#30363d] transition-colors text-sm"
          >
            Keep it
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="px-4 py-2 bg-[#002244] text-white rounded hover:bg-[#003366] transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm flex items-center gap-2"
          >
            {loading && (
              <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            )}
            Yes, Withdraw
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Empty State ────────────────────────────────────────────────────────────────

function EmptyState({ tab }: { tab: ActiveTab }) {
  return (
    <div className="text-center py-16">
      <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-100 dark:bg-[#21262d] flex items-center justify-center">
        <ClipboardList className="w-8 h-8 text-gray-400 dark:text-gray-500" />
      </div>
      <p className="text-gray-500 dark:text-gray-400 font-medium">No requests found</p>
      <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
        {tab === "my-requests"
          ? "You haven't submitted any dependency requests yet"
          : "No requests match the current filters"}
      </p>
    </div>
  );
}

// ── Main View ──────────────────────────────────────────────────────────────────

export function DependencyApprovalsView() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<ActiveTab>("my-requests");
  const [approvals, setApprovals] = useState<DependencyApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [actionFilter, setActionFilter] = useState<ActionFilter>("all");
  const [rejectTarget, setRejectTarget] = useState<DependencyApproval | null>(null);
  const [withdrawTarget, setWithdrawTarget] = useState<DependencyApproval | null>(null);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const [search, setSearch] = useState("");

  const fetchApprovals = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await dependencyApprovalsApi.getAll();
      setApprovals(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch approval requests");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchApprovals();
  }, [fetchApprovals]);

  const handleTabChange = (tab: ActiveTab) => {
    // Block non-admin users from accessing the admin panel
    if (tab === "admin-panel" && !user?.isAdmin) return;
    setActiveTab(tab);
    // Default admin panel to PENDING, my-requests to all
    setStatusFilter(tab === "admin-panel" ? "PENDING" : "all");
    setActionFilter("all");
  };

  const myRequests = useMemo(() => {
    return approvals
      .filter((a) => a.requestedBy === user?.loginId)
      .filter((a) => statusFilter === "all" || a.status === statusFilter)
      .filter((a) => actionFilter === "all" || a.action === actionFilter)
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [approvals, user, statusFilter, actionFilter]);

  const adminRequests = useMemo(() => {
    return approvals
      .filter((a) => statusFilter === "all" || a.status === statusFilter)
      .filter((a) => actionFilter === "all" || a.action === actionFilter)
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [approvals, statusFilter, actionFilter]);

  const pendingCount = useMemo(
    () => approvals.filter((a) => a.status === "PENDING").length,
    [approvals]
  );

  const myRequestsCount = useMemo(
    () => approvals.filter((a) => a.requestedBy === user?.loginId).length,
    [approvals, user]
  );

  const handleApprove = async (approval: DependencyApproval) => {
    try {
      setActionLoading(approval.id);
      await dependencyApprovalsApi.approve(approval.id, user?.loginId ?? "unknown");
      setToast({
        message: `Approved: ${approval.applicationName} → ${approval.dependencyName}`,
        type: "success",
      });
      fetchApprovals();
    } catch (err) {
      setToast({
        message: err instanceof Error ? err.message : "Failed to approve request",
        type: "error",
      });
    } finally {
      setActionLoading(null);
    }
  };

  const handleWithdraw = async () => {
    if (!withdrawTarget) return;
    try {
      setActionLoading(withdrawTarget.id);
      await dependencyApprovalsApi.reject(
        withdrawTarget.id,
        user?.loginId ?? "unknown",
        "Withdrawn by requester"
      );
      setToast({ message: "Request withdrawn successfully", type: "success" });
      setWithdrawTarget(null);
      fetchApprovals();
    } catch (err) {
      setToast({
        message: err instanceof Error ? err.message : "Failed to withdraw request",
        type: "error",
      });
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (reason: string) => {
    if (!rejectTarget) return;
    try {
      setActionLoading(rejectTarget.id);
      await dependencyApprovalsApi.reject(rejectTarget.id, user?.loginId ?? "unknown", reason);
      setToast({
        message: `Rejected: ${rejectTarget.applicationName} → ${rejectTarget.dependencyName}`,
        type: "success",
      });
      setRejectTarget(null);
      fetchApprovals();
    } catch (err) {
      setToast({
        message: err instanceof Error ? err.message : "Failed to reject request",
        type: "error",
      });
    } finally {
      setActionLoading(null);
    }
  };


  const baseData = useMemo(() => {
    const data = activeTab === "my-requests" ? myRequests : adminRequests;
    if (!search.trim()) return data;
    const s = search.trim().toLowerCase();
    return data.filter((a) =>
      (a.applicationName ?? "").toLowerCase().includes(s) ||
      (a.dependencyName ?? "").toLowerCase().includes(s) ||
      (a.requestedBy ?? "").toLowerCase().includes(s) ||
      (a.approvedBy ?? "").toLowerCase().includes(s) ||
      (a.reason ?? "").toLowerCase().includes(s) ||
      (a.action ?? "").toLowerCase().includes(s) ||
      (a.status ?? "").toLowerCase().includes(s)
    );
  }, [activeTab, myRequests, adminRequests, search]);

  return (
    <div className="h-full flex flex-col bg-[#f8f9fa] dark:bg-[#0d1117]">
      <div className="flex-1 px-4 pt-3 pb-4 overflow-hidden flex flex-col">
      <div className="flex-1 flex flex-col rounded-lg shadow-sm overflow-hidden bg-white dark:bg-[#161b22] dark:border dark:border-[#30363d]">

      {/* ── Row 1: Title + Refresh ── */}
      <div className="flex-shrink-0 bg-[#f8f9fa] dark:bg-[#0d1117] px-4 py-2 flex items-center gap-3 border-b border-gray-200 dark:border-[#30363d]">
        <h1 className="text-lg font-bold text-[#002244] dark:text-gray-100 whitespace-nowrap">Dependency Approvals</h1>
        <div className="flex items-center gap-2 px-2.5 h-7 rounded-md border w-[220px] transition-all focus-within:ring-2 bg-white dark:bg-[#161b22] border-gray-200 dark:border-[#30363d] focus-within:border-[#0071CE] focus-within:ring-[#0071CE]/10 dark:focus-within:border-blue-500 dark:focus-within:ring-blue-500/20">
          <Search className="w-3.5 h-3.5 flex-shrink-0 text-gray-400 dark:text-gray-500" />
          <input
            type="text"
            placeholder="Search all columns…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 text-xs bg-transparent outline-none text-gray-800 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
          />
          {search && (
            <button onClick={() => setSearch("")} className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700">
              <X className="w-3.5 h-3.5 text-gray-400" />
            </button>
          )}
        </div>
        <div className="flex-1" />
        <button
          onClick={fetchApprovals}
          disabled={loading}
          className="flex items-center gap-1.5 px-2 h-7 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#21262d] rounded transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* ── Row 2: Filter Pills (left) + Count + Tab Switcher (right) ── */}
      <div className="flex-shrink-0 bg-[#f3f4f6] dark:bg-[#161b22] border-b border-gray-100 dark:border-[#30363d]/50 flex items-center">
        {/* Filter pills */}
        <div className="flex items-center gap-1.5 px-4 py-1.5">
          {(["all","PENDING","APPROVED","REJECTED"] as const).map(v => (
            <button
              key={v}
              onClick={() => setStatusFilter(v)}
              className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-colors ${
                statusFilter === v
                  ? "bg-[#002244] dark:bg-[#90EE90] text-white dark:text-[#002244]"
                  : "bg-gray-100 dark:bg-[#21262d] text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#30363d]"
              }`}
            >
              {v === "all" ? "All" : v.charAt(0) + v.slice(1).toLowerCase()}
            </button>
          ))}
          <div className="h-4 border-l border-gray-300 dark:border-[#30363d]" />
          {(["all","ADD","DELETE"] as const).map(v => (
            <button
              key={v}
              onClick={() => setActionFilter(v as ActionFilter)}
              className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-colors ${
                actionFilter === v
                  ? "bg-[#002244] dark:bg-[#90EE90] text-white dark:text-[#002244]"
                  : "bg-gray-100 dark:bg-[#21262d] text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#30363d]"
              }`}
            >
              {v === "all" ? "All Actions" : v}
            </button>
          ))}
        </div>
        {/* Count + Tab switcher on right */}
        <div className="flex items-center gap-3 ml-auto px-4 py-1.5">
          <span className="text-[11px] text-gray-500 dark:text-gray-400">
            {baseData.length} request{baseData.length !== 1 ? "s" : ""}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => handleTabChange("my-requests")}
              className={`flex items-center gap-1.5 px-3 h-6 rounded text-xs font-medium transition-colors ${
                activeTab === "my-requests"
                  ? "bg-[#002244] dark:bg-[#002244] text-white"
                  : "text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-[#21262d]"
              }`}
            >
              <User className="w-3.5 h-3.5" />
              My Requests
              {!loading && (
                <span className={`ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                  activeTab === "my-requests"
                    ? "bg-white/20 text-white"
                    : "bg-gray-200 dark:bg-[#30363d] text-gray-600 dark:text-gray-300"
                }`}>
                  {myRequestsCount}
                </span>
              )}
            </button>
            {user?.isAdmin && (
              <button
                onClick={() => handleTabChange("admin-panel")}
                className={`flex items-center gap-1.5 px-3 h-6 rounded text-xs font-medium transition-colors ${
                  activeTab === "admin-panel"
                    ? "bg-[#002244] dark:bg-[#002244] text-white"
                    : "text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-[#21262d]"
                }`}
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Admin Panel
                {!loading && pendingCount > 0 && (
                  <span className={`ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                    activeTab === "admin-panel"
                      ? "bg-white/20 text-white"
                      : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
                  }`}>
                    {pendingCount}
                  </span>
                )}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Table Content ── */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-10 h-10 border-4 border-[#002244] dark:border-blue-400 border-t-transparent dark:border-t-transparent rounded-full animate-spin" />
            <p className="mt-4 text-gray-500 dark:text-gray-400">Loading approval requests...</p>
          </div>
        ) : error ? (
          <div className="p-6">
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-center">
              <p className="text-red-600 dark:text-red-400 text-sm">{error}</p>
              <button
                onClick={fetchApprovals}
                className="mt-3 px-4 py-2 bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 rounded hover:bg-red-200 dark:hover:bg-red-900/60 transition-colors text-sm"
              >
                Try Again
              </button>
            </div>
          </div>
        ) : baseData.length === 0 ? (
          <EmptyState tab={activeTab} />
        ) : (
          <div className="flex-1 overflow-auto">
            <table className="w-full font-sans">
              <thead className="sticky top-0 z-10" style={{ transform: "translateZ(0)" }}>
                <tr className="bg-[#002244]">
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap border-r border-white/10">Application</th>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap border-r border-white/10">Dependency</th>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap border-r border-white/10">Action</th>
                  {activeTab === "admin-panel" && (
                    <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap border-r border-white/10">Requested By</th>
                  )}
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap border-r border-white/10">Status</th>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap border-r border-white/10">Submitted</th>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap border-r border-white/10">Reason</th>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide uppercase select-none whitespace-nowrap">
                    {activeTab === "my-requests" ? "Actioned By" : "Actions"}
                  </th>
                </tr>
              </thead>
                <tbody>
                  {baseData.map((approval, index) => {
                    const isOwnRequest = approval.requestedBy === user?.loginId;
                    const isPending = approval.status === "PENDING";
                    const isActioning = actionLoading === approval.id;

                    return (
                      <tr
                        key={approval.id}
                        className={`border-b border-gray-100 dark:border-[#30363d] hover:bg-[#f0f6ff] dark:hover:bg-[#1c2128] transition-colors ${
                          index % 2 === 1
                            ? "bg-[#fafbfc] dark:bg-[#0d1117]"
                            : "bg-white dark:bg-[#161b22]"
                        }`}
                      >
                        <td className="px-4 py-2.5 text-[14px] font-medium text-[#1a1a1a] dark:text-gray-100">
                          {approval.applicationName}
                        </td>
                        <td className="px-4 py-2.5 text-[14px] text-gray-700 dark:text-gray-300">
                          {approval.dependencyName}
                        </td>
                        <td className="px-4 py-2.5">
                          <ActionBadge action={approval.action} />
                        </td>
                        {activeTab === "admin-panel" && (
                          <td className="px-4 py-2.5 text-[14px] text-gray-700 dark:text-gray-300">
                            {approval.requestedBy}
                          </td>
                        )}
                        <td className="px-4 py-2.5">
                          <StatusBadge status={approval.status} />
                        </td>
                        <td className="px-4 py-2.5 text-[14px] text-gray-500 dark:text-gray-400">
                          {timeAgo(approval.createdAt)}
                        </td>
                        <td
                          className="px-4 py-2.5 text-[14px] text-gray-500 dark:text-gray-400 max-w-[180px] truncate"
                          title={approval.reason ?? ""}
                        >
                          {approval.reason ?? (
                            <span className="italic text-gray-300 dark:text-gray-600">—</span>
                          )}
                        </td>

                        {/* Last column: Actioned By / Withdraw (my-requests) or Actions (admin-panel) */}
                        <td className="px-4 py-2.5">
                          {activeTab === "my-requests" ? (
                            <div className="flex items-center gap-2">
                              {isPending ? (
                                <>
                                  <span className="text-xs italic text-gray-400 dark:text-gray-500">
                                    awaiting review
                                  </span>
                                  <button
                                    onClick={() => setWithdrawTarget(approval)}
                                    disabled={isActioning}
                                    title="Withdraw this request"
                                    className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors bg-gray-100 dark:bg-[#21262d] text-gray-600 dark:text-gray-300 hover:bg-red-50 dark:hover:bg-red-900/20 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50 disabled:cursor-not-allowed"
                                  >
                                    <Undo2 className="w-3 h-3" />
                                    Withdraw
                                  </button>
                                </>
                              ) : (
                                <div className="text-sm text-gray-500 dark:text-gray-400">
                                  {approval.approvedBy ? (
                                    <>
                                      <span>
                                        {approval.approvedBy === "system" ? (
                                          <span className="italic text-gray-400 dark:text-gray-500">
                                            system
                                          </span>
                                        ) : approval.approvedBy === user?.loginId ? (
                                          <span className="italic text-gray-400 dark:text-gray-500">
                                            withdrawn by you
                                          </span>
                                        ) : (
                                          approval.approvedBy
                                        )}
                                      </span>
                                      {approval.approvedAt && (
                                        <span className="text-gray-400 dark:text-gray-500 ml-1">
                                          · {timeAgo(approval.approvedAt)}
                                        </span>
                                      )}
                                    </>
                                  ) : (
                                    "—"
                                  )}
                                </div>
                              )}
                            </div>
                          ) : (
                            <div className="flex items-center gap-2">
                              {isPending ? (
                                <>
                                  <button
                                    onClick={() => handleApprove(approval)}
                                    disabled={isOwnRequest || isActioning}
                                    title={
                                      isOwnRequest
                                        ? "You cannot approve your own request"
                                        : "Approve this request"
                                    }
                                    className={`flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                                      isOwnRequest
                                        ? "bg-gray-100 dark:bg-[#21262d] text-gray-300 dark:text-gray-600 cursor-not-allowed"
                                        : "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-900/60"
                                    }`}
                                  >
                                    {isActioning ? (
                                      <div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
                                    ) : (
                                      <Check className="w-3 h-3" />
                                    )}
                                    Approve
                                  </button>
                                  <button
                                    onClick={() => setRejectTarget(approval)}
                                    disabled={isOwnRequest || isActioning}
                                    title={
                                      isOwnRequest
                                        ? "You cannot reject your own request"
                                        : "Reject this request"
                                    }
                                    className={`flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                                      isOwnRequest
                                        ? "bg-gray-100 dark:bg-[#21262d] text-gray-300 dark:text-gray-600 cursor-not-allowed"
                                        : "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-900/60"
                                    }`}
                                  >
                                    <XCircle className="w-3 h-3" />
                                    Reject
                                  </button>
                                </>
                              ) : (
                                <div className="text-sm text-gray-500 dark:text-gray-400">
                                  {approval.approvedBy === "system" ? (
                                    <span className="italic text-gray-400 dark:text-gray-500">
                                      system
                                    </span>
                                  ) : (
                                    approval.approvedBy ?? "—"
                                  )}
                                  {approval.approvedAt && (
                                    <span className="text-gray-400 dark:text-gray-500 ml-1">
                                      · {timeAgo(approval.approvedAt)}
                                    </span>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
      </div>
      </div>{/* card */}
      </div>{/* px-4 pt-3 pb-4 */}

      {/* Reject Modal */}
      {rejectTarget && (
        <RejectModal
          approval={rejectTarget}
          onConfirm={handleReject}
          onCancel={() => setRejectTarget(null)}
          loading={actionLoading === rejectTarget.id}
        />
      )}

      {/* Withdraw Modal */}
      {withdrawTarget && (
        <WithdrawModal
          approval={withdrawTarget}
          onConfirm={handleWithdraw}
          onCancel={() => setWithdrawTarget(null)}
          loading={actionLoading === withdrawTarget.id}
        />
      )}

      {/* Toast */}
      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}
    </div>
  );
}
