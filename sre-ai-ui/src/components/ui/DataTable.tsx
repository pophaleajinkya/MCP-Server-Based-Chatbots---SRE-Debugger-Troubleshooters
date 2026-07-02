"use client";

import React, { useState, useMemo, useCallback, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  flexRender,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
  type VisibilityState,
  type Row,
  type Table,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useTheme } from "@/contexts/ThemeContext";
import {
  Search,
  Columns,
  Filter,
  Download,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  X,
  AlignJustify,
  Check,
  Layers,
  List,
} from "lucide-react";

// ─── Types ─────────────────────────────────────────────────────────────────

type DensityType = "compact" | "standard" | "comfortable";
type ScrollMode = "paginated" | "virtual";

interface DataTableProps<TData> {
  data: TData[];
  columns: ColumnDef<TData, unknown>[];
  title?: string;
  /** Row height in pixels for virtual scroll mode */
  rowHeight?: number;
  /** Default page size for pagination mode */
  defaultPageSize?: number;
  /** Callback when a row is clicked */
  onRowClick?: (row: TData) => void;
  /** Currently selected row ID (for highlight) */
  selectedRowId?: string | number | null;
  /** Key extractor for row identity — receives row data and zero-based index */
  getRowId?: (row: TData, index: number) => string;
  /** Extra actions to render in the toolbar */
  toolbarActions?: React.ReactNode;
  /** Actions to render between the search box and the right-side toolbar buttons */
  prefixActions?: React.ReactNode;
  /** Enable global search (built-in toolbar search) */
  enableSearch?: boolean;
  /** Controlled global filter value — when provided, overrides internal search state */
  globalFilter?: string;
  /** Callback for controlled global filter changes */
  onGlobalFilterChange?: (value: string) => void;
  /** Enable column filters */
  enableFilters?: boolean;
  /** Enable column visibility toggle */
  enableColumnVisibility?: boolean;
  /** Enable export CSV */
  enableExport?: boolean;
  /** Enable density toggle */
  enableDensity?: boolean;
  /** Enable scroll mode toggle */
  enableScrollToggle?: boolean;
  /** Default column visibility */
  defaultColumnVisibility?: VisibilityState;
  /** Loading state */
  loading?: boolean;
  /** Error message */
  error?: string | null;
  /** Retry callback */
  onRetry?: () => void;
  /** Default sorting state */
  defaultSorting?: SortingState;
  /** Empty state message */
  emptyMessage?: string;
  /** Filter empty state message */
  filterEmptyMessage?: string;
}

// ─── Density config ────────────────────────────────────────────────────────

const DENSITY_CONFIG: Record<DensityType, { py: string; text: string; rowHeight: number }> = {
  compact:     { py: "py-1.5", text: "text-[12px]", rowHeight: 36 },
  standard:    { py: "py-2.5", text: "text-[14px]", rowHeight: 44 },
  comfortable: { py: "py-4",   text: "text-[15px]", rowHeight: 56 },
};

// ─── Toolbar dropdown wrapper ──────────────────────────────────────────────

function ToolbarDropdown({
  trigger,
  children,
  isOpen,
  onToggle
}: {
  trigger: React.ReactNode;
  children: React.ReactNode;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const triggerRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [dropStyle, setDropStyle] = useState<React.CSSProperties>({});

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const clickedTrigger = triggerRef.current?.contains(e.target as Node);
      const clickedDropdown = dropdownRef.current?.contains(e.target as Node);
      if (!clickedTrigger && !clickedDropdown && isOpen) onToggle();
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen, onToggle]);

  useEffect(() => {
    if (isOpen && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setDropStyle({
        position: "fixed",
        top: rect.bottom + 4,
        right: window.innerWidth - rect.right,
        zIndex: 9999,
        minWidth: 200,
      });
    }
  }, [isOpen]);

  const panel = isOpen ? (
    <div
      ref={dropdownRef}
      style={dropStyle}
      className="rounded-lg border shadow-xl bg-white dark:bg-[#161b22] dark:border-[#30363d] border-gray-200 overflow-hidden animate-in fade-in slide-in-from-top-1 duration-150"
    >
      {children}
    </div>
  ) : null;

  return (
    <div className="relative">
      <div ref={triggerRef} onClick={onToggle}>{trigger}</div>
      {typeof window !== "undefined" && panel
        ? ReactDOM.createPortal(panel, document.body)
        : null}
    </div>
  );
}

// ─── Custom filter functions ───────────────────────────────────────────────

/** Multi-select filter: value is string[], row must match any */
export function multiSelectFilterFn(row: Row<unknown>, columnId: string, filterValue: string[]) {
  if (!filterValue || filterValue.length === 0) return true;
  const cellValue = String(row.getValue(columnId) ?? "");
  return filterValue.includes(cellValue);
}
multiSelectFilterFn.autoRemove = (val: unknown) => !val || (Array.isArray(val) && val.length === 0);

/** Boolean filter: value is true/false/undefined */
export function booleanFilterFn(row: Row<unknown>, columnId: string, filterValue: boolean) {
  if (filterValue === undefined || filterValue === null) return true;
  return Boolean(row.getValue(columnId)) === filterValue;
}
booleanFilterFn.autoRemove = (val: unknown) => val === undefined || val === null;

// ─── Column filter components ──────────────────────────────────────────────

/** Multi-select facet filter — for columns with a small set of unique values (tier, tenant) */
function FacetFilter({ column, isDark }: { column: { getFilterValue: () => unknown; setFilterValue: (v: unknown) => void; getFacetedUniqueValues: () => Map<unknown, number> }; isDark: boolean }) {
  const [open, setOpen] = useState(false);
  const [dropLeft, setDropLeft] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = new Set((column.getFilterValue() as string[] | undefined) ?? []);
  const facets = column.getFacetedUniqueValues();
  const sortedValues = useMemo(() =>
    Array.from(facets.entries())
      .filter(([v]) => v != null && v !== "")
      .sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
    [facets]
  );

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Detect if dropdown would overflow viewport right edge — flip to open leftward
  useEffect(() => {
    if (open && ref.current) {
      const rect = ref.current.getBoundingClientRect();
      setDropLeft(rect.left + 200 > window.innerWidth - 16);
    }
  }, [open]);

  const toggle = (val: string) => {
    const next = new Set(selected);
    if (next.has(val)) next.delete(val); else next.add(val);
    column.setFilterValue(next.size ? Array.from(next) : undefined);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors ${
          selected.size > 0
            ? isDark ? "bg-blue-900/40 text-blue-300" : "bg-blue-100 text-blue-700"
            : isDark ? "text-gray-500 hover:text-gray-300 hover:bg-[#21262d]" : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
        }`}
      >
        <Filter className="w-3 h-3" />
        {selected.size > 0 && <span>{selected.size}</span>}
      </button>
      {open && (
        <div className={`absolute top-full mt-1 z-30 min-w-[180px] max-h-[280px] overflow-y-auto rounded-lg border shadow-xl ${
          dropLeft ? "right-0" : "left-0"
        } ${
          isDark ? "bg-[#161b22] border-[#30363d]" : "bg-white border-gray-200"
        }`} onClick={(e) => e.stopPropagation()}>
          {selected.size > 0 && (
            <button
              onClick={() => column.setFilterValue(undefined)}
              className={`w-full px-3 py-1.5 text-[11px] text-left border-b ${
                isDark ? "text-blue-400 hover:bg-[#21262d] border-[#30363d]" : "text-blue-600 hover:bg-blue-50 border-gray-100"
              }`}
            >
              Clear filter
            </button>
          )}
          {sortedValues.map(([val, count]) => (
            <label
              key={String(val)}
              className={`flex items-center gap-2 px-3 py-1.5 cursor-pointer transition-colors ${
                isDark ? "hover:bg-[#21262d]" : "hover:bg-gray-50"
              }`}
            >
              <div className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 ${
                selected.has(String(val))
                  ? "bg-[#0071CE] border-[#0071CE]"
                  : isDark ? "border-[#30363d]" : "border-gray-300"
              }`}>
                {selected.has(String(val)) && <Check className="w-2.5 h-2.5 text-white" />}
              </div>
              <span className={`text-[11px] flex-1 ${isDark ? "text-gray-300" : "text-gray-700"}`}>{String(val)}</span>
              <span className={`text-[10px] ${isDark ? "text-gray-600" : "text-gray-400"}`}>{count}</span>
              <input type="checkbox" checked={selected.has(String(val))} onChange={() => toggle(String(val))} className="sr-only" />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/** Boolean filter — Yes / No / All for boolean columns */
function BooleanFilter({ column, isDark }: { column: { getFilterValue: () => unknown; setFilterValue: (v: unknown) => void }; isDark: boolean }) {
  const val = column.getFilterValue();
  const options = [
    { label: "All", value: undefined },
    { label: "Yes", value: true },
    { label: "No", value: false },
  ];
  return (
    <div className="flex items-center gap-0.5">
      {options.map(opt => {
        const isActive = val === opt.value;
        return (
          <button
            key={opt.label}
            onClick={(e) => { e.stopPropagation(); column.setFilterValue(opt.value); }}
            className={`px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors ${
              isActive
                ? isDark ? "bg-blue-900/40 text-blue-300" : "bg-blue-100 text-blue-700"
                : isDark ? "text-gray-500 hover:text-gray-300" : "text-gray-400 hover:text-gray-600"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** Text search filter — for high-cardinality columns (namespace, appName) */
function TextColumnFilter({ column, isDark }: { column: { getFilterValue: () => unknown; setFilterValue: (v: unknown) => void }; isDark: boolean }) {
  const val = (column.getFilterValue() as string) ?? "";
  return (
    <input
      type="text"
      value={val}
      onChange={(e) => { column.setFilterValue(e.target.value || undefined); }}
      onClick={(e) => e.stopPropagation()}
      placeholder="Filter..."
      className={`w-full px-1.5 py-0.5 rounded border text-[10px] outline-none transition-colors ${
        isDark
          ? "bg-[#0d1117] border-[#30363d] text-gray-200 placeholder:text-gray-600 focus:border-blue-500"
          : "bg-white border-gray-200 text-gray-700 placeholder:text-gray-400 focus:border-[#0071CE]"
      }`}
    />
  );
}

// ─── Sort indicator ────────────────────────────────────────────────────────

function SortIndicator({ direction }: { direction: false | "asc" | "desc" }) {
  if (direction === "asc") return <ChevronUp className="w-3.5 h-3.5 text-[#90EE90]" />;
  if (direction === "desc") return <ChevronDown className="w-3.5 h-3.5 text-[#90EE90]" />;
  return <ChevronsUpDown className="w-3.5 h-3.5 opacity-30 group-hover:opacity-60 transition-opacity" />;
}

// ─── Main DataTable component ──────────────────────────────────────────────

export function DataTable<TData>({
  data,
  columns,
  title,
  defaultPageSize = 25,
  onRowClick,
  selectedRowId,
  getRowId,
  toolbarActions,
  prefixActions,
  enableSearch = true,
  enableFilters = true,
  enableColumnVisibility = true,
  enableExport = true,
  enableDensity = true,
  enableScrollToggle = true,
  defaultColumnVisibility = {},
  defaultSorting = [],
  loading = false,
  error = null,
  onRetry,
  emptyMessage = "No data found",
  filterEmptyMessage = "No results match your filters",
  globalFilter: controlledGlobalFilter,
  onGlobalFilterChange,
}: DataTableProps<TData>) {
  const { isDark } = useTheme();

  // ── State ──
  const [sorting, setSorting] = useState<SortingState>(defaultSorting);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(defaultColumnVisibility);
  const [internalGlobalFilter, setInternalGlobalFilter] = useState("");

  // Support both controlled (from parent) and uncontrolled (internal) global filter
  const globalFilter = controlledGlobalFilter !== undefined ? controlledGlobalFilter : internalGlobalFilter;
  const setGlobalFilter = onGlobalFilterChange ?? setInternalGlobalFilter;
  const [density, setDensity] = useState<DensityType>("standard");
  const [scrollMode, setScrollMode] = useState<ScrollMode>("paginated");

  // Toolbar dropdown state
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);
  const toggleDropdown = useCallback((name: string) => {
    setOpenDropdown(prev => prev === name ? null : name);
  }, []);

  // ── Table instance ──
  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnFilters, columnVisibility, globalFilter },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: scrollMode === "paginated" ? getPaginationRowModel() : undefined,
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    getRowId: getRowId ? (row, idx) => getRowId(row, idx) : undefined,
    initialState: {
      pagination: { pageSize: defaultPageSize },
    },
  });

  const { rows } = scrollMode === "paginated"
    ? table.getRowModel()
    : { rows: table.getFilteredRowModel().rows };

  const totalFiltered = table.getFilteredRowModel().rows.length;
  const hasActiveFilters = globalFilter || columnFilters.length > 0;
  const densityCfg = DENSITY_CONFIG[density];

  // ── Virtual scroll ──
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: scrollMode === "virtual" ? rows.length : 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => densityCfg.rowHeight,
    overscan: 15,
  });

  // ── Export CSV ──
  const handleExport = useCallback(() => {
    const visibleCols = table.getVisibleLeafColumns().filter(c => c.id !== "actions");
    const headerRow = visibleCols.map(c => {
      const header = c.columnDef.header;
      const label = typeof header === "string" ? header : c.id;
      return `"${label.replace(/"/g, '""')}"`;
    }).join(",");

    const dataRows = table.getFilteredRowModel().rows.map(row =>
      visibleCols.map(col => {
        const val = row.getValue(col.id);
        const str = val == null ? "" : String(val);
        return `"${str.replace(/"/g, '""')}"`;
      }).join(",")
    );

    const csv = [headerRow, ...dataRows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title?.toLowerCase().replace(/\s+/g, "-") || "data"}-${new Date().toISOString().split("T")[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [table, title]);

  // ── Loading state ──
  if (loading) {
    return (
      <div className={`flex items-center justify-center h-full ${isDark ? "bg-[#0d1117]" : "bg-[#f8f9fa]"}`}>
        <div className="flex flex-col items-center gap-4">
          <div className={`w-12 h-12 border-4 ${isDark ? "border-blue-400 border-t-transparent" : "border-[#002244] border-t-transparent"} rounded-full animate-spin`} />
          <p className={`${isDark ? "text-gray-300" : "text-gray-600"}`}>Loading {title?.toLowerCase() || "data"}...</p>
        </div>
      </div>
    );
  }

  // ── Error state ──
  if (error) {
    return (
      <div className={`flex items-center justify-center h-full ${isDark ? "bg-[#0d1117]" : "bg-[#f8f9fa]"}`}>
        <div className={`border rounded-lg p-6 max-w-md ${isDark ? "bg-red-900/20 border-red-800" : "bg-red-50 border-red-200"}`}>
          <h3 className={`font-semibold mb-2 ${isDark ? "text-red-300" : "text-red-800"}`}>Error</h3>
          <p className={`text-sm ${isDark ? "text-red-400" : "text-red-600"}`}>{error}</p>
          {onRetry && (
            <button onClick={onRetry} className={`mt-4 px-4 py-2 rounded transition-colors ${isDark ? "bg-red-900/30 text-red-300 hover:bg-red-900/50" : "bg-red-100 text-red-700 hover:bg-red-200"}`}>
              Try Again
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`h-full flex flex-col ${isDark ? "bg-[#0d1117]" : "bg-[#f8f9fa]"}`}>

      {/* ── Main content — reduced outer padding for data density ── */}
      <div className="flex-1 px-4 pt-3 pb-4 overflow-hidden flex flex-col">
        <div className={`flex-1 flex flex-col rounded-lg shadow-sm overflow-hidden ${isDark ? "bg-[#161b22] border border-[#30363d]" : "bg-white"}`}>

          {/* ── Toolbar ── */}
          <div className={`flex-shrink-0 border-b ${isDark ? "border-[#30363d]" : "border-gray-200"}`}>
            {/* Row 1: Title + Search + prefix actions (time frame, expand, refresh) */}
            <div className={`px-4 py-2 flex items-center gap-3 ${isDark ? "bg-[#0d1117]" : "bg-[#f8f9fa]"}`}>
              {title && (
                <h1 className={`text-lg font-bold whitespace-nowrap ${isDark ? "text-gray-100" : "text-[#002244]"}`}>{title}</h1>
              )}

              {enableSearch && (
                <div className={`flex items-center gap-2 px-2.5 h-7 rounded-md border w-[220px] transition-all focus-within:ring-2 ${
                  isDark
                    ? "bg-[#161b22] border-[#30363d] focus-within:border-blue-500 focus-within:ring-blue-500/20"
                    : "bg-white border-gray-200 focus-within:border-[#0071CE] focus-within:ring-[#0071CE]/10"
                }`}>
                  <Search className={`w-3.5 h-3.5 flex-shrink-0 ${isDark ? "text-gray-500" : "text-gray-400"}`} />
                  <input
                    type="text"
                    value={globalFilter ?? ""}
                    onChange={e => setGlobalFilter(e.target.value)}
                    placeholder="Search all columns…"
                    className={`flex-1 text-xs bg-transparent outline-none ${isDark ? "text-gray-100 placeholder:text-gray-500" : "text-gray-800 placeholder:text-gray-400"}`}
                  />
                  {globalFilter && (
                    <button onClick={() => setGlobalFilter("")} className={`p-0.5 rounded ${isDark ? "hover:bg-gray-700" : "hover:bg-gray-200"}`}>
                      <X className="w-3.5 h-3.5 text-gray-400" />
                    </button>
                  )}
                </div>
              )}

              {prefixActions}
            </div>

            {/* Row 2: Utility buttons + view toggles + stats — only when data exists */}
            <div className={`px-4 py-1.5 flex items-center gap-1.5 border-t ${isDark ? "bg-[#0d1117]/60 border-[#30363d]/50" : "bg-[#f3f4f6] border-gray-100"}`}>
              {/* Column Visibility */}
              {enableColumnVisibility && (
                <ToolbarDropdown
                  isOpen={openDropdown === "columns"}
                  onToggle={() => toggleDropdown("columns")}
                  trigger={
                    <button className={`h-7 flex items-center gap-1.5 px-2.5 rounded-md text-xs font-medium transition-colors ${
                      openDropdown === "columns"
                        ? isDark ? "bg-[#21262d] text-gray-100" : "bg-gray-200 text-gray-800"
                        : isDark ? "text-gray-400 hover:text-gray-200 hover:bg-[#21262d]" : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                    }`}>
                      <Columns className="w-3.5 h-3.5" />
                      Columns
                    </button>
                  }
                >
                  <div className="py-1 max-h-[300px] overflow-y-auto">
                    {table.getAllLeafColumns().filter(c => c.id !== "actions").map(column => (
                      <label
                        key={column.id}
                        className={`flex items-center gap-2.5 px-3 py-2 cursor-pointer transition-colors ${
                          isDark ? "hover:bg-[#21262d]" : "hover:bg-gray-50"
                        }`}
                      >
                        <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${
                          column.getIsVisible()
                            ? "bg-[#0071CE] border-[#0071CE]"
                            : isDark ? "border-[#30363d]" : "border-gray-300"
                        }`}>
                          {column.getIsVisible() && <Check className="w-3 h-3 text-white" />}
                        </div>
                        <input
                          type="checkbox"
                          checked={column.getIsVisible()}
                          onChange={column.getToggleVisibilityHandler()}
                          className="sr-only"
                        />
                        <span className={`text-sm ${isDark ? "text-gray-300" : "text-gray-700"}`}>
                          {typeof column.columnDef.header === "string" ? column.columnDef.header : column.id}
                        </span>
                      </label>
                    ))}
                  </div>
                </ToolbarDropdown>
              )}

              {/* Density */}
              {enableDensity && (
                <ToolbarDropdown
                  isOpen={openDropdown === "density"}
                  onToggle={() => toggleDropdown("density")}
                  trigger={
                    <button className={`h-7 flex items-center gap-1.5 px-2.5 rounded-md text-xs font-medium transition-colors ${
                      isDark ? "text-gray-400 hover:text-gray-200 hover:bg-[#21262d]" : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                    }`}>
                      <AlignJustify className="w-3.5 h-3.5" />
                      Density
                    </button>
                  }
                >
                  <div className="py-1">
                    {(["compact", "standard", "comfortable"] as DensityType[]).map(d => (
                      <button
                        key={d}
                        onClick={() => { setDensity(d); setOpenDropdown(null); }}
                        className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors ${
                          density === d
                            ? isDark ? "bg-blue-900/20 text-blue-300" : "bg-blue-50 text-blue-700"
                            : isDark ? "text-gray-300 hover:bg-[#21262d]" : "text-gray-700 hover:bg-gray-50"
                        }`}
                      >
                        {density === d && <Check className="w-3.5 h-3.5" />}
                        <span className={density === d ? "" : "ml-5"}>{d.charAt(0).toUpperCase() + d.slice(1)}</span>
                      </button>
                    ))}
                  </div>
                </ToolbarDropdown>
              )}

              {/* Scroll mode toggle */}
              {enableScrollToggle && (
                <button
                  onClick={() => setScrollMode(m => m === "paginated" ? "virtual" : "paginated")}
                  className={`h-7 flex items-center gap-1.5 px-2.5 rounded-md text-xs font-medium transition-colors ${
                    isDark ? "text-gray-400 hover:text-gray-200 hover:bg-[#21262d]" : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                  }`}
                  title={scrollMode === "paginated" ? "Switch to virtual scroll" : "Switch to pagination"}
                >
                  {scrollMode === "paginated" ? <List className="w-3.5 h-3.5" /> : <Layers className="w-3.5 h-3.5" />}
                  {scrollMode === "paginated" ? "Pages" : "Scroll"}
                </button>
              )}

              {/* Export */}
              {enableExport && (
                <button
                  onClick={handleExport}
                  className={`h-7 flex items-center gap-1.5 px-2.5 rounded-md text-xs font-medium transition-colors ${
                    isDark ? "text-gray-400 hover:text-gray-200 hover:bg-[#21262d]" : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                  }`}
                  title="Export CSV"
                >
                  <Download className="w-3.5 h-3.5" />
                  Export
                </button>
              )}

              {/* Spacer */}
              <div className="flex-1" />

              {/* Extra toolbar actions (e.g. Table/Timeline tabs) */}
              {toolbarActions}

              {/* Stats badge */}
              <div className={`text-[11px] font-medium px-2.5 py-1 rounded-full whitespace-nowrap ${
                hasActiveFilters
                  ? isDark ? "bg-blue-900/30 text-blue-300 border border-blue-800/50" : "bg-blue-50 text-blue-700 border border-blue-200"
                  : isDark ? "bg-[#161b22] text-gray-400 border border-[#30363d]" : "bg-gray-100 text-gray-500"
              }`}>
                {hasActiveFilters ? `${totalFiltered.toLocaleString()} of ` : ""}{data.length.toLocaleString()} {title?.toLowerCase() || "rows"}
              </div>
            </div>
          </div>

          {/* ── Table ── */}
          <div ref={parentRef} className="flex-1 overflow-auto">
            <table className="w-full" style={{ tableLayout: "fixed", borderSpacing: 0 }}>
              {/* Lock column widths via colgroup — prevents resize jitter during scroll/pagination */}
              <colgroup>
                {table.getVisibleLeafColumns().map(col => (
                  <col key={col.id} style={{ width: col.getSize() }} />
                ))}
              </colgroup>
              {/* Sticky header + filter row — translateZ(0) forces GPU layer to prevent blur */}
              <thead className="sticky top-0 z-10" style={{ transform: "translateZ(0)" }}>
                {table.getHeaderGroups().map(headerGroup => (
                  <tr key={headerGroup.id} className="bg-[#002244]">
                    {headerGroup.headers.map((header, idx) => (
                      <th
                        key={header.id}
                        onClick={header.column.getCanSort() ? header.column.getToggleSortingHandler() : undefined}
                        style={{ width: header.getSize() }}
                        className={`${header.id === "actions" ? "px-4" : "px-3"} py-2 text-left text-[10px] font-semibold text-[#90EE90] tracking-wide select-none uppercase whitespace-nowrap bg-[#002244] ${
                          header.column.getCanSort() ? "cursor-pointer group hover:bg-[#003366] transition-colors" : ""
                        } ${header.column.getIsSorted() ? "!bg-[#001a33]" : ""} ${
                          idx < headerGroup.headers.length - 1 ? "border-r border-white/10" : ""
                        }`}
                      >
                        <div className="flex items-center gap-1.5 truncate">
                          {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                          {header.column.getCanSort() && (
                            <SortIndicator direction={header.column.getIsSorted()} />
                          )}
                        </div>
                      </th>
                    ))}
                  </tr>
                ))}
                {/* Filter row — compact */}
                {enableFilters && (
                  <tr className={isDark ? "bg-[#161b22] border-b border-[#30363d]" : "bg-gray-50 border-b border-gray-200"}>
                    {table.getVisibleLeafColumns().map((column) => {
                      const filterType = (column.columnDef.meta as { filterType?: string })?.filterType;
                      const hasActiveFilter = column.getFilterValue() != null && column.getFilterValue() !== undefined;
                      return (
                        <th key={column.id} className={`px-2 py-1 ${
                          hasActiveFilter ? "border-b-2 border-[#0071CE]" : ""
                        }`}>
                          {filterType === "facet" && (
                            <FacetFilter column={column} isDark={isDark} />
                          )}
                          {filterType === "boolean" && (
                            <BooleanFilter column={column} isDark={isDark} />
                          )}
                          {filterType === "text" && (
                            <TextColumnFilter column={column} isDark={isDark} />
                          )}
                        </th>
                      );
                    })}
                  </tr>
                )}
              </thead>

              {/* Body */}
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={table.getVisibleLeafColumns().length} className={`px-5 py-12 text-center ${isDark ? "text-gray-500" : "text-gray-400"}`}>
                      <div className="flex flex-col items-center gap-2">
                        <Search className="w-8 h-8 opacity-30" />
                        <p className="text-sm font-medium">{hasActiveFilters ? filterEmptyMessage : emptyMessage}</p>
                        {hasActiveFilters && (
                          <button
                            onClick={() => { setGlobalFilter(""); setColumnFilters([]); }}
                            className={`text-xs px-3 py-1 rounded-full transition-colors ${
                              isDark ? "text-blue-400 hover:bg-blue-900/20" : "text-blue-600 hover:bg-blue-50"
                            }`}
                          >
                            Clear all filters
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ) : scrollMode === "virtual" ? (
                  // ── Virtual scroll rows ──
                  <>
                    {/* Spacer for virtual items before viewport */}
                    {virtualizer.getVirtualItems().length > 0 && (
                      <tr><td colSpan={table.getVisibleLeafColumns().length} style={{ height: virtualizer.getVirtualItems()[0]?.start ?? 0, padding: 0, border: "none" }} /></tr>
                    )}
                    {virtualizer.getVirtualItems().map(virtualRow => {
                      const row = rows[virtualRow.index];
                      const isSelected = selectedRowId != null && row.id === String(selectedRowId);
                      return (
                        <tr
                          key={row.id}
                          onClick={() => onRowClick?.(row.original)}
                          data-index={virtualRow.index}
                          style={{ height: virtualRow.size }}
                          className={`border-b transition-colors ${onRowClick ? "cursor-pointer" : ""} ${
                            isSelected
                              ? isDark ? "bg-blue-950/40 shadow-[inset_3px_0_0_#0071CE]" : "bg-blue-50 shadow-[inset_3px_0_0_#0071CE]"
                              : virtualRow.index % 2 === 0
                                ? isDark ? "bg-[#0d1117]" : "bg-white"
                                : isDark ? "bg-[#161b22]" : "bg-[#fafbfc]"
                          } ${isDark ? "border-[#30363d]" : "border-gray-100"} ${
                            isDark ? "hover:bg-[#1c2128]" : "hover:bg-[#f0f6ff]"
                          }`}
                        >
                          {row.getVisibleCells().map(cell => (
                            <td key={cell.id} className={`${cell.column.id === "actions" ? "px-6" : "px-4"} ${densityCfg.py} ${densityCfg.text} ${isDark ? "text-gray-200" : "text-[#1a1a1a]"} overflow-hidden`}>
                              <div className="truncate">{flexRender(cell.column.columnDef.cell, cell.getContext())}</div>
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                    {/* Spacer for virtual items after viewport */}
                    {virtualizer.getVirtualItems().length > 0 && (
                      <tr><td colSpan={table.getVisibleLeafColumns().length} style={{ height: virtualizer.getTotalSize() - (virtualizer.getVirtualItems().at(-1)?.end ?? 0), padding: 0, border: "none" }} /></tr>
                    )}
                  </>
                ) : (
                  // ── Paginated rows ──
                  rows.map((row, index) => {
                    const isSelected = selectedRowId != null && row.id === String(selectedRowId);
                    return (
                      <tr
                        key={row.id}
                        onClick={() => onRowClick?.(row.original)}
                        className={`border-b transition-colors ${onRowClick ? "cursor-pointer" : ""} ${
                          isSelected
                            ? isDark ? "bg-blue-950/40 shadow-[inset_3px_0_0_#0071CE]" : "bg-blue-50 shadow-[inset_3px_0_0_#0071CE]"
                            : index % 2 === 0
                              ? isDark ? "bg-[#0d1117]" : "bg-white"
                              : isDark ? "bg-[#161b22]" : "bg-[#fafbfc]"
                        } ${isDark ? "border-[#30363d]" : "border-gray-100"} ${
                          isDark ? "hover:bg-[#1c2128]" : "hover:bg-[#f0f6ff]"
                        }`}
                      >
                        {row.getVisibleCells().map(cell => (
                          <td key={cell.id} className={`${cell.column.id === "actions" ? "px-6" : "px-4"} ${densityCfg.py} ${densityCfg.text} ${isDark ? "text-gray-200" : "text-[#1a1a1a]"} overflow-hidden`}>
                            <div className="truncate">{flexRender(cell.column.columnDef.cell, cell.getContext())}</div>
                          </td>
                        ))}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* ── Footer / Pagination ── shown when multi-page OR filter returns 0 results (shows "0-0 of 0") */}
          {scrollMode === "paginated" && (table.getPageCount() > 1 || totalFiltered === 0) && (
            <div className={`px-4 py-3 border-t flex items-center justify-end gap-6 flex-shrink-0 ${
              isDark ? "bg-[#0d1117] border-[#30363d]" : "bg-[#fafafa] border-gray-200"
            }`}>
              <div className={`flex items-center gap-2 text-sm ${isDark ? "text-gray-300" : "text-gray-600"}`}>
                <span>Rows per page:</span>
                <select
                  value={table.getState().pagination.pageSize}
                  onChange={e => table.setPageSize(Number(e.target.value))}
                  className={`border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 ${
                    isDark
                      ? "border-[#30363d] bg-[#21262d] text-gray-100 focus:ring-blue-500"
                      : "border-gray-300 bg-white text-[#002244] focus:ring-[#002244]"
                  }`}
                >
                  {[10, 25, 50, 100].map(size => (
                    <option key={size} value={size}>{size}</option>
                  ))}
                </select>
              </div>
              <div className={`text-sm ${isDark ? "text-gray-300" : "text-gray-600"}`}>
                {totalFiltered === 0
                  ? "0–0 of 0"
                  : `${table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1}–${Math.min(
                      (table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
                      totalFiltered
                    )} of ${totalFiltered.toLocaleString()}`
                }
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => table.previousPage()}
                  disabled={!table.getCanPreviousPage()}
                  className={`p-1 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                    isDark ? "text-gray-300 hover:bg-[#21262d]" : "text-gray-600 hover:bg-gray-100"
                  }`}
                >
                  <ChevronLeft className="w-5 h-5" />
                </button>
                <span className={`text-sm font-medium min-w-[60px] text-center ${isDark ? "text-gray-300" : "text-gray-600"}`}>
                  {table.getState().pagination.pageIndex + 1} / {table.getPageCount()}
                </span>
                <button
                  onClick={() => table.nextPage()}
                  disabled={!table.getCanNextPage()}
                  className={`p-1 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                    isDark ? "text-gray-300 hover:bg-[#21262d]" : "text-gray-600 hover:bg-gray-100"
                  }`}
                >
                  <ChevronRight className="w-5 h-5" />
                </button>
              </div>
            </div>
          )}

          {/* Virtual scroll stats */}
          {scrollMode === "virtual" && (
            <div className={`px-4 py-2 border-t text-xs text-center flex-shrink-0 ${
              isDark ? "bg-[#0d1117] border-[#30363d] text-gray-500" : "bg-[#fafafa] border-gray-200 text-gray-400"
            }`}>
              Showing {totalFiltered.toLocaleString()} {title?.toLowerCase() || "rows"} · Scroll to browse
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Cell helper components ────────────────────────────────────────────────

/** Pill badge for tags like tenant, tier, status
 *  Uses explicit color classes (not dark: prefix) to avoid conflicts with parent text-color inheritance */
export function CellBadge({ children, variant = "default" }: { children: React.ReactNode; variant?: "default" | "blue" | "green" | "red" | "purple" | "orange" | "cyan" | "pink" | "indigo" }) {
  const { isDark } = useTheme();
  const colors: Record<string, string> = isDark ? {
    default:  "bg-gray-800 text-gray-400",
    blue:     "bg-blue-900/40 text-blue-300",
    green:    "bg-emerald-900/40 text-emerald-300",
    red:      "bg-red-900/40 text-red-300",
    purple:   "bg-purple-900/40 text-purple-300",
    orange:   "bg-orange-900/40 text-orange-300",
    cyan:     "bg-cyan-900/40 text-cyan-300",
    pink:     "bg-pink-900/40 text-pink-300",
    indigo:   "bg-indigo-900/40 text-indigo-300",
  } : {
    default:  "bg-gray-100 text-gray-600",
    blue:     "bg-blue-100 text-blue-700",
    green:    "bg-emerald-100 text-emerald-700",
    red:      "bg-red-100 text-red-600",
    purple:   "bg-purple-100 text-purple-700",
    orange:   "bg-orange-100 text-orange-700",
    cyan:     "bg-cyan-100 text-cyan-700",
    pink:     "bg-pink-100 text-pink-700",
    indigo:   "bg-indigo-100 text-indigo-700",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md font-medium text-inherit ${colors[variant] || colors.default}`}>
      {children}
    </span>
  );
}

/** Boolean check/cross cell */
export function CellBoolean({ value, trueLabel = "Yes", falseLabel = "No" }: { value: boolean; trueLabel?: string; falseLabel?: string }) {
  return value ? (
    <CellBadge variant="blue">{trueLabel}</CellBadge>
  ) : (
    <CellBadge variant="default">{falseLabel}</CellBadge>
  );
}

/** Truncated text with tooltip */
export function CellTruncated({ text, maxWidth = "200px" }: { text: string | null | undefined; maxWidth?: string }) {
  const { isDark } = useTheme();
  if (!text) return <span className={isDark ? "text-gray-600" : "text-gray-400"}>—</span>;
  return (
    <span className="block truncate" style={{ maxWidth }} title={text}>
      {text}
    </span>
  );
}

/** Copy icon SVG */
function CopyIcon({ className }: { className?: string }) {
  return (
    <svg className={className || "w-3 h-3"} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" strokeWidth="2" />
      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" strokeWidth="2" />
    </svg>
  );
}

/** Popup row with copy action */
function PopupCopyRow({ value, isDark, prefix = "" }: { value: string; isDark: boolean; prefix?: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(value).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className={`flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors ${
        isDark ? "hover:bg-[#21262d]" : "hover:bg-blue-50"
      }`}
    >
      <span className={`flex-1 text-inherit font-mono truncate ${isDark ? "text-gray-200" : "text-gray-700"}`}>
        {prefix}{value}
      </span>
      {copied ? (
        <Check className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
      ) : (
        <CopyIcon className={`w-3.5 h-3.5 flex-shrink-0 ${isDark ? "text-gray-500" : "text-gray-400"}`} />
      )}
    </div>
  );
}

/**
 * Fixed-position popup that renders via React Portal to avoid overflow clipping.
 * Calculates position from trigger element's bounding rect.
 */
function CopyPopup({
  triggerRef,
  values,
  isDark,
  prefix = "",
  onClose,
}: {
  triggerRef: React.RefObject<HTMLElement | null>;
  values: string[];
  isDark: boolean;
  prefix?: string;
  onClose: () => void;
}) {
  const popupRef = React.useRef<HTMLDivElement>(null);
  const [pos, setPos] = React.useState({ top: 0, left: 0 });

  // Calculate position from trigger element
  React.useEffect(() => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const popupHeight = values.length * 36 + 30; // estimate
      const spaceBelow = window.innerHeight - rect.bottom;
      // Show below trigger, or above if not enough space
      setPos({
        top: spaceBelow > popupHeight ? rect.bottom + 4 : rect.top - popupHeight - 4,
        left: Math.min(rect.left, window.innerWidth - 280),
      });
    }
  }, [triggerRef, values.length]);

  // Close on click outside
  React.useEffect(() => {
    const handle = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node) &&
          triggerRef.current && !triggerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose, triggerRef]);

  // Close on scroll (the table scrolls)
  React.useEffect(() => {
    const handle = () => onClose();
    window.addEventListener("scroll", handle, true); // capture phase to catch any scrollable parent
    return () => window.removeEventListener("scroll", handle, true);
  }, [onClose]);

  // Render as portal to avoid overflow clipping
  if (typeof document === "undefined") return null;
  return ReactDOM.createPortal(
    <div
      ref={popupRef}
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 9999 }}
      className={`min-w-[200px] max-w-[320px] rounded-lg border shadow-xl py-1 ${
        isDark ? "bg-[#161b22] border-[#30363d]" : "bg-white border-gray-200"
      }`}
      onClick={(e) => e.stopPropagation()}
    >
      <div className={`px-3 py-1.5 text-[9px] uppercase tracking-wider font-semibold flex items-center gap-1.5 ${isDark ? "text-gray-500" : "text-gray-400"}`}>
        <CopyIcon className="w-2.5 h-2.5" />
        Click to copy
      </div>
      <div className={`border-t ${isDark ? "border-[#30363d]" : "border-gray-100"}`}>
        {values.map((v, i) => (
          <PopupCopyRow key={i} value={v} isDark={isDark} prefix={prefix} />
        ))}
      </div>
    </div>,
    document.body
  );
}

/** Copyable text cell — click to see popup with values + copy. Uses CSS truncation to fill available width. */
export function CellCopyable({ text }: { text: string | null | undefined; maxChars?: number }) {
  const { isDark } = useTheme();
  const [showPopup, setShowPopup] = React.useState(false);
  const triggerRef = React.useRef<HTMLSpanElement>(null);

  if (!text) return <span className={isDark ? "text-gray-600" : "text-gray-400"}>—</span>;

  const values = text.includes(",") ? text.split(",").map(s => s.trim()).filter(Boolean) : [text];

  return (
    <>
      <span
        ref={triggerRef}
        onClick={(e) => { e.stopPropagation(); setShowPopup(!showPopup); }}
        className={`flex items-center gap-1 cursor-pointer text-inherit hover:underline decoration-dotted underline-offset-2 w-full ${
          isDark ? "decoration-gray-600" : "decoration-gray-300"
        }`}
        title={text}
      >
        <span className="truncate">{values[0]}</span>
        {values.length > 1 && <span className="text-[9px] text-gray-400 flex-shrink-0">+{values.length - 1}</span>}
      </span>
      {showPopup && (
        <CopyPopup
          triggerRef={triggerRef}
          values={values}
          isDark={isDark}
          onClose={() => setShowPopup(false)}
        />
      )}
    </>
  );
}

/** Compact list cell with click popup for copy (slack, xmatters, emails). Uses CSS truncation. */
export function CellList({ items, variant = "default", prefix = "" }: { items: string[] | null | undefined; variant?: "default" | "blue" | "purple" | "green"; prefix?: string; truncateAt?: number }) {
  const { isDark } = useTheme();
  const [showPopup, setShowPopup] = React.useState(false);
  const triggerRef = React.useRef<HTMLSpanElement>(null);

  if (!items?.length) return <span className={isDark ? "text-gray-600" : "text-gray-400"}>—</span>;

  return (
    <>
      <span
        ref={triggerRef}
        onClick={(e) => { e.stopPropagation(); setShowPopup(!showPopup); }}
        className="cursor-pointer max-w-full inline-flex"
        title={items.map(i => `${prefix}${i}`).join(", ")}
      >
        <CellBadge variant={variant}>
          <span className="truncate max-w-[100px]">{prefix}{items[0]}</span>
          {items.length > 1 && <span className="ml-1 text-[9px] opacity-60 flex-shrink-0">+{items.length - 1}</span>}
        </CellBadge>
      </span>
      {showPopup && (
        <CopyPopup
          triggerRef={triggerRef}
          values={items}
          isDark={isDark}
          prefix={prefix}
          onClose={() => setShowPopup(false)}
        />
      )}
    </>
  );
}
