"use client";

import { useState } from "react";
import DOMPurify from "dompurify";
import {
  ResponsiveContainer,
  LineChart, Line,
  AreaChart, Area,
  BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { DataTable } from "./ui/DataTable";

/**
 * A2UI v0.9 renderer — supports ONLY v0.9 flat format.
 *
 * v0.9 Basic Catalog (14 components):
 *   Layout:      Row, Column, List
 *   Display:     Text, Image, Icon, Divider
 *   Interactive: Button, TextField, CheckBox, Slider, DateTimeInput, ChoicePicker
 *   Container:   Card, Modal, Tabs
 *
 * Custom catalog extensions (used by health-mcp):
 *   Table, Chart
 *
 * v0.9 rules enforced:
 *   - `component` field (NOT `type`)
 *   - Props are top-level on component (NOT inside `props: {}`)
 *   - Card uses `child` (single ID)
 *   - Button uses `child` (ID) + `action`
 *   - Text uses `variant` (h1-h5, body, caption)
 *   - Chart uses `chartType`, `xAxis.labels`, `series`
 *
 * v0.8 and mixed formats are NOT supported. Migrate to v0.9.
 * Unknown components degrade gracefully as labeled containers.
 */

/**
 * A2UI v0.9 component shape — flat format only.
 *
 * v0.9 rules:
 * - `component` is a string ("Text", "Card", etc.) — NOT `type`
 * - Props are top-level on the component — NOT wrapped in `props: {}`
 * - Card uses `child` (single ID) — NOT `title`/`subtitle`
 * - Button uses `child` (ID) + `action` — NOT `label`/`url`
 * - Text uses `variant` (h1-h5, body, caption)
 * - Chart uses `chartType`, `xAxis.labels`, `series`
 */
interface A2UIComponent {
  id: string;
  component: string;
  children?: string[];
  child?: string;
  text?: string;
  variant?: string;
  action?: Record<string, unknown>;
  justify?: string;
  align?: string;
  name?: string;
  label?: string;
  value?: unknown;
  options?: Array<{ label: string; value: string } | string>;
  tabItems?: Array<{ title: string; child: string }>;
  entryPointChild?: string;
  contentChild?: string;
  axis?: string;
  fit?: string;
  weight?: number;
  chartType?: string;
  title?: string;
  xAxis?: Record<string, unknown>;
  series?: unknown[];
  columns?: string[];
  rows?: unknown[][];
  [key: string]: unknown;
}

interface A2UIMessage {
  version?: string;
  createSurface?: Record<string, unknown>;
  updateComponents?: { surfaceId?: string; components?: A2UIComponent[] };
  updateDataModel?: Record<string, unknown>;
}

interface A2UIRendererProps {
  data: unknown;
}

export function A2UIRenderer({ data }: A2UIRendererProps) {
  const messages = Array.isArray(data) ? (data as A2UIMessage[]) : [data as A2UIMessage];

  return (
    <div className="a2ui-root flex flex-col gap-3">
      {messages.map((msg, idx) => {
        const components = msg?.updateComponents?.components ?? [];
        if (components.length === 0) return null;

        const componentMap = new Map(components.map((c) => [c.id, c]));

        // Find roots: components not referenced as children by any other component
        const childIds = new Set(components.flatMap((c) => [
          ...(c.children ?? []),
          ...(c.child ? [c.child] : []),
          ...(c.entryPointChild ? [c.entryPointChild] : []),
          ...(c.contentChild ? [c.contentChild] : []),
          ...(c.tabItems?.map((t) => t.child) ?? []),
        ]));
        const roots = components.filter((c) => !childIds.has(c.id));
        const rootComps = roots.length > 0 ? roots : [components[0]];

        return (
          <div key={msg.updateComponents?.surfaceId ?? idx} className="flex flex-col gap-2">
            {rootComps.map((root) => (
              <RenderComponent key={root.id} comp={root} componentMap={componentMap} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function RenderComponent({ comp, componentMap }: { comp: A2UIComponent; componentMap: Map<string, A2UIComponent> }) {
  const resolveChild = (id?: string) => id ? componentMap.get(id) : undefined;
  const resolveChildren = (ids?: string[]) =>
    ids?.map((id) => componentMap.get(id)).filter(Boolean) as A2UIComponent[] | undefined;
  const children = resolveChildren(comp.children);
  const singleChild = resolveChild(comp.child);
  const justify = comp.justify;
  const align = comp.align;

  const justifyClass: Record<string, string> = {
    start: "justify-start", end: "justify-end", center: "justify-center",
    spaceBetween: "justify-between", spaceAround: "justify-around", spaceEvenly: "justify-evenly",
  };
  const alignClass: Record<string, string> = {
    start: "items-start", end: "items-end", center: "items-center", stretch: "items-stretch",
  };

  switch (comp.component) {
    // ═══════════════════════════════════════════════════════════════════════
    // LAYOUT (v0.9 spec)
    // ═══════════════════════════════════════════════════════════════════════

    case "Row":
      return (
        <div className={`flex flex-row gap-2 flex-wrap ${justifyClass[justify ?? ""] ?? ""} ${alignClass[align ?? ""] ?? "items-center"}`}>
          {children?.map((c) => <RenderComponent key={c.id} comp={c} componentMap={componentMap} />)}
        </div>
      );

    case "Column":
      return (
        <div className={`flex flex-col gap-2 ${justifyClass[justify ?? ""] ?? ""} ${alignClass[align ?? ""] ?? ""}`}>
          {children?.map((c) => <RenderComponent key={c.id} comp={c} componentMap={componentMap} />)}
        </div>
      );

    case "List": {
      const direction = comp.direction;
      const cls = direction === "horizontal" ? "flex flex-row gap-2 overflow-x-auto" : "flex flex-col gap-1 max-h-96 overflow-y-auto";
      return (
        <div className={cls}>
          {children?.map((c) => <RenderComponent key={c.id} comp={c} componentMap={componentMap} />)}
        </div>
      );
    }

    // ═══════════════════════════════════════════════════════════════════════
    // DISPLAY (v0.9 spec)
    // ═══════════════════════════════════════════════════════════════════════

    case "Text": {
      const text = String(comp.text ?? "");
      const variant = (comp.variant ?? "body") as string;
      const cls: Record<string, string> = {
        h1: "text-2xl font-bold", h2: "text-xl font-semibold", h3: "text-lg font-semibold",
        h4: "text-base font-semibold", h5: "text-sm font-semibold",
        caption: "text-xs text-gray-500 dark:text-gray-400",
        body: "text-sm",
      };
      // If text contains markdown headings or newlines, use MarkdownRenderer
      if (text.includes("\n") || text.startsWith("#")) {
        return <div className={cls[variant] ?? "text-sm"}><MarkdownRenderer content={text} /></div>;
      }
      if (["h1", "h2", "h3", "h4", "h5"].includes(variant)) {
        return <div className={cls[variant]}>{text}</div>;
      }
      return <p className={cls[variant] ?? "text-sm"} dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(inlineMarkdown(text)) }} />;
    }

    case "Image": {
      const src = String(comp.url ?? "");
      const alt = String((comp as any).alt ?? "");
      const fit = (comp.fit ?? "contain") as string;
      if (!src) return null;
      // eslint-disable-next-line @next/next/no-img-element
      return <img src={src} alt={alt} className={`rounded-lg max-w-full object-${fit === "cover" ? "cover" : "contain"}`} />;
    }

    case "Icon": {
      const name = String(comp.name ?? "");
      const size = 20;
      const color = "currentColor";
      return (
        <span className="inline-flex items-center justify-center" style={{ width: size, height: size, color }} title={name} role="img" aria-label={name}>
          {getIconSvg(name, size)}
        </span>
      );
    }

    case "Divider":
      return <hr className={`border-gray-200 dark:border-gray-700 my-1 ${comp.axis === "vertical" ? "w-px h-full border-l" : ""}`} />;

    // ═══════════════════════════════════════════════════════════════════════
    // INTERACTIVE (v0.9 spec)
    // ═══════════════════════════════════════════════════════════════════════

    case "Button": {
      const childComp = singleChild;
      const variant = (comp.variant ?? "primary") as string;
      const action = comp.action;
      const base = "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors";
      const variantCls = variant === "secondary" || variant === "outlined"
        ? "border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
        : variant === "danger" || variant === "destructive"
        ? "bg-red-600 text-white hover:bg-red-700"
        : "bg-[#0071CE] text-white hover:bg-[#005fa3]";
      const content = childComp
        ? <RenderComponent comp={childComp} componentMap={componentMap} />
        : <span>Button</span>;
      const event = action?.event as Record<string, unknown> | undefined;
      const eventData = event?.data as Record<string, unknown> | undefined;
      const href = eventData?.url ? String(eventData.url) : "#";
      return <a href={href} target="_blank" rel="noopener noreferrer" className={`${base} ${variantCls}`}>{content}<ExternalLinkIcon /></a>;
    }

    case "TextField": {
      const label = String(comp.label ?? "");
      const placeholder = String((comp as any).placeholder ?? "");
      const val = String(comp.value ?? "");
      const fieldType = String((comp as any).textFieldType ?? "shortText");
      const isLong = fieldType === "longText";
      return (
        <div className="flex flex-col gap-1">
          {label && <label className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</label>}
          {isLong
            ? <textarea defaultValue={val} placeholder={placeholder} rows={3} className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1a2233] text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-[#0071CE] focus:border-transparent" />
            : <input type={fieldType === "number" ? "number" : fieldType === "obscured" ? "password" : "text"} defaultValue={val} placeholder={placeholder} className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1a2233] text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-[#0071CE] focus:border-transparent" />
          }
        </div>
      );
    }

    case "CheckBox": {
      const label = String(comp.label ?? "");
      const checked = Boolean(comp.value ?? false);
      return (
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" defaultChecked={checked} className="w-4 h-4 rounded border-gray-300 text-[#0071CE] focus:ring-[#0071CE]" />
          {label}
        </label>
      );
    }

    case "Slider": {
      const min = ((comp as any).minValue ?? 0) as number;
      const max = ((comp as any).maxValue ?? 100) as number;
      const val = (comp.value ?? min) as number;
      const label = String(comp.label ?? "");
      return (
        <div className="flex flex-col gap-1">
          {label && <label className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</label>}
          <input type="range" min={min} max={max} defaultValue={typeof val === "number" ? val : min} className="w-full accent-[#0071CE]" />
        </div>
      );
    }

    case "DateTimeInput": {
      const label = String(comp.label ?? "");
      const val = String(comp.value ?? "");
      const enableDate = ((comp as any).enableDate ?? true) as boolean;
      const enableTime = ((comp as any).enableTime ?? false) as boolean;
      const inputType = enableDate && enableTime ? "datetime-local" : enableTime ? "time" : "date";
      return (
        <div className="flex flex-col gap-1">
          {label && <label className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</label>}
          <input type={inputType} defaultValue={val} className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1a2233] text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-[#0071CE]" />
        </div>
      );
    }

    case "ChoicePicker": {
      const label = String(comp.label ?? "");
      const opts = (comp.options ?? []) as Array<{ label: string; value: string } | string>;
      const placeholder = "Select...";
      const maxSel = ((comp as any).maxAllowedSelections ?? 1) as number;
      return (
        <div className="flex flex-col gap-1">
          {label && <label className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</label>}
          <select multiple={maxSel > 1} className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-[#1a2233] text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-[#0071CE]">
            {maxSel <= 1 && <option value="">{placeholder}</option>}
            {opts.map((opt, i) => {
              const v = typeof opt === "string" ? opt : opt.value;
              const l = typeof opt === "string" ? opt : opt.label;
              return <option key={i} value={v}>{l}</option>;
            })}
          </select>
        </div>
      );
    }

    // ═══════════════════════════════════════════════════════════════════════
    // CONTAINER (v0.9 spec)
    // ═══════════════════════════════════════════════════════════════════════

    case "Card": {
      const hasContent = singleChild || (children && children.length > 0);
      return (
        <div className="rounded-lg border p-4 shadow-sm bg-white dark:bg-[#1a2233] dark:border-gray-700">
          {hasContent ? (
            <div className="flex flex-col gap-2">
              {singleChild && <RenderComponent comp={singleChild} componentMap={componentMap} />}
              {children?.map((c) => <RenderComponent key={c.id} comp={c} componentMap={componentMap} />)}
            </div>
          ) : null}
        </div>
      );
    }

    case "Modal":
      return <ModalComponent comp={comp} componentMap={componentMap} />;

    case "Tabs":
      return <TabsComponent comp={comp} componentMap={componentMap} />;

    // ═══════════════════════════════════════════════════════════════════════
    // CUSTOM CATALOG EXTENSIONS (Table, Chart)
    // ═══════════════════════════════════════════════════════════════════════

    case "Table": {
      const columns = (comp.columns ?? []) as string[];
      const rows = (comp.rows ?? []) as (string | unknown)[][];
      if (columns.length === 0 && rows.length === 0) return null;
      const cols = columns.length > 0 ? columns : (rows[0] && Array.isArray(rows[0]) ? rows[0].map((_, i) => `Col ${i + 1}`) : []);

      // Format columns for DataTable with content-aware sizing
      const CHAR_PX   = 8;   // avg px per character at 14px font
      const COL_PAD   = 32;  // px-4 (16px each side)
      const MIN_WIDTH = 80;
      const MAX_WIDTH = 320;

      const tableColumns = cols.map((col, index) => {
        const headerLen  = String(col).length;
        const maxDataLen = rows.reduce((max, row) => {
          const cell = String((Array.isArray(row) ? row : [row])[index] ?? "");
          return Math.max(max, cell.length);
        }, 0);
        const size = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.max(headerLen, maxDataLen) * CHAR_PX + COL_PAD));
        return { id: `col_${index}`, header: String(col), accessorKey: `col_${index}`, size };
      });

      // Format rows into Record objects
      const tableData = rows.map(row => {
        const rowObj: Record<string, string> = {};
        (Array.isArray(row) ? row : [row]).forEach((cell, index) => {
          rowObj[`col_${index}`] = formatCell(String(cell));
        });
        return rowObj;
      });

      return (
        <div className="a2ui-table-wrapper rounded-lg border dark:border-gray-700 overflow-hidden">
          <DataTable 
            columns={tableColumns} 
            data={tableData} 
            defaultPageSize={25}
            enableSearch={false}
          />
        </div>
      );
    }

    case "Chart":
      return <ChartComponent comp={comp} />;

    // ═══════════════════════════════════════════════════════════════════════
    // UNKNOWN — forward-compatible fallback
    // ═══════════════════════════════════════════════════════════════════════

    default:
      if (children && children.length > 0) {
        return (
          <div className="rounded border p-2 dark:border-gray-700">
            <div className="text-xs text-gray-400 mb-1">{comp.component}</div>
            <div className="flex flex-col gap-2">
              {children.map((c) => <RenderComponent key={c.id} comp={c} componentMap={componentMap} />)}
            </div>
          </div>
        );
      }
      if (singleChild) return <RenderComponent comp={singleChild} componentMap={componentMap} />;
      return null;
  }
}

// ─── Utilities ────────────────────────────────────────────────────────────────

// ─── Stateful components (extracted to satisfy React hooks rules) ──────────────

function ModalComponent({ comp, componentMap }: { comp: A2UIComponent; componentMap: Map<string, A2UIComponent> }) {
  const [open, setOpen] = useState(false);
  const entry = comp.entryPointChild ? componentMap.get(comp.entryPointChild) : undefined;
  const content = comp.contentChild ? componentMap.get(comp.contentChild) : undefined;
  return (
    <>
      {entry && <div onClick={() => setOpen(true)} className="cursor-pointer"><RenderComponent comp={entry} componentMap={componentMap} /></div>}
      {open && content && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setOpen(false)}>
          <div className="bg-white dark:bg-[#1a2233] rounded-xl shadow-xl p-6 max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <RenderComponent comp={content} componentMap={componentMap} />
            <button onClick={() => setOpen(false)} className="mt-4 px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800">Close</button>
          </div>
        </div>
      )}
    </>
  );
}

// Chart type options for the switcher (not shown for pie)
const CHART_TYPE_OPTIONS = [
  { key: "line", label: "Line" },
  { key: "area", label: "Area" },
  { key: "bar",  label: "Bar"  },
] as const;

function ChartComponent({ comp }: { comp: A2UIComponent }) {
  const origType = String(comp.chartType ?? "line");
  const isPie    = origType === "pie";

  const [hiddenSeries,  setHiddenSeries]  = useState<Set<string>>(new Set());
  const [activeType,    setActiveType]    = useState(isPie ? "pie" : origType);
  const [fullscreen,    setFullscreen]    = useState(false);

  const title     = String(comp.title ?? "");
  const xAxis     = (comp.xAxis ?? {}) as Record<string, unknown>;
  const labels    = (xAxis.labels ?? []) as string[];
  const rawSeries = (comp.series ?? []) as unknown[];

  const toggleSeries = (label: string) =>
    setHiddenSeries(prev => {
      const next = new Set(prev);
      next.has(label) ? next.delete(label) : next.add(label);
      return next;
    });

  // ── Pie chart ──────────────────────────────────────────────────────────
  if (isPie) {
    const pieData = rawSeries.flatMap((s: any) => {
      if (s.data && Array.isArray(s.data) && s.data[0]?.name !== undefined) return s.data;
      return [];
    }) as Array<{ name: string; value: number }>;
    if (pieData.length === 0) return title ? <div className="text-sm text-gray-500">{title} (no data)</div> : null;
    return (
      <div className="rounded-lg border dark:border-gray-700 p-3">
        <div className="flex items-center justify-between mb-2">
          {title && <div className="text-sm font-semibold">{title}</div>}
          <button onClick={() => setFullscreen(f => !f)}
            className="ml-2 p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-[#0071CE] transition-colors"
            title="Full screen">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
            </svg>
          </button>
        </div>
        {fullscreen && (
          <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" onClick={() => setFullscreen(false)}>
            <div className="bg-white dark:bg-[#1a2233] rounded-xl shadow-2xl p-6 w-full max-w-4xl" onClick={e => e.stopPropagation()}>
              {title && <div className="text-base font-semibold mb-4">{title}</div>}
              <ResponsiveContainer width="100%" height={500}>
                <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={180}
                    label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`}>
                    {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={(v: unknown) => typeof v === "number" ? v.toLocaleString() : String(v)} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
              <button onClick={() => setFullscreen(false)} className="mt-4 px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800">Close</button>
            </div>
          </div>
        )}
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie
              data={pieData}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={100}
              label={({ name, percent }: { name?: string; percent?: number }) =>
                (percent ?? 0) >= 0.05 ? `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%` : ""
              }
              labelLine={false}
            >
              {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip formatter={(v: unknown) => typeof v === "number" ? v.toLocaleString() : String(v)} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  // ── Line / Area / Bar chart ─────────────────────────────────────────────
  const series = rawSeries.map((s: any) => ({
    label: s.label ?? s.name ?? "Series",
    data:  (s.data ?? []) as (number | null)[],
  }));
  if (labels.length === 0 || series.length === 0)
    return title ? <div className="text-sm text-gray-500">{title} (no data)</div> : null;

  const chartData = labels.map((label, i) => {
    const row: Record<string, string | number | null> = { label };
    series.forEach(s => { row[s.label] = s.data[i] ?? null; });
    return row;
  });

  // Shared legend with click-to-hide/show
  const legendProps = series.length > 1 ? {
    wrapperStyle: { fontSize: 11 } as React.CSSProperties,
    formatter:  (value: string) => (
      <span style={{
        color:          hiddenSeries.has(value) ? "#6b7280" : undefined,
        textDecoration: hiddenSeries.has(value) ? "line-through" : undefined,
        cursor:         "pointer",
      }}>{value}</span>
    ),
    onClick: (e: any) => e?.dataKey && toggleSeries(String(e.dataKey)),
  } : null;

  const ChartBody = ({ height }: { height: number }) => (
    <ResponsiveContainer width="100%" height={height}>
      {activeType === "bar" ? (
        <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
          <XAxis dataKey="label" tick={CHART_TICK_STYLE} />
          <YAxis tick={CHART_TICK_STYLE} width={40} />
          <Tooltip contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
          {legendProps && <Legend {...legendProps} />}
          {series.map((s, i) => (
            <Bar key={s.label} dataKey={s.label} fill={COLORS[i % COLORS.length]}
              radius={[2, 2, 0, 0]} maxBarSize={40} hide={hiddenSeries.has(s.label)} />
          ))}
        </BarChart>
      ) : activeType === "area" ? (
        <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
          <XAxis dataKey="label" tick={CHART_TICK_STYLE} />
          <YAxis tick={CHART_TICK_STYLE} width={40} />
          <Tooltip contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
          {legendProps && <Legend {...legendProps} />}
          {series.map((s, i) => (
            <Area key={s.label} type="monotone" dataKey={s.label}
              stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]}
              fillOpacity={hiddenSeries.has(s.label) ? 0 : 0.12}
              strokeWidth={hiddenSeries.has(s.label) ? 0 : 1.5}
              dot={false} activeDot={{ r: 3 }} connectNulls hide={hiddenSeries.has(s.label)} />
          ))}
        </AreaChart>
      ) : (
        <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
          <XAxis dataKey="label" tick={CHART_TICK_STYLE} />
          <YAxis tick={CHART_TICK_STYLE} width={40} />
          <Tooltip contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
          {legendProps && <Legend {...legendProps} />}
          {series.map((s, i) => (
            <Line key={s.label} type="monotone" dataKey={s.label}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={hiddenSeries.has(s.label) ? 0 : 1.5}
              dot={false} activeDot={{ r: 3 }} connectNulls
              hide={hiddenSeries.has(s.label)} opacity={hiddenSeries.has(s.label) ? 0 : 1} />
          ))}
        </LineChart>
      )}
    </ResponsiveContainer>
  );

  const btnBase = "text-[10px] px-1.5 py-0.5 rounded border transition-colors";
  const btnActive = `${btnBase} border-[#0071CE] text-[#0071CE] bg-[#0071CE]/10`;
  const btnIdle   = `${btnBase} border-gray-300 dark:border-gray-600 text-gray-500 hover:text-[#0071CE] hover:border-[#0071CE]`;

  return (
    <>
      <div className="rounded-lg border dark:border-gray-700 p-3">
        {/* Header: title + type switcher + controls */}
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          {title && <div className="text-sm font-semibold truncate flex-1 min-w-0">{title}</div>}
          {/* Chart type switcher */}
          <div className="flex items-center gap-0.5 flex-shrink-0">
            {CHART_TYPE_OPTIONS.map(opt => (
              <button key={opt.key} onClick={() => setActiveType(opt.key)}
                className={activeType === opt.key ? btnActive : btnIdle}>
                {opt.label}
              </button>
            ))}
          </div>
          {/* Reset hidden series */}
          {hiddenSeries.size > 0 && (
            <button onClick={() => setHiddenSeries(new Set())} className={btnIdle} title="Show all series">
              Reset
            </button>
          )}
          {/* Full-screen expand */}
          <button onClick={() => setFullscreen(true)}
            className="p-0.5 rounded text-gray-400 hover:text-[#0071CE] transition-colors"
            title="Full screen">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
            </svg>
          </button>
        </div>
        {series.length > 1 && (
          <div className="text-[10px] text-gray-400 mb-1">Click legend to show/hide series</div>
        )}
        <ChartBody height={220} />
      </div>

      {/* Full-screen overlay */}
      {fullscreen && (
        <div className="fixed inset-0 z-50 bg-black/75 flex flex-col items-center justify-center p-6"
          onClick={() => setFullscreen(false)}>
          <div className="bg-white dark:bg-[#0d1117] rounded-xl shadow-2xl w-full max-w-6xl flex flex-col"
            style={{ maxHeight: "90vh" }} onClick={e => e.stopPropagation()}>
            {/* Fullscreen header */}
            <div className="flex items-center gap-2 px-5 py-3 border-b dark:border-gray-700 flex-shrink-0">
              {title && <div className="text-sm font-semibold flex-1">{title}</div>}
              <div className="flex items-center gap-0.5">
                {CHART_TYPE_OPTIONS.map(opt => (
                  <button key={opt.key} onClick={() => setActiveType(opt.key)}
                    className={activeType === opt.key ? btnActive : btnIdle}>
                    {opt.label}
                  </button>
                ))}
              </div>
              {hiddenSeries.size > 0 && (
                <button onClick={() => setHiddenSeries(new Set())} className={btnIdle}>Reset</button>
              )}
              <button onClick={() => setFullscreen(false)}
                className="ml-2 p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600 transition-colors"
                title="Close">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            {series.length > 1 && (
              <div className="text-[10px] text-gray-400 px-5 pt-2">Click legend to show/hide series</div>
            )}
            {/* Full-screen chart body fills remaining space */}
            <div className="flex-1 p-5 min-h-0">
              <ChartBody height={Math.max(400, typeof window !== "undefined" ? window.innerHeight * 0.65 : 500)} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function TabsComponent({ comp, componentMap }: { comp: A2UIComponent; componentMap: Map<string, A2UIComponent> }) {
  const tabs = comp.tabItems ?? [];
  const [activeTab, setActiveTab] = useState(0);
  if (tabs.length === 0) return null;
  const activeChildId = tabs[activeTab]?.child;
  const activeChild = activeChildId ? componentMap.get(activeChildId) : undefined;
  return (
    <div>
      <div className="flex border-b border-gray-200 dark:border-gray-700 gap-0">
        {tabs.map((tab, i) => (
          <button key={i} onClick={() => setActiveTab(i)} className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${i === activeTab ? "border-[#0071CE] text-[#0071CE]" : "border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"}`}>
            {tab.title}
          </button>
        ))}
      </div>
      <div className="pt-3">
        {activeChild
          ? <RenderComponent comp={activeChild} componentMap={componentMap} />
          : <div className="text-xs text-gray-400 p-2 italic">No content for this tab.</div>
        }
      </div>
    </div>
  );
}

// ─── Utilities ────────────────────────────────────────────────────────────────

const COLORS = ["#0071CE", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"];

// Chart theme — module-level so they're not recreated on every render
const CHART_TICK_STYLE = { fontSize: 10, fill: "#9ca3af" } as const;
const CHART_GRID_STROKE = "#374151";
// Neutral tooltip styling that reads in both light and dark mode
const CHART_TOOLTIP_STYLE = { backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: 6, fontSize: 11 } as const;
const CHART_TOOLTIP_LABEL_STYLE = { color: "#f1f5f9" } as const;

function ExternalLinkIcon() {
  return <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>;
}

function getIconSvg(name: string, size: number): React.ReactNode {
  const s = size;
  const icons: Record<string, React.ReactNode> = {
    check: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>,
    warning: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" /></svg>,
    error: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>,
    info: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>,
    search: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>,
    close: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>,
    settings: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>,
    star: <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" /></svg>,
  };
  return icons[name.toLowerCase()] ?? <span className="text-xs font-mono">{name}</span>;
}

function inlineMarkdown(text: string): string {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/`(.*?)`/g, '<code class="px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-xs">$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-[#0071CE] underline">$1</a>');
}

function formatCell(value: string): string {
  if (value === "—" || value === "null" || value === "undefined" || value === "None") return "—";
  return value;
}
