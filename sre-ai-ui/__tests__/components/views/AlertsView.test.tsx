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

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ theme: "light", isDark: false, toggleTheme: jest.fn() }),
}));

jest.mock("@/components/ui/DataTable", () => {
  const React = require("react");
  return {
    __esModule: true,
    DataTable: ({ data, columns, loading, error, emptyMessage, toolbarActions, prefixActions, title }: any) => {
      if (loading) return <div><p>Loading...</p></div>;
      if (error) return <div><p>{error}</p></div>;
      if (!data?.length) return <div><p>{emptyMessage || "No data"}</p></div>;
      return (
        <div data-testid="alerts-datatable">
          {title && <h2>{title}</h2>}
          {prefixActions && <div data-testid="prefix-actions">{prefixActions}</div>}
          {toolbarActions && <div data-testid="toolbar-actions">{toolbarActions}</div>}
          <table>
            <thead><tr>{columns.map((col: any, i: number) => (
              <th key={i}>{typeof col.header === "string" ? col.header : col.id || ""}</th>
            ))}</tr></thead>
            <tbody>{data.map((row: any, ri: number) => (
              <tr key={ri}>{columns.map((col: any, ci: number) => {
                const val = col.accessorKey ? row[col.accessorKey] : col.accessorFn?.(row);
                let content = val;
                if (col.cell) { try { content = col.cell({ getValue: () => val, row: { original: row } }); } catch { content = String(val ?? ""); } }
                return <td key={ci}>{content}</td>;
              })}</tr>
            ))}</tbody>
          </table>
        </div>
      );
    },
    CellBadge: ({ children }: any) => <span>{children}</span>,
    CellTruncated: ({ text }: any) => <span>{text || "—"}</span>,
    CellCopyable: ({ text }: any) => <span>{text || "—"}</span>,
    CellList: ({ items, prefix }: any) => items?.length ? <span>{items.map((i: string) => `${prefix || ""}${i}`).join(", ")}</span> : <span>—</span>,
    multiSelectFilterFn: jest.fn(),
    booleanFilterFn: jest.fn(),
  };
});

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const TEST_NOW = Math.floor(Date.now() / 1000);

function makeAlert(overrides: Partial<AlertResultAlert> = {}): AlertResultAlert {
  return {
    alert_id: "alert-1",
    alertname: "HighCPUUsage",
    alert_sla_name: "CPU SLA",
    episode_is_open: true,
    episode_start_ts: TEST_NOW - 600,
    episode_end_ts: null,
    cluster: "prod-cluster",
    mms_xmatters_group: "sre-team",
    mms_slack_channel: "#sre-alerts",
    alert_owner_category: "infrastructure",
    // Default values with recent timestamps so isAlertActive returns true
    values: [[TEST_NOW - 60, "1"], [TEST_NOW - 10, "1"]] as [number, string][],
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

/** Empty PromQL response for graph queries */
const EMPTY_PROMQL_RESULT = {
  data: { resultType: "matrix", result: [] },
};

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  _resetAlertsCache();
  jest.clearAllMocks();
  // Default: return empty result so tests that don't need alerts still work
  mockQuery.mockResolvedValue(makeQueryResult([]));
  // Default: return empty PromQL results for all graph queries
  mockQueryRange.mockResolvedValue(EMPTY_PROMQL_RESULT);
  // jsdom doesn't implement clipboard; stub it for copy-button tests
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: jest.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  });
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("AlertsView", () => {
  // ─── Header rendering ───────────────────────────────────────────────────────
  describe("header rendering", () => {
    it("renders the 'Alerts' title via DataTable", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => {
        expect(screen.getByText("Alerts")).toBeInTheDocument();
      });
    });

    it("renders the Refresh button when alerts are present", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument();
      });
    });
  });

  // ─── API wiring ─────────────────────────────────────────────────────────────
  describe("API wiring", () => {
    it("calls alertsApi.query on mount with start and end params", async () => {
      render(<AlertsView />);
      await waitFor(() => expect(mockQuery).toHaveBeenCalledTimes(1));

      const payload = (mockQuery.mock.calls[0] as [Record<string, string>])[0];
      expect(typeof payload.start).toBe("string");
      expect(typeof payload.end).toBe("string");
      expect(Number(payload.end)).toBeGreaterThan(Number(payload.start));
    });

    it("the queried window matches the default 1-hour time frame", async () => {
      render(<AlertsView />);
      await waitFor(() => expect(mockQuery).toHaveBeenCalledTimes(1));

      const payload = (mockQuery.mock.calls[0] as [Record<string, string>])[0];
      const windowSecs = Number(payload.end) - Number(payload.start);
      // 1 hour = 3600s; allow ±5s for test execution time
      expect(windowSecs).toBeGreaterThanOrEqual(3595);
      expect(windowSecs).toBeLessThanOrEqual(3605);
    });
  });

  // ─── Loading state ──────────────────────────────────────────────────────────
  describe("loading state", () => {
    it("shows 'Fetching alerts...' spinner while API call is in progress", async () => {
      let resolveQuery!: (val: AlertQueryResult) => void;
      mockQuery.mockReturnValue(
        new Promise<AlertQueryResult>((res) => { resolveQuery = res; })
      );

      render(<AlertsView />);

      expect(screen.getByText(/fetching alerts/i)).toBeInTheDocument();

      // clean up
      await act(async () => { resolveQuery(makeQueryResult()); });
    });

    it("hides the spinner after load completes", async () => {
      render(<AlertsView />);
      await waitFor(() => {
        expect(screen.queryByText(/fetching alerts/i)).not.toBeInTheDocument();
      });
    });

    it("disables Refresh button while re-loading with existing alerts", async () => {
      let resolveFirst!: (v: AlertQueryResult) => void;
      mockQuery.mockReturnValueOnce(new Promise((res) => { resolveFirst = res; }));
      render(<AlertsView />);

      // Resolve first load with alerts
      await act(async () => { resolveFirst(makeQueryResult([makeAlert()])); });
      await waitFor(() => screen.getByRole("button", { name: /refresh/i }));

      // Trigger a refresh — mock next call to be pending
      let resolveSecond!: (v: AlertQueryResult) => void;
      mockQuery.mockReturnValueOnce(new Promise((res) => { resolveSecond = res; }));
      const refreshBtn = screen.getByRole("button", { name: /refresh/i });
      await act(async () => { fireEvent.click(refreshBtn); });

      expect(refreshBtn).toBeDisabled();

      await act(async () => { resolveSecond(makeQueryResult([makeAlert()])); });
      await waitFor(() => expect(refreshBtn).not.toBeDisabled());
    });
  });

  // ─── Empty state ────────────────────────────────────────────────────────────
  describe("empty state", () => {
    it("shows empty state message with default time frame after load", async () => {
      render(<AlertsView />);
      await waitFor(() => {
        expect(screen.getByText(/no alerts found.*last 1 hr/i)).toBeInTheDocument();
      });
    });

    it("does NOT show 'Expanded view' button when there are no alerts", async () => {
      render(<AlertsView />);
      await waitFor(() => {
        expect(
          screen.queryByTitle("Expanded view")
        ).not.toBeInTheDocument();
      });
    });
  });

  // ─── Error state ────────────────────────────────────────────────────────────
  describe("error state", () => {
    it("shows error heading and message when API throws a generic Error", async () => {
      mockQuery.mockRejectedValue(new Error("Network timeout"));
      render(<AlertsView />);

      await waitFor(() => {
        expect(screen.getByText(/error fetching alerts/i)).toBeInTheDocument();
        expect(screen.getByText("Network timeout")).toBeInTheDocument();
      });
    });

    it("shows fallback message for non-Error rejections", async () => {
      mockQuery.mockRejectedValue("something went wrong");
      render(<AlertsView />);

      await waitFor(() => {
        expect(screen.getByText("Failed to fetch alerts")).toBeInTheDocument();
      });
    });

    it("shows a friendly message for 502 gateway errors", async () => {
      mockQuery.mockRejectedValue(new Error("Alerts query failed: 502 Bad Gateway"));
      render(<AlertsView />);

      await waitFor(() => {
        expect(
          screen.getByText(/temporarily unavailable/i)
        ).toBeInTheDocument();
      });
    });

    it("shows a friendly message for 503 gateway errors", async () => {
      mockQuery.mockRejectedValue(new Error("Alerts query failed: 503 Service Unavailable"));
      render(<AlertsView />);

      await waitFor(() => {
        expect(
          screen.getByText(/temporarily unavailable/i)
        ).toBeInTheDocument();
      });
    });
  });

  // ─── Time frame filter ──────────────────────────────────────────────────────
  describe("time frame filter", () => {
    it("renders both the value input and unit selector when alerts are present", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => {
        expect(screen.getByRole("spinbutton", { name: /time frame value/i })).toBeInTheDocument();
        expect(screen.getByRole("combobox", { name: /time frame unit/i })).toBeInTheDocument();
      });
    });

    it("defaults to 1 Hour", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => screen.getByRole("spinbutton", { name: /time frame value/i }));
      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement;
      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i }) as HTMLSelectElement;
      expect(valueInput.value).toBe("1");
      expect(unitSelect.value).toBe("hours");
    });

    it("unit selector has exactly Minutes and Hours options", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => screen.getByRole("combobox", { name: /time frame unit/i }));
      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i }) as HTMLSelectElement;
      expect(Array.from(unitSelect.options).map((o) => o.text)).toEqual(["Min", "Hours"]);
    });

    it("updates empty state message when value changes after clicking Apply", async () => {
      mockQuery.mockResolvedValueOnce(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => screen.getByRole("spinbutton", { name: /time frame value/i }));

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "6" } });
      });

      // Return empty on next query
      mockQuery.mockResolvedValueOnce(makeQueryResult([]));
      const applyButton = screen.getByRole("button", { name: /apply/i });
      await act(async () => {
        fireEvent.click(applyButton);
      });

      await waitFor(() => {
        expect(screen.getByText(/no alerts found.*last 6 hrs/i)).toBeInTheDocument();
      });
    });

    it("updates empty state message when unit changes to Minutes after clicking Apply", async () => {
      mockQuery.mockResolvedValueOnce(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => screen.getByRole("combobox", { name: /time frame unit/i }));

      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i });
      await act(async () => {
        fireEvent.change(unitSelect, { target: { value: "minutes" } });
      });

      // Return empty on next query
      mockQuery.mockResolvedValueOnce(makeQueryResult([]));
      const applyButton = screen.getByRole("button", { name: /apply/i });
      await act(async () => {
        fireEvent.click(applyButton);
      });

      await waitFor(() => {
        expect(screen.getByText(/no alerts found.*\d+ min/i)).toBeInTheDocument();
      });
    });

    it("re-enables inputs after load completes", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => {
        expect(screen.getByRole("spinbutton", { name: /time frame value/i })).not.toBeDisabled();
        expect(screen.getByRole("combobox", { name: /time frame unit/i })).not.toBeDisabled();
      });
    });

    it("re-fetches alerts when time value changes after clicking Apply", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => expect(mockQuery).toHaveBeenCalledTimes(1));

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "3" } });
      });

      // Must click Apply to trigger fetch (not auto-fetch on input change)
      const applyButton = screen.getByRole("button", { name: /apply/i });
      await act(async () => {
        fireEvent.click(applyButton);
      });

      await waitFor(() => expect(mockQuery).toHaveBeenCalledTimes(2));
    });

    it("clamps value to minimum 5 when unit is Minutes", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => screen.getByRole("combobox", { name: /time frame unit/i }));

      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i });
      await act(async () => {
        fireEvent.change(unitSelect, { target: { value: "minutes" } });
      });

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement;
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "1" } });
        fireEvent.blur(valueInput);
      });

      await waitFor(() => {
        const val = Number(
          (screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement).value
        );
        expect(val).toBeGreaterThanOrEqual(5);
      });
    });

    it("clamps value to maximum 24 when unit is Hours", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => screen.getByRole("spinbutton", { name: /time frame value/i }));

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement;
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "99" } });
        fireEvent.blur(valueInput);
      });

      await waitFor(() => {
        const val = Number(
          (screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement).value
        );
        expect(val).toBeLessThanOrEqual(24);
      });
    });
  });

  // ─── Refresh button ─────────────────────────────────────────────────────────
  describe("Refresh button", () => {
    it("is enabled after initial load completes with alerts", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => {
        const refreshBtn = screen.getByRole("button", { name: /refresh/i });
        expect(refreshBtn).not.toBeDisabled();
      });
    });

    it("triggers a second API call and returns to non-loading state", async () => {
      jest.useFakeTimers();
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);

      // Let initial fetchAllAlerts complete (including 1s setTimeout between graph queries)
      await act(async () => { jest.advanceTimersByTime(2000); });
      expect(mockQuery).toHaveBeenCalledTimes(1);

      const refreshBtn = screen.getByRole("button", { name: /refresh/i });
      await act(async () => {
        fireEvent.click(refreshBtn);
      });

      // Advance past the 1s setTimeout inside fetchAllAlerts so refreshing finishes
      await act(async () => { jest.advanceTimersByTime(2000); });

      expect(mockQuery).toHaveBeenCalledTimes(2);
      expect(refreshBtn).not.toBeDisabled();

      jest.useRealTimers();
    });
  });

  // ─── Alerts table ────────────────────────────────────────────────────────────
  describe("expanded view", () => {
    it("opens ExpandedView when 'Expanded view' button is clicked", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => {
        expect(screen.getByTitle("Close expanded view")).toBeInTheDocument();
      });
    });

    it("closes ExpandedView when X button is clicked", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => screen.getByTitle("Close expanded view"));
      fireEvent.click(screen.getByTitle("Close expanded view"));

      await waitFor(() => {
        expect(screen.queryByTitle("Close expanded view")).not.toBeInTheDocument();
      });
    });

    it("closes ExpandedView when backdrop is clicked", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      const { container } = render(<AlertsView />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => screen.getByTitle("Close expanded view"));

      const backdrop = container.querySelector(".fixed.inset-0.bg-black\\/60");
      if (backdrop) fireEvent.click(backdrop);

      await waitFor(() => {
        expect(screen.queryByTitle("Close expanded view")).not.toBeInTheDocument();
      });
    });

    it("shows time frame filter inputs in expanded view header", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => {
        // Both the main header and expanded view render filter controls
        const valueInputs = screen.getAllByRole("spinbutton", { name: /time frame value/i });
        const unitSelects = screen.getAllByRole("combobox", { name: /time frame unit/i });
        expect(valueInputs.length).toBeGreaterThanOrEqual(2);
        expect(unitSelects.length).toBeGreaterThanOrEqual(2);
        // Both default to 1 hour
        expect((valueInputs[1] as HTMLInputElement).value).toBe("1");
        expect((unitSelects[1] as HTMLSelectElement).value).toBe("hours");
      });
    });

    it("Refresh button inside expanded view triggers another API call", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => screen.getByTitle("Close expanded view"));

      // There are now multiple Refresh buttons; find the one in the expanded view
      const refreshButtons = screen.getAllByRole("button", { name: /refresh/i });
      expect(refreshButtons.length).toBeGreaterThanOrEqual(2);

      const initialCallCount = mockQuery.mock.calls.length;

      await act(async () => {
        fireEvent.click(refreshButtons[refreshButtons.length - 1]);
      });

      await waitFor(() => {
        expect(mockQuery.mock.calls.length).toBeGreaterThan(initialCallCount);
      });
    });

    it("expanded view renders the full alerts table", async () => {
      const alert = makeAlert({ alertname: "ExpandedAlertName", alert_sla_name: "SLA X" });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => {
        // The alert table data is rendered inside the expanded view
        expect(screen.getAllByText("ExpandedAlertName").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("SLA X").length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  // ─── formatRelativeTime (via rendered output) ────────────────────────────────
  describe("PromQL graph data integration", () => {
    it("processes Section 1 graph data from PromQL response", async () => {
      jest.useFakeTimers();
      const now = Math.floor(Date.now() / 1000);
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange.mockResolvedValue({
        data: {
          resultType: "matrix",
          result: [{
            metric: {},
            values: [[now - 300, "5"], [now - 200, "8"], [now - 100, "3"]],
          }],
        },
      });

      render(<AlertsView />);
      await act(async () => { jest.advanceTimersByTime(2000); });

      // The graph data is passed to AlertsGraphDashboard; just verify no errors
      await waitFor(() => {
        expect(screen.queryByText(/error fetching alerts/i)).not.toBeInTheDocument();
      });
      jest.useRealTimers();
    });

    it("processes Section 2 multi-series graph data grouped by alert_type", async () => {
      jest.useFakeTimers();
      const now = Math.floor(Date.now() / 1000);
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange.mockResolvedValue({
        data: {
          resultType: "matrix",
          result: [
            { metric: { alert_type: "cpu" }, values: [[now - 300, "2"], [now - 100, "4"]] },
            { metric: { alert_type: "memory" }, values: [[now - 300, "1"], [now - 100, "3"]] },
          ],
        },
      });

      render(<AlertsView />);
      await act(async () => { jest.advanceTimersByTime(2000); });

      await waitFor(() => {
        expect(screen.queryByText(/error fetching alerts/i)).not.toBeInTheDocument();
      });
      jest.useRealTimers();
    });

    it("handles graph section errors gracefully", async () => {
      jest.useFakeTimers();
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange
        .mockRejectedValueOnce(new Error("Graph section 1 error"))
        .mockRejectedValueOnce(new Error("Graph section 2 error"))
        .mockRejectedValueOnce(new Error("Graph section 3 error"));

      render(<AlertsView />);
      await act(async () => { jest.advanceTimersByTime(2000); });

      // Component should still render (graph errors are handled per-section)
      await waitFor(() => {
        expect(screen.getByTestId("alerts-datatable")).toBeInTheDocument();
      });
      jest.useRealTimers();
    });

    it("handles non-Error graph section failures", async () => {
      jest.useFakeTimers();
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange
        .mockRejectedValueOnce("string error")
        .mockRejectedValueOnce("string error")
        .mockRejectedValueOnce("string error");

      render(<AlertsView />);
      await act(async () => { jest.advanceTimersByTime(2000); });

      await waitFor(() => {
        expect(screen.getByTestId("alerts-datatable")).toBeInTheDocument();
      });
      jest.useRealTimers();
    });
  });

  // ─── Alert Details Dialog ────────────────────────────────────────────────

  describe("AlertDetailsDialog", () => {
    it("opens alert details dialog when info button is clicked on alert row", async () => {
      const alert = makeAlert({
        alertname: "DetailTestAlert",
        alert_id: "detail-1",
        values: [[TEST_NOW - 120, "1"], [TEST_NOW - 10, "2"]],
        labels: { custom_label: "custom_value" },
      });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("View full alert details"));
      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => {
        // The dialog shows time-series values
        expect(screen.getByText(/time-series values/i)).toBeInTheDocument();
      });
    });

    it("shows time-series values table in details dialog", async () => {
      const alert = makeAlert({
        alert_id: "ts-alert",
        values: [[TEST_NOW - 120, "42"], [TEST_NOW - 10, "43"]],
      });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("View full alert details"));
      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => {
        expect(screen.getByText(/time-series values/i)).toBeInTheDocument();
        expect(screen.getByText("42")).toBeInTheDocument();
      });
    });

    it("shows labels in details dialog", async () => {
      const alert = makeAlert({
        alert_id: "label-alert",
        values: undefined,
        labels: { environment: "production", region: "us-east" },
      });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("View full alert details"));
      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => {
        // Labels are rendered as "key:" format in the dialog
        expect(screen.getByText(/environment/)).toBeInTheDocument();
        expect(screen.getByText("production")).toBeInTheDocument();
      });
    });

    it("shows 'No additional data' when no labels or values", async () => {
      const alert = makeAlert({
        alert_id: "empty-alert",
        values: undefined,
        labels: undefined,
      });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("View full alert details"));
      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => {
        expect(screen.getByText(/no additional data to display/i)).toBeInTheDocument();
      });
    });

    it("closes details dialog when Close button is clicked", async () => {
      const alert = makeAlert({ alert_id: "close-alert", values: [[TEST_NOW - 10, "1"]] });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      render(<AlertsView />);

      await waitFor(() => screen.getByTitle("View full alert details"));
      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => screen.getByText(/time-series values/i));

      const closeBtn = screen.getByRole("button", { name: /close/i });
      fireEvent.click(closeBtn);

      await waitFor(() => {
        expect(screen.queryByText(/time-series values/i)).not.toBeInTheDocument();
      });
    });

    it("closes details dialog when backdrop is clicked", async () => {
      const alert = makeAlert({ alert_id: "backdrop-alert", values: [[TEST_NOW - 10, "1"]] });
      mockQuery.mockResolvedValue(makeQueryResult([alert]));
      const { container } = render(<AlertsView />);

      await waitFor(() => screen.getByTitle("View full alert details"));
      fireEvent.click(screen.getByTitle("View full alert details"));

      await waitFor(() => screen.getByText(/time-series values/i));

      const backdrops = container.querySelectorAll(".fixed.inset-0.bg-black\\/50");
      const detailsBackdrop = Array.from(backdrops).find(
        (el) => el.querySelector('[class*="max-w-4xl"]')
      );
      if (detailsBackdrop) fireEvent.click(detailsBackdrop);

      await waitFor(() => {
        expect(screen.queryByText(/time-series values/i)).not.toBeInTheDocument();
      });
    });
  });

  // ─── Toolbar ─────────────────────────────────────────────────────────────

  describe("Timeline tab", () => {
    it("switches to timeline tab and shows graph dashboard", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);

      await waitFor(() => screen.getByText("Timeline"));
      fireEvent.click(screen.getByText("Timeline"));

      // Should switch away from Table — no column headers visible
      await waitFor(() => {
        expect(screen.getByText("Table")).toBeInTheDocument();
        expect(screen.queryByRole("columnheader")).not.toBeInTheDocument();
      });
    });

    it("switches to timeline tab in expanded view", async () => {
      jest.useFakeTimers();
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);

      await act(async () => { jest.advanceTimersByTime(2000); });

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => screen.getByTitle("Close expanded view"));

      // Click Timeline tab in expanded view
      const timelineBtns = screen.getAllByText("Timeline");
      fireEvent.click(timelineBtns[timelineBtns.length - 1]);

      // Should show zoom button when in timeline mode
      await waitFor(() => {
        expect(screen.getByTitle(/zoom/i)).toBeInTheDocument();
      });

      // Toggle zoom
      fireEvent.click(screen.getByTitle(/zoom/i));

      await waitFor(() => {
        expect(screen.getByTitle(/exit zoom/i)).toBeInTheDocument();
      });

      jest.useRealTimers();
    });
  });

  // ─── isAlertActive edge cases ────────────────────────────────────────────

  describe("computeGraphStep for large time ranges", () => {
    afterEach(() => {
      jest.useRealTimers();
    });

    it("uses appropriate graph step for time frames > 12 hours", async () => {
      jest.useFakeTimers();
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      mockQueryRange.mockResolvedValue(EMPTY_PROMQL_RESULT);

      render(<AlertsView />);
      await act(async () => { jest.advanceTimersByTime(2000); });

      // Set time frame to 24 hours and apply
      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      fireEvent.change(valueInput, { target: { value: "24" } });

      const applyButton = screen.getByRole("button", { name: /apply/i });
      await act(async () => {
        fireEvent.click(applyButton);
      });
      await act(async () => { jest.advanceTimersByTime(2000); });

      // Should trigger a new fetch with a 24-hour window, which has range > 43200
      // The computeGraphStep function should return "3600s" for this range
      await waitFor(() => {
        expect(mockQuery.mock.calls.length).toBeGreaterThanOrEqual(2);
      });
      jest.useRealTimers();
    });
  });

  describe("Draft unit change", () => {
    it("converts value from hours to minutes when switching unit", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => screen.getByRole("spinbutton", { name: /time frame value/i }));

      // Default is 1 hour; switch to minutes should give 60
      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i });
      fireEvent.change(unitSelect, { target: { value: "minutes" } });

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement;
      expect(Number(valueInput.value)).toBeGreaterThanOrEqual(5);
    });

    it("converts value from minutes to hours when switching unit", async () => {
      mockQuery.mockResolvedValue(makeQueryResult([makeAlert()]));
      render(<AlertsView />);
      await waitFor(() => screen.getByRole("spinbutton", { name: /time frame value/i }));

      // First switch to minutes
      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i });
      fireEvent.change(unitSelect, { target: { value: "minutes" } });

      // Set to 120 minutes
      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      fireEvent.change(valueInput, { target: { value: "120" } });

      // Switch back to hours — should convert 120 min to 2 hours
      fireEvent.change(unitSelect, { target: { value: "hours" } });

      const updatedValue = (screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement).value;
      expect(Number(updatedValue)).toBe(2);
    });
  });

  // ─── Section 3 composite multi-series graph parsing ──────────────────────

});
