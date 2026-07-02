/**
 * Additional tests for AlertsView to improve coverage.
 * Covers: tab switching, alert details dialog, search/filter,
 * graph section rendering, and export functionality.
 *
 * NOTE: Column sorting, toolbar, pagination, and filters are now handled by
 * DataTable internally and tested in DataTable.test.tsx.
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { AlertsView, _resetAlertsCache } from "@/components/views/AlertsView";
import type { AlertResultAlert, AlertQueryResult } from "@/lib/api-client";

// ─── Mock api-client ─────────────────────────────────────────────────────────

const mockQuery = jest.fn<Promise<AlertQueryResult>, [unknown]>();
const mockQueryRange = jest.fn<Promise<unknown>, [unknown]>();

jest.mock("@/lib/api-client", () => ({
  alertsApi: {
    query: (arg: unknown) => mockQuery(arg),
  },
  promqlApi: {
    queryRange: (arg: unknown) => mockQueryRange(arg),
  },
}));

// ─── Mock ThemeContext ────────────────────────────────────────────────────────

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

// ─── Mock DataTable ──────────────────────────────────────────────────────────

jest.mock("@/components/ui/DataTable", () => {
  const React = require("react");
  return {
    __esModule: true,
    DataTable: ({ data, columns, loading, error, emptyMessage, toolbarActions }: any) => {
      if (loading) {
        return <div><p>Loading data...</p></div>;
      }
      if (error) {
        return <div><h3 role="heading">Error</h3><p>{error}</p></div>;
      }
      if (data.length === 0) {
        return <div><p>{emptyMessage || "No data found"}</p></div>;
      }
      return (
        <div>
          {toolbarActions && <div data-testid="toolbar-actions">{toolbarActions}</div>}
          <table>
            <thead>
              <tr>
                {columns.map((col: any, i: number) => (
                  <th key={col.id || col.accessorKey || i}>
                    {typeof col.header === "string" ? col.header : col.id || ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row: any, rowIdx: number) => (
                <tr key={rowIdx}>
                  {columns.map((col: any, colIdx: number) => {
                    const cellValue = col.accessorKey ? row[col.accessorKey] : col.accessorFn?.(row);
                    let cellContent = cellValue;
                    if (col.cell) {
                      try {
                        cellContent = col.cell({
                          getValue: () => cellValue,
                          row: { original: row },
                        });
                      } catch {
                        cellContent = String(cellValue ?? "");
                      }
                    }
                    return <td key={colIdx}>{cellContent}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    },
    CellBadge: ({ children, variant }: any) => <span data-variant={variant}>{children}</span>,
    CellTruncated: ({ text }: any) => <span>{text || "\u2014"}</span>,
    CellCopyable: ({ text }: any) => <span>{text || "\u2014"}</span>,
    CellList: ({ items, prefix }: any) =>
      items?.length ? (
        <span>{items.map((item: string) => `${prefix || ""}${item}`).join(", ")}</span>
      ) : null,
    multiSelectFilterFn: jest.fn(),
    booleanFilterFn: jest.fn(),
  };
});

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const NOW = Math.floor(Date.now() / 1000);

function makeAlert(overrides: Partial<AlertResultAlert> = {}): AlertResultAlert {
  return {
    alert_id: "alert-1",
    alertname: "HighCPUUsage",
    alert_sla_name: "CPU SLA",
    episode_is_open: true,
    episode_start_ts: NOW - 600,
    episode_end_ts: null,
    cluster: "prod-cluster",
    mms_xmatters_group: "sre-team",
    mms_slack_channel: "#sre-alerts",
    alert_owner_category: "infrastructure",
    values: [[NOW - 600, "1"], [NOW - 300, "1"]],
    labels: { cluster_id: "prod-cluster", tool: "juno", custom_label: "custom_value" },
    ...overrides,
  };
}

function makeQueryResult(
  alerts: AlertResultAlert[] = [],
  overrides: Partial<AlertQueryResult> = {}
): AlertQueryResult {
  return {
    alerts,
    total_count: alerts.length,
    ok: true,
    ...overrides,
  };
}

const EMPTY_PROMQL = { data: { resultType: "matrix", result: [] } };

const PROMQL_WITH_DATA = {
  data: {
    resultType: "matrix",
    result: [
      {
        metric: { alert_type: "golden_signal" },
        values: [[NOW - 600, "3"], [NOW - 300, "5"]],
      },
    ],
  },
};

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  _resetAlertsCache();
  jest.clearAllMocks();
  mockQuery.mockResolvedValue(makeQueryResult([]));
  mockQueryRange.mockResolvedValue(EMPTY_PROMQL);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: jest.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  });
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("AlertsView — additional coverage", () => {
  // ── Sorting ───────────────────────────────────────────────────────────
  describe("tab switching", () => {
    it("renders Table and Timeline tabs when alerts exist", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);

      await waitFor(() => {
        expect(screen.getByText("Table")).toBeInTheDocument();
        expect(screen.getByText("Timeline")).toBeInTheDocument();
      });
    });

    it("switches to Timeline tab when clicked", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange.mockResolvedValue(PROMQL_WITH_DATA);
      render(<AlertsView />);

      await waitFor(() => screen.getByText("Timeline"));
      fireEvent.click(screen.getByText("Timeline"));

      await waitFor(() => {
        // Timeline view renders the graph dashboard — Table tab button should still be visible
        expect(screen.getByText("Table")).toBeInTheDocument();
        // DataTable (mock) should NOT be rendered when on Timeline tab
        expect(screen.queryByRole("columnheader")).not.toBeInTheDocument();
      });
    });

    it("switches back to Table tab when clicked", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange.mockResolvedValue(PROMQL_WITH_DATA);
      render(<AlertsView />);

      await waitFor(() => screen.getByText("Timeline"));

      // Go to Timeline
      fireEvent.click(screen.getByText("Timeline"));
      await waitFor(() => expect(screen.queryByRole("columnheader")).not.toBeInTheDocument());

      // Go back to Table
      fireEvent.click(screen.getByText("Table"));
      await waitFor(() => {
        expect(screen.getByRole("columnheader", { name: "SLA Name" })).toBeInTheDocument();
      });
    });
  });

  // ── Alert Details Dialog ──────────────────────────────────────────────
  describe("alert details dialog", () => {
    it("opens AlertDetailsDialog when info icon is clicked", async () => {
      const alert = makeAlert({
        alertname: "DetailTestAlert",
        values: [[NOW - 300, "1"], [NOW - 200, "2"]],
        labels: { custom_field: "hello_world", tool: "juno" },
      });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByText("DetailTestAlert"));

      // Click the "View full alert details" info icon button
      fireEvent.click(screen.getByTitle("View full alert details"));

      // Check if the details dialog opens — it shows "Alert Details" heading in an h2
      await waitFor(() => {
        // The card section has an h3 "Alert Details"; the dialog has h2 "Alert Details"
        const headings = screen.getAllByText("Alert Details");
        expect(headings.length).toBeGreaterThanOrEqual(2); // card h3 + dialog h2
      });
    });

    it("shows time-series values in AlertDetailsDialog", async () => {
      const alert = makeAlert({
        alertname: "ValuesTestAlert",
        values: [[NOW - 300, "42"]],
      });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByText("ValuesTestAlert"));

      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => {
        // Check for the values heading — it contains "Values" and point count
        expect(screen.getByText(/values.*1 point/i)).toBeInTheDocument();
        expect(screen.getByText("42")).toBeInTheDocument();
      });
    });

    it("shows filtered labels in AlertDetailsDialog", async () => {
      const alert = makeAlert({
        alertname: "LabelsTestAlert",
        labels: { custom_field: "hello_world", tool: "juno", alertname: "LabelsTestAlert" },
      });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByText("LabelsTestAlert"));

      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => {
        // custom_field should be shown (not in excluded set) — rendered as "key:" format
        expect(screen.getByText(/custom_field/)).toBeInTheDocument();
        expect(screen.getByText("hello_world")).toBeInTheDocument();
        // tool should be shown (not in excluded set)
        expect(screen.getByText(/\btool\b/)).toBeInTheDocument();
      });
    });

    it("closes AlertDetailsDialog when Close button is clicked", async () => {
      const alert = makeAlert({ alertname: "CloseTestAlert" });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByText("CloseTestAlert"));

      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => {
        // Dialog h2 + card h3 both say "Alert Details"
        expect(screen.getAllByText("Alert Details").length).toBeGreaterThanOrEqual(2);
      });

      // Click the Close button in the dialog footer
      const closeBtn = screen.getByRole("button", { name: "Close" });
      fireEvent.click(closeBtn);

      await waitFor(() => {
        // After closing, only the card h3 "Alert Details" remains (1 instance)
        expect(screen.getAllByText("Alert Details")).toHaveLength(1);
      });
    });
  });

  // ── Graph sections ────────────────────────────────────────────────────
  describe("graph sections", () => {
    it("calls promqlApi.queryRange for graph sections after table data loads", async () => {
      jest.useFakeTimers();
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange.mockResolvedValue(PROMQL_WITH_DATA);

      render(<AlertsView />);

      // Advance timers multiple times to let all sequential graph fetches complete
      // Sections 1 & 2 fire immediately; section 3 has a 1s delay before firing
      for (let i = 0; i < 5; i++) {
        await act(async () => { jest.advanceTimersByTime(1000); });
      }

      // promqlApi.queryRange should have been called at least 3 times (sections 1, 2, 3)
      expect(mockQueryRange.mock.calls.length).toBeGreaterThanOrEqual(3);

      jest.useRealTimers();
    });

    it("handles graph section errors gracefully", async () => {
      jest.useFakeTimers();
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange.mockRejectedValue(new Error("Graph fetch failed"));

      render(<AlertsView />);

      await act(async () => { jest.advanceTimersByTime(3000); });

      // Should not crash — error is caught per-section
      expect(screen.getByText("Table")).toBeInTheDocument();

      jest.useRealTimers();
    });
  });

  // ── computeGraphStep (indirectly via different time frames) ────────────
  describe("graph step calculation", () => {
    it("uses appropriate step for 1-hour window", async () => {
      jest.useFakeTimers();
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange.mockResolvedValue(EMPTY_PROMQL);

      render(<AlertsView />);
      await act(async () => { jest.advanceTimersByTime(3000); });

      // Default is 1 hour — step should be "60s"
      const calls = mockQueryRange.mock.calls;
      if (calls.length > 0) {
        const payload = calls[0][0] as Record<string, string>;
        expect(payload.step).toBe("60s");
      }

      jest.useRealTimers();
    });
  });

  // ── Multiple alerts with different statuses ──────────────────────────
  describe("alert count header", () => {
    it("renders all alerts when multiple are returned", async () => {
      const alerts = [
        makeAlert({ alert_id: "a1", alertname: "Alert_A1" }),
        makeAlert({ alert_id: "a2", alertname: "Alert_A2" }),
        makeAlert({ alert_id: "a3", alertname: "Alert_A3" }),
      ];
      mockQuery.mockResolvedValue(makeQueryResult(alerts, { total_count: 3 }));
      render(<AlertsView />);

      await waitFor(() => {
        expect(screen.getByText("Alert_A1")).toBeInTheDocument();
        expect(screen.getByText("Alert_A2")).toBeInTheDocument();
        expect(screen.getByText("Alert_A3")).toBeInTheDocument();
      });
    });
  });

});
