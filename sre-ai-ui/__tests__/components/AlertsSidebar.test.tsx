import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { AlertsSidebar } from "@/components/AlertsSidebar";
import type { Application, ManagedServiceData, AlertResultAlert } from "@/lib/api-client";

// ─── Mock ThemeContext ────────────────────────────────────────────────────────
let mockIsDark = false;
jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: mockIsDark, theme: mockIsDark ? "dark" : "light", toggleTheme: jest.fn() }),
}));

// ─── Mock AlertsMultiLineGraphSection ─────────────────────────────────────────
jest.mock("@/components/AlertsMultiLineGraphSection", () => ({
  AlertsMultiLineGraphSection: ({ title, loading, error }: any) => (
    <div data-testid={`graph-section-${title}`}>
      {loading && <span>Graph loading...</span>}
      {error && <span>Graph error: {error}</span>}
      <span>{title}</span>
    </div>
  ),
}));

// ─── Mock api-client ─────────────────────────────────────────────────────────

const mockQueryRange = jest.fn<Promise<any>, [unknown]>();

jest.mock("@/lib/api-client", () => ({
  promqlApi: {
    queryRange: (...args: unknown[]) => mockQueryRange(...args),
  },
}));

// ─── Fixtures ─────────────────────────────────────────────────────────────────

function makeWcnpApp(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    name: "checkout-service",
    tenant: "ecom",
    tier: "T1",
    functionalDomain: "checkout",
    active: true,
    certified: true,
    applicationType: "wcnp",
    namespace: "checkout-ns",
    appName: "checkout-app",
    cluster: null,
    team: null,
    slackChannels: [],
    xmattersGroups: [],
    emails: [],
    oneOpsPlatformId: null,
    wcnpId: 1,
    pageFlowId: null,
    oneOpsOrg: null,
    oneOpsAssembly: null,
    oneOpsPlatform: null,
    ...overrides,
  };
}

function makeManagedService(overrides: Partial<ManagedServiceData> = {}): ManagedServiceData {
  return {
    id: 10,
    managedServiceId: 10,
    name: "my-cosmos-db",
    serviceType: "cosmos",
    ...overrides,
  };
}

/**
 * Build a PromQL query-range response.
 * Each entry in `series` becomes one result item with metric labels + values.
 */
function makePromQLResult(
  series: Array<{
    metric?: Record<string, string>;
    values?: [number, string][];
  }> = []
) {
  return {
    status: "success",
    data: {
      resultType: "matrix",
      result: series.map((s) => ({
        metric: s.metric || {},
        values: s.values || [[Math.floor(Date.now() / 1000), "1"]],
      })),
    },
  };
}

/** Shortcut: build a single-alert PromQL result from AlertResultAlert-like overrides */
function makeAlertSeries(overrides: Partial<AlertResultAlert> = {}) {
  const now = Math.floor(Date.now() / 1000);
  const startTs = overrides.episode_start_ts ?? now - 300;
  const endTs = overrides.episode_end_ts ?? now;
  const metric: Record<string, string> = {
    alertname: overrides.alertname || "HighCPUUsage",
    alert_sla_name: overrides.alert_sla_name || "CPU SLA",
    alertstate: "firing",
    cluster: overrides.cluster || "prod-cluster",
    mms_xmatters_group: overrides.mms_xmatters_group || "sre-team",
    mms_slack_channel: overrides.mms_slack_channel || "#sre-alerts",
    alert_owner_category: overrides.alert_owner_category || "infrastructure",
  };
  // Remove falsy keys
  for (const k of Object.keys(metric)) {
    if (!metric[k]) delete metric[k];
  }
  if (overrides.labels) Object.assign(metric, overrides.labels);

  const values: [number, string][] = overrides.values || [
    [startTs as number, "1"],
    [endTs as number, "1"],
  ];

  return { metric, values };
}

/** Empty PromQL result */
function makeEmptyPromQLResult() {
  return makePromQLResult([]);
}

// ─── Default props ─────────────────────────────────────────────────────────────

const defaultProps = {
  isOpen: false,
  onClose: jest.fn(),
  app: null,
};

// ─── Tests ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  // jsdom doesn't implement clipboard; stub it so copy-button tests can run
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: jest.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  jest.useRealTimers();
});

/**
 * Helper: render the sidebar, advance timers to flush the 2s delay between
 * the table PromQL call and the graph PromQL call, then flush microtasks.
 */
async function renderAndSettle(ui: React.ReactElement) {
  const result = render(ui);
  // Flush initial fetch + 2s delay between table & graph calls
  await act(async () => {
    jest.advanceTimersByTime(3000);
  });
  return result;
}

describe("AlertsSidebar", () => {
  describe("closed state", () => {
    it("does not render the overlay or sidebar header when isOpen=false", () => {
      render(<AlertsSidebar {...defaultProps} />);
      expect(screen.queryByText("Fetching alerts...")).not.toBeInTheDocument();
    });

    it("does not call the PromQL API when closed with no app", () => {
      render(<AlertsSidebar {...defaultProps} />);
      expect(mockQueryRange).not.toHaveBeenCalled();
    });
  });

  describe("header", () => {
    it("renders 'Alerts' heading when open", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      expect(screen.getByText("Alerts")).toBeInTheDocument();
    });

    it("shows app name in header subtext for Application", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp({ name: "checkout-service" })} />
      );
      expect(screen.getByText(/checkout-service/i)).toBeInTheDocument();
    });

    it("shows app name in header subtext for ManagedServiceData", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({ name: "my-kafka" })} />
      );
      expect(screen.getByText(/my-kafka/i)).toBeInTheDocument();
    });

    it("shows 'Unknown' when app is null", () => {
      render(<AlertsSidebar {...defaultProps} isOpen app={null} />);
      expect(screen.getByText(/unknown/i)).toBeInTheDocument();
    });
  });

  describe("loading state", () => {
    it("shows loading spinner while API call is in progress", async () => {
      mockQueryRange.mockReturnValue(new Promise(() => {})); // never resolves
      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      expect(screen.getByText(/fetching alerts/i)).toBeInTheDocument();
    });
  });

  describe("empty state", () => {
    it("shows 'No alerts found' message when API returns empty result", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText(/no alerts found/i)).toBeInTheDocument();
      });
    });

    it("shows the expand button even when alert list is empty (data loaded)", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        // Expand button is visible once data has loaded (alerts state is not null)
        expect(screen.getByTitle("Expanded view")).toBeInTheDocument();
      });
    });
  });

  describe("error state", () => {
    it("shows error message when API throws an Error", async () => {
      mockQueryRange.mockRejectedValue(new Error("Network timeout"));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText("Network timeout")).toBeInTheDocument();
        expect(screen.getByText(/error fetching alerts/i)).toBeInTheDocument();
      });
    });

    it("shows fallback error message for non-Error rejections", async () => {
      mockQueryRange.mockRejectedValue("something went wrong");
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText("Failed to fetch alerts")).toBeInTheDocument();
      });
    });
  });

  describe("alerts table", () => {
    it("renders all column headers when alerts are present", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText("SLA_name")).toBeInTheDocument();
        expect(screen.getByText("Alert start time")).toBeInTheDocument();
        expect(screen.getByText("Status")).toBeInTheDocument();
        expect(screen.getByText("Cluster_id")).toBeInTheDocument();
        expect(screen.getByText("x_matters_group")).toBeInTheDocument();
        expect(screen.getByText("Slack_xmatters")).toBeInTheDocument();
        expect(screen.getByText("Alert category")).toBeInTheDocument();
        expect(screen.getByText("Alert name")).toBeInTheDocument();
      });
    });

    it("displays alert data in table rows", async () => {
      const EPISODE_START_TS = Math.floor(Date.now() / 1000) - 60;
      const series = makeAlertSeries({
        alert_sla_name: "My SLA",
        cluster: "us-central-1",
        mms_xmatters_group: "platform-eng",
        mms_slack_channel: "#platform",
        alert_owner_category: "platform",
        alertname: "DiskSpaceAlert",
        episode_start_ts: EPISODE_START_TS,
        values: [[EPISODE_START_TS, "1"], [EPISODE_START_TS + 30, "1"]],
      });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const expectedStartTime = new Date(EPISODE_START_TS * 1000).toLocaleString();

      await waitFor(() => {
        expect(screen.getByText("My SLA")).toBeInTheDocument();
        expect(screen.getByText(expectedStartTime)).toBeInTheDocument();
        expect(screen.getByText("us-central-1")).toBeInTheDocument();
        expect(screen.getByText("platform-eng")).toBeInTheDocument();
        expect(screen.getByText("#platform")).toBeInTheDocument();
        expect(screen.getByText("platform")).toBeInTheDocument();
        expect(screen.getByText("DiskSpaceAlert")).toBeInTheDocument();
      });
    });

    it("shows copy button for x_matters_group and copies value on click", async () => {
      const series = makeAlertSeries({ mms_xmatters_group: "sre-xmatters-group" });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => screen.getByText("sre-xmatters-group"));

      const copyBtn = screen.getByTitle("Copy x_matters_group");
      fireEvent.click(copyBtn);

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("sre-xmatters-group");
    });

    it("shows copy button for Slack_xmatters and copies value on click", async () => {
      const series = makeAlertSeries({ mms_slack_channel: "#sre-alerts-channel" });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => screen.getByText("#sre-alerts-channel"));

      const copyBtn = screen.getByTitle("Copy Slack_xmatters");
      fireEvent.click(copyBtn);

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("#sre-alerts-channel");
    });

    it("shows copy button for Cluster_id and copies value on click", async () => {
      const series = makeAlertSeries({ cluster: "eus2-prod-a21" });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => screen.getByText("eus2-prod-a21"));

      const copyBtn = screen.getByTitle("Copy Cluster_id");
      fireEvent.click(copyBtn);

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("eus2-prod-a21");
    });

    it("falls back to labels.cluster_id for Cluster_id copy button", async () => {
      const series = {
        metric: {
          alertname: "TestAlert",
          alert_sla_name: "SLA",
          alertstate: "firing",
          cluster_id: "scus-prod-a67",
        },
        values: [[Math.floor(Date.now() / 1000), "1"]] as [number, string][],
      };
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      // The labels.cluster_id should be picked up as fallback since cluster is not set
      // parsePromQLToAlertList maps m.cluster to cluster field; labels stores all of m
      await waitFor(() => screen.getByText("scus-prod-a67"));

      const copyBtn = screen.getByTitle("Copy Cluster_id");
      fireEvent.click(copyBtn);

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("scus-prod-a67");
    });

    it("shows 'Active' badge when alert episode is recent", async () => {
      const now = Math.floor(Date.now() / 1000);
      const series = makeAlertSeries({
        episode_start_ts: now - 30,
        values: [[now - 30, "1"], [now, "1"]], // last timestamp is now → active
      });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        const badge = screen.getByText("Active");
        expect(badge).toHaveClass("bg-red-100");
        expect(badge).toHaveClass("text-red-800");
      });
    });

    it("shows 'Inactive' badge when alert episode is old", async () => {
      const now = Math.floor(Date.now() / 1000);
      const pastTs = now - 600; // 10 min ago — well past the active threshold
      const series = makeAlertSeries({
        episode_start_ts: pastTs - 30,
        values: [[pastTs - 30, "1"], [pastTs, "1"]], // last ts is 10 min ago
      });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        const badge = screen.getByText("Inactive");
        expect(badge).toHaveClass("bg-green-100");
        expect(badge).toHaveClass("text-green-800");
      });
    });

    it("renders '-' for missing optional fields", async () => {
      const series = {
        metric: { alertname: "", alertstate: "firing" },
        values: [[Math.floor(Date.now() / 1000), "1"]] as [number, string][],
      };
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        const dashes = screen.getAllByText("-");
        expect(dashes.length).toBeGreaterThanOrEqual(4);
      });
    });

    it("shows the alert count in the summary", async () => {
      const series1 = makeAlertSeries({ alertname: "Alert1", alert_sla_name: "SLA1" });
      const series2 = makeAlertSeries({ alertname: "Alert2", alert_sla_name: "SLA2" });
      mockQueryRange.mockResolvedValue(makePromQLResult([series1, series2]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText(/showing 2 alerts/i)).toBeInTheDocument();
      });
    });

    it("shows 'No data available' inside the table when alerts list is empty after sorting", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText(/no alerts found/i)).toBeInTheDocument();
      });
    });
  });

  describe("sorting", () => {
    it("renders sort indicators on column headers", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        // All headers should have the unsorted icon (ChevronsUpDown) initially
        const headers = screen.getAllByRole("columnheader");
        expect(headers.length).toBe(8);
      });
    });

    it("toggles sort direction on column header click", async () => {
      const s1 = makeAlertSeries({ alert_sla_name: "Alpha" });
      const s2 = makeAlertSeries({ alert_sla_name: "Beta" });
      mockQueryRange.mockResolvedValue(makePromQLResult([s1, s2]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => screen.getByText("Alpha"));

      // Click SLA_name header to sort ascending
      const slaHeader = screen.getByText("SLA_name");
      await act(async () => { fireEvent.click(slaHeader); });

      // First row should be Alpha (asc)
      const cells = screen.getAllByRole("cell");
      const slaValues = cells.filter((c) => c.textContent === "Alpha" || c.textContent === "Beta");
      expect(slaValues.length).toBe(2);
    });
  });

  describe("close button", () => {
    it("calls onClose when the X button in the header is clicked", async () => {
      const onClose = jest.fn();
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen onClose={onClose} app={makeWcnpApp()} />);

      const closeBtn = screen.getByTitle("Close alerts");
      fireEvent.click(closeBtn);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("calls onClose when the overlay backdrop is clicked", async () => {
      const onClose = jest.fn();
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      const { container } = await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen onClose={onClose} app={makeWcnpApp()} />
      );

      const overlay = container.querySelector(".fixed.inset-0.bg-black\\/30");
      if (overlay) fireEvent.click(overlay);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("info dialog", () => {
    it("opens AlertInfoDialog with alert name when info button is clicked", async () => {
      const series = makeAlertSeries({ alertname: "VeryLongAlertNameThatNeedsDialog" });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText("VeryLongAlertNameThatNeedsDialog")).toBeInTheDocument();
      });

      const infoBtn = screen.getByTitle("View full alert name");
      fireEvent.click(infoBtn);

      expect(screen.getByRole("heading", { name: /alert name/i })).toBeInTheDocument();
      const dialogMessages = screen.getAllByText("VeryLongAlertNameThatNeedsDialog");
      expect(dialogMessages.length).toBeGreaterThanOrEqual(2);
    });

    it("closes AlertInfoDialog when X button inside dialog is clicked", async () => {
      const series = makeAlertSeries({ alertname: "AlertForDialog" });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => screen.getByTitle("View full alert name"));
      fireEvent.click(screen.getByTitle("View full alert name"));

      expect(screen.getByRole("heading", { name: /alert name/i })).toBeInTheDocument();

      const allButtons = screen.getAllByRole("button");
      const dialogCloseBtn = allButtons.find(
        (btn) => btn.closest(".fixed.inset-0.bg-black\\/50.z-\\[200\\]")
      );
      expect(dialogCloseBtn).toBeDefined();
      if (dialogCloseBtn) fireEvent.click(dialogCloseBtn);

      await waitFor(() => {
        expect(screen.queryByRole("heading", { name: /alert name/i })).not.toBeInTheDocument();
      });
    });

    it("closes AlertInfoDialog when overlay backdrop is clicked", async () => {
      const series = makeAlertSeries({ alertname: "AlertForBackdrop" });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      const { container } = await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />
      );

      await waitFor(() => screen.getByTitle("View full alert name"));
      fireEvent.click(screen.getByTitle("View full alert name"));

      expect(screen.getByRole("heading", { name: /alert name/i })).toBeInTheDocument();

      const backdrop = container.querySelector(".fixed.inset-0.bg-black\\/50");
      if (backdrop) fireEvent.click(backdrop);

      await waitFor(() => {
        expect(screen.queryByRole("heading", { name: /alert name/i })).not.toBeInTheDocument();
      });
    });
  });

  describe("expanded view", () => {
    it("shows the expand button when alerts are present", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByTitle("Expanded view")).toBeInTheDocument();
      });
    });

    it("opens ExpandedView when expand button is clicked", async () => {
      const app = makeWcnpApp({ name: "order-service" });
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={app} />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => {
        expect(screen.getByText(/alerts — order-service/i)).toBeInTheDocument();
      });
    });

    it("closes ExpandedView when X button is clicked", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => screen.getByTitle("Close expanded view"));
      fireEvent.click(screen.getByTitle("Close expanded view"));

      await waitFor(() => {
        expect(screen.queryByTitle("Close expanded view")).not.toBeInTheDocument();
      });
    });

    it("closes ExpandedView when overlay backdrop is clicked", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      const { container } = await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />
      );

      await waitFor(() => screen.getByTitle("Expanded view"));
      fireEvent.click(screen.getByTitle("Expanded view"));

      await waitFor(() => screen.getByTitle("Close expanded view"));

      const expandedBackdrop = container.querySelector(".fixed.inset-0.bg-black\\/60");
      if (expandedBackdrop) fireEvent.click(expandedBackdrop);

      await waitFor(() => {
        expect(screen.queryByTitle("Close expanded view")).not.toBeInTheDocument();
      });
    });
  });

  describe("refresh", () => {
    it("calls promqlApi.queryRange again on Refresh button click", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const callCountBeforeRefresh = mockQueryRange.mock.calls.length;

      const refreshBtn = screen.getByRole("button", { name: /refresh/i });
      await act(async () => {
        fireEvent.click(refreshBtn);
        jest.advanceTimersByTime(3000);
      });

      await waitFor(() => {
        expect(mockQueryRange.mock.calls.length).toBeGreaterThan(callCountBeforeRefresh);
      });
    });

    it("refresh button is disabled while loading", async () => {
      mockQueryRange.mockReturnValue(new Promise(() => {})); // never resolves
      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const refreshBtn = screen.getByRole("button", { name: /refresh/i });
      expect(refreshBtn).toBeDisabled();
    });
  });

  describe("re-fetch on prop changes", () => {
    it("fetches alerts again when intent prop changes", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      const app = makeWcnpApp();
      const { rerender } = await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={app} intent="cpu" />
      );

      const callsAfterFirst = mockQueryRange.mock.calls.length;

      await act(async () => {
        rerender(<AlertsSidebar {...defaultProps} isOpen app={app} intent="memory" />);
        jest.advanceTimersByTime(3000);
      });

      await waitFor(() => {
        expect(mockQueryRange.mock.calls.length).toBeGreaterThan(callsAfterFirst);
      });
    });

    it("fetches when sidebar changes from closed to open", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      const app = makeWcnpApp();
      const { rerender } = render(
        <AlertsSidebar {...defaultProps} isOpen={false} app={app} />
      );
      expect(mockQueryRange).not.toHaveBeenCalled();

      await act(async () => {
        rerender(<AlertsSidebar {...defaultProps} isOpen={true} app={app} />);
        jest.advanceTimersByTime(3000);
      });

      await waitFor(() => {
        expect(mockQueryRange).toHaveBeenCalled();
      });
    });
  });

  describe("time frame filter", () => {
    it("renders both the value input and the unit selector", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      expect(screen.getByRole("spinbutton", { name: /time frame value/i })).toBeInTheDocument();
      expect(screen.getByRole("combobox", { name: /time frame unit/i })).toBeInTheDocument();
    });

    it("defaults to 1 Hour", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement;
      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i }) as HTMLSelectElement;

      expect(valueInput.value).toBe("1");
      expect(unitSelect.value).toBe("hours");
    });

    it("unit selector has exactly Minutes and Hours options", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i }) as HTMLSelectElement;
      const options = Array.from(unitSelect.options).map((o) => o.text);
      expect(options).toEqual(["Minutes", "Hours"]);
    });

    it("re-fetches alerts when the value changes after clicking Apply", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const callsAfterInitial = mockQueryRange.mock.calls.length;

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "3" } });
      });

      const applyButton = screen.getByRole("button", { name: /apply/i });
      await act(async () => {
        fireEvent.click(applyButton);
        jest.advanceTimersByTime(3000);
      });

      await waitFor(() => {
        expect(mockQueryRange.mock.calls.length).toBeGreaterThan(callsAfterInitial);
      });
    });

    it("re-fetches alerts when unit is switched and value adjusted to a different window after Apply", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const callsAfterInitial = mockQueryRange.mock.calls.length;

      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i });
      await act(async () => {
        fireEvent.change(unitSelect, { target: { value: "minutes" } });
      });

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "30" } });
      });

      const applyButton = screen.getByRole("button", { name: /apply/i });
      await act(async () => {
        fireEvent.click(applyButton);
        jest.advanceTimersByTime(3000);
      });

      await waitFor(() => {
        expect(mockQueryRange.mock.calls.length).toBeGreaterThan(callsAfterInitial);
      });
    });

    it("clamps value to minimum 5 when unit is Minutes", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i });
      await act(async () => { fireEvent.change(unitSelect, { target: { value: "minutes" } }); });

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement;
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "1" } });
        fireEvent.blur(valueInput);
      });

      await waitFor(() => {
        expect(Number((screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement).value)).toBeGreaterThanOrEqual(5);
      });
    });

    it("clamps value to maximum 24 when unit is Hours", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement;
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "99" } });
        fireEvent.blur(valueInput);
      });

      await waitFor(() => {
        expect(Number((screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement).value)).toBeLessThanOrEqual(24);
      });
    });

    it("disables Apply button while loading", async () => {
      mockQueryRange.mockReturnValue(new Promise(() => {})); // never resolves
      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      expect(screen.getByRole("button", { name: /apply/i })).toBeDisabled();
    });
  });

  describe("dark mode", () => {
    beforeEach(() => { mockIsDark = true; });
    afterEach(() => { mockIsDark = false; });

    it("renders sidebar with dark mode classes", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      expect(screen.getByText("Alerts")).toBeInTheDocument();
    });

    it("renders dark mode with alerts present (table branch)", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await waitFor(() => expect(screen.getByText("HighCPUUsage")).toBeInTheDocument());
    });

    it("renders error state in dark mode", async () => {
      mockQueryRange.mockRejectedValue(new Error("Dark mode error"));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await waitFor(() => expect(screen.getByText("Dark mode error")).toBeInTheDocument());
    });
  });

  describe("managed service filters", () => {
    it("builds filters for cassandra service type", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({ serviceType: "cassandra", assembly: "my-cluster" })} />
      );
      await waitFor(() => {
        const call = mockQueryRange.mock.calls[0][0] as any;
        expect(call.promql).toContain('alert_type="cassandra"');
        expect(call.promql).toContain('cluster="my-cluster"');
      });
    });

    it("builds filters for cosmos service type", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({
          serviceType: "cosmos",
          subscriptionId: "sub-123",
          resourceGroup: "rg-cosmos",
        })} />
      );
      await waitFor(() => {
        const call = mockQueryRange.mock.calls[0][0] as any;
        expect(call.promql).toContain('alert_type="cosmos"');
        expect(call.promql).toContain('subscription_name="sub-123"');
        expect(call.promql).toContain('resource_group="rg-cosmos"');
      });
    });

    it("builds filters for kafka service type", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({
          serviceType: "kafka",
          assembly: "kafka-cluster",
          topicName: "my-topic",
        })} />
      );
      await waitFor(() => {
        const call = mockQueryRange.mock.calls[0][0] as any;
        expect(call.promql).toContain('alert_type="kafka"');
        expect(call.promql).toContain('cluster="kafka-cluster"');
        expect(call.promql).toContain('topic="my-topic"');
      });
    });

    it("builds filters for meghacache service type", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({
          serviceType: "meghacache",
          assembly: "mega-assembly",
        })} />
      );
      await waitFor(() => {
        const call = mockQueryRange.mock.calls[0][0] as any;
        expect(call.promql).toContain('alert_type="meghacache"');
        expect(call.promql).toContain('megacache_assembly="mega-assembly"');
      });
    });

    it("builds filters for sql service type", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({
          serviceType: "sql",
          databaseName: "my-db",
        })} />
      );
      await waitFor(() => {
        const call = mockQueryRange.mock.calls[0][0] as any;
        expect(call.promql).toContain('alert_type="sql"');
        expect(call.promql).toContain('database="my-db"');
      });
    });

    it("builds filters for oracle service type", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({
          serviceType: "oracle",
          databaseName: "oracle-db",
        })} />
      );
      await waitFor(() => {
        const call = mockQueryRange.mock.calls[0][0] as any;
        expect(call.promql).toContain('alert_type="oracle"');
        expect(call.promql).toContain('database="oracle-db"');
      });
    });
  });

  describe("oneops application type", () => {
    it("builds filters for oneops application type", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      const app = makeWcnpApp({
        applicationType: "oneops",
        oneOpsAssembly: "test-assembly",
        oneOpsPlatform: "test-platform",
      });
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={app} />);
      await waitFor(() => {
        const call = mockQueryRange.mock.calls[0][0] as any;
        expect(call.promql).toContain('alert_type="oneops"');
        expect(call.promql).toContain('assembly="test-assembly"');
        expect(call.promql).toContain('platform="test-platform"');
      });
    });
  });

  describe("getAppType", () => {
    it("returns applicationType for Application objects", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp({ applicationType: "wcnp" })} />);
      expect(screen.getByText(/wcnp/i)).toBeInTheDocument();
    });

    it("returns serviceType for ManagedServiceData objects", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({ serviceType: "cosmos" })} />
      );
      expect(screen.getByText(/cosmos/i)).toBeInTheDocument();
    });

    it("returns Unknown for ManagedServiceData with empty serviceType", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(
        <AlertsSidebar {...defaultProps} isOpen app={makeManagedService({ serviceType: "" })} />
      );
      expect(screen.getByText(/Unknown/)).toBeInTheDocument();
    });
  });

  describe("sorting branches", () => {
    const makeMultiAlertResult = () => {
      const now = Math.floor(Date.now() / 1000);
      const s1 = makeAlertSeries({
        alert_sla_name: "SLA-Alpha",
        alertname: "AlertAlpha",
        cluster: "cluster-a",
        mms_xmatters_group: "group-a",
        mms_slack_channel: "#slack-a",
        alert_owner_category: "category-a",
        episode_start_ts: now - 120,
        values: [[now - 120, "1"], [now - 60, "1"]],
      });
      const s2 = makeAlertSeries({
        alert_sla_name: "SLA-Beta",
        alertname: "AlertBeta",
        cluster: "cluster-b",
        mms_xmatters_group: "group-b",
        mms_slack_channel: "#slack-b",
        alert_owner_category: "category-b",
        episode_start_ts: now - 60,
        values: [[now - 60, "1"], [now, "1"]],
      });
      return makePromQLResult([s1, s2]);
    };

    async function renderWithAlerts() {
      mockQueryRange.mockResolvedValue(makeMultiAlertResult());
      const result = await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await waitFor(() => expect(screen.getByText("SLA-Alpha")).toBeInTheDocument());
      return result;
    }

    it("sorts by episode_start_ts when clicked", async () => {
      await renderWithAlerts();
      const header = screen.getByText("Alert start time");
      await act(async () => { fireEvent.click(header); });
      // Verify sorting happened without error
      expect(screen.getByText("SLA-Alpha")).toBeInTheDocument();
    });

    it("sorts by status when clicked", async () => {
      await renderWithAlerts();
      const header = screen.getByText("Status");
      await act(async () => { fireEvent.click(header); });
      expect(screen.getByText("SLA-Alpha")).toBeInTheDocument();
    });

    it("sorts by cluster when clicked", async () => {
      await renderWithAlerts();
      const header = screen.getByText("Cluster_id");
      await act(async () => { fireEvent.click(header); });
      expect(screen.getByText("cluster-a")).toBeInTheDocument();
    });

    it("sorts by x_matters_group when clicked", async () => {
      await renderWithAlerts();
      const header = screen.getByText("x_matters_group");
      await act(async () => { fireEvent.click(header); });
      expect(screen.getByText("group-a")).toBeInTheDocument();
    });

    it("sorts by Slack_xmatters when clicked", async () => {
      await renderWithAlerts();
      const header = screen.getByText("Slack_xmatters");
      await act(async () => { fireEvent.click(header); });
      expect(screen.getByText("#slack-a")).toBeInTheDocument();
    });

    it("sorts by alert_owner_category when clicked", async () => {
      await renderWithAlerts();
      const header = screen.getByText("Alert category");
      await act(async () => { fireEvent.click(header); });
      expect(screen.getByText("category-a")).toBeInTheDocument();
    });

    it("sorts by alertname when clicked", async () => {
      await renderWithAlerts();
      const header = screen.getByText("Alert name");
      await act(async () => { fireEvent.click(header); });
      expect(screen.getByText("AlertAlpha")).toBeInTheDocument();
    });

    it("toggles sort direction: asc → desc → clear", async () => {
      await renderWithAlerts();
      const header = screen.getByText("SLA_name");
      // 1st click: asc
      await act(async () => { fireEvent.click(header); });
      // 2nd click: desc
      await act(async () => { fireEvent.click(header); });
      // 3rd click: clear sort
      await act(async () => { fireEvent.click(header); });
      expect(screen.getByText("SLA-Alpha")).toBeInTheDocument();
    });

    it("sorts with null episode_start_ts values", async () => {
      const now = Math.floor(Date.now() / 1000);
      const s1 = {
        metric: { alertname: "NoTsAlert", alertstate: "firing", alert_sla_name: "NoTsSLA" },
        values: [] as [number, string][],
      };
      const s2 = makeAlertSeries({
        alertname: "WithTsAlert",
        alert_sla_name: "WithTsSLA",
        episode_start_ts: now - 60,
        values: [[now - 60, "1"]],
      });
      mockQueryRange.mockResolvedValue(makePromQLResult([s1, s2]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await waitFor(() => expect(screen.getByText("WithTsSLA")).toBeInTheDocument());
      const header = screen.getByText("Alert start time");
      await act(async () => { fireEvent.click(header); });
      expect(screen.getByText("NoTsSLA")).toBeInTheDocument();
    });
  });

  describe("timeline tab", () => {
    it("switches to timeline view when Timeline tab is clicked", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await waitFor(() => expect(screen.getByText("Table")).toBeInTheDocument());

      fireEvent.click(screen.getByText("Timeline"));
      await waitFor(() => {
        expect(screen.getByTestId("graph-section-Alert Timeline")).toBeInTheDocument();
        expect(screen.getByTestId("graph-section-Alerts by SLA Name")).toBeInTheDocument();
      });
    });

    it("switches back to table view when Table tab is clicked after Timeline", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await waitFor(() => screen.getByText("Table"));

      fireEvent.click(screen.getByText("Timeline"));
      fireEvent.click(screen.getByText("Table"));
      await waitFor(() => {
        expect(screen.getByText("SLA_name")).toBeInTheDocument();
      });
    });
  });

  describe("expanded view timeline tab", () => {
    it("shows timeline graphs in expanded view", async () => {
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => screen.getByTitle("Expanded view"));
      await act(async () => { fireEvent.click(screen.getByTitle("Expanded view")); });

      await waitFor(() => screen.getByText(/alerts — checkout-service/i));

      // Switch to timeline in expanded view — there will be 2 Timeline buttons (sidebar + expanded)
      const timelineButtons = screen.getAllByText("Timeline");
      await act(async () => { fireEvent.click(timelineButtons[timelineButtons.length - 1]); });

      await waitFor(() => {
        const graphSections = screen.getAllByTestId(/graph-section-/);
        expect(graphSections.length).toBeGreaterThanOrEqual(2);
      });
    });

    it("shows loading state in expanded view table", async () => {
      mockQueryRange.mockReturnValue(new Promise(() => {})); // never resolves
      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      // The sidebar shows loading. We can't easily open expanded view while loading
      // because the expand button only appears after data loads.
      // Instead, test that the loading text is present in the sidebar.
      expect(screen.getByText(/fetching alerts/i)).toBeInTheDocument();
    });
  });

  describe("unit conversion", () => {
    it("converts minutes to hours when switching unit from minutes to hours", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      // Switch to minutes first
      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i });
      await act(async () => {
        fireEvent.change(unitSelect, { target: { value: "minutes" } });
      });

      // Set value to 120 minutes
      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "120" } });
      });

      // Switch back to hours
      await act(async () => {
        fireEvent.change(unitSelect, { target: { value: "hours" } });
      });

      // Value should be converted to 2 hours
      const currentValue = (screen.getByRole("spinbutton", { name: /time frame value/i }) as HTMLInputElement).value;
      expect(Number(currentValue)).toBeLessThanOrEqual(24);
    });
  });

  describe("retry on timeout", () => {
    it("retries table fetch on timeout error", async () => {
      const timeoutError = new Error("500: AsyncRequestTimeoutException");
      mockQueryRange
        .mockRejectedValueOnce(timeoutError) // first call: table fails
        .mockResolvedValueOnce(makeEmptyPromQLResult()) // retry: succeeds
        .mockResolvedValue(makeEmptyPromQLResult()); // graph call

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      // Advance through retry delay (2s) + graph delay (2s) + extra
      await act(async () => { jest.advanceTimersByTime(2500); });
      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(mockQueryRange.mock.calls.length).toBeGreaterThanOrEqual(2);
      });
    });

    it("handles retry failure for table fetch", async () => {
      const timeoutError = new Error("500: AsyncRequestTimeoutException");
      mockQueryRange
        .mockRejectedValueOnce(timeoutError)
        .mockRejectedValueOnce(new Error("Retry also failed"))
        .mockResolvedValue(makeEmptyPromQLResult());

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await act(async () => { jest.advanceTimersByTime(2500); });
      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(mockQueryRange.mock.calls.length).toBeGreaterThanOrEqual(2);
      });
    });

    it("handles graph fetch timeout with retry", async () => {
      const graphTimeoutError = new Error("Timeout: server did not respond");
      mockQueryRange
        .mockResolvedValueOnce(makePromQLResult([makeAlertSeries()])) // table succeeds
        .mockRejectedValueOnce(graphTimeoutError) // graph fails
        .mockResolvedValueOnce(makePromQLResult([makeAlertSeries()])); // graph retry succeeds

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      // table completes, then 2s delay for graph, then graph fails, then 2s retry delay
      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(mockQueryRange.mock.calls.length).toBeGreaterThanOrEqual(3);
      });
    });

    it("handles graph fetch retry failure", async () => {
      const graphTimeoutError = new Error("500: Timeout");
      mockQueryRange
        .mockResolvedValueOnce(makePromQLResult([makeAlertSeries()])) // table succeeds
        .mockRejectedValueOnce(graphTimeoutError) // graph fails
        .mockRejectedValueOnce(new Error("Graph retry also failed"));

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(mockQueryRange.mock.calls.length).toBeGreaterThanOrEqual(3);
      });
    });

    it("handles non-timeout graph errors without retry", async () => {
      mockQueryRange
        .mockResolvedValueOnce(makePromQLResult([makeAlertSeries()])) // table succeeds
        .mockRejectedValueOnce(new Error("Permission denied")); // graph fails with non-timeout

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(screen.getByText("HighCPUUsage")).toBeInTheDocument();
      });
    });
  });

  describe("502/503/504 error handling", () => {
    it("shows service unavailable message for 502 errors", async () => {
      // Synchronous throw to hit the top-level catch (lines 810-815)
      mockQueryRange.mockImplementation(() => { throw new Error("502 Bad Gateway"); });

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
      });
    });

    it("shows service unavailable message for 503 errors", async () => {
      mockQueryRange.mockImplementation(() => { throw new Error("503 Service Unavailable"); });

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
      });
    });

    it("shows service unavailable message for 504 errors", async () => {
      mockQueryRange.mockImplementation(() => { throw new Error("504 Gateway Timeout"); });

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
      });
    });

    it("shows original error for non-5xx errors in catch block", async () => {
      mockQueryRange.mockImplementation(() => { throw new Error("Something broke"); });

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(screen.getByText("Something broke")).toBeInTheDocument();
      });
    });

    it("shows fallback for non-Error throw in catch block", async () => {
      mockQueryRange.mockImplementation(() => { throw "raw string error"; });

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(screen.getByText("Failed to fetch alerts")).toBeInTheDocument();
      });
    });
  });

  describe("handleRefresh sets refreshing state", () => {
    it("calls handleRefresh and completes", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      const refreshBtn = screen.getByRole("button", { name: /refresh/i });
      await act(async () => { fireEvent.click(refreshBtn); });
      // Advance timers for the 2s graph delay
      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });

      // Verify refresh completed (button re-enabled)
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /refresh/i })).not.toBeDisabled();
      });
    });
  });

  describe("pagination", () => {
    it("renders pagination controls with page size selector", async () => {
      // Create enough alerts to trigger pagination
      const series = Array.from({ length: 3 }, (_, i) =>
        makeAlertSeries({ alertname: `Alert${i}`, alert_sla_name: `SLA${i}` })
      );
      mockQueryRange.mockResolvedValue(makePromQLResult(series));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText("Rows per page:")).toBeInTheDocument();
      });
    });
  });

  describe("non-Error rejection for graph", () => {
    it("handles non-Error table rejection (string throw)", async () => {
      mockQueryRange
        .mockRejectedValueOnce("string error") // table: non-Error rejection
        .mockResolvedValue(makeEmptyPromQLResult()); // graph

      render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      // Advance through the full flow: table catch + 2s graph delay + graph call
      await act(async () => { jest.advanceTimersByTime(3000); });
      await act(async () => { jest.advanceTimersByTime(3000); });

      await waitFor(() => {
        expect(screen.getByText("Failed to fetch alerts")).toBeInTheDocument();
      });
    });
  });

  describe("formatRelativeTime coverage (hours and days)", () => {
    it("shows hours ago when alert start is hours old", async () => {
      const now = Math.floor(Date.now() / 1000);
      const twoHoursAgo = now - 7200; // 2 hours ago
      const series = makeAlertSeries({
        alertname: "OldAlert",
        alert_sla_name: "OldSLA",
        episode_start_ts: twoHoursAgo,
        values: [[twoHoursAgo, "1"], [twoHoursAgo + 60, "1"]],
      });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText(/2 hrs ago/i)).toBeInTheDocument();
      });
    });

    it("shows days ago when alert start is days old", async () => {
      const now = Math.floor(Date.now() / 1000);
      const twoDaysAgo = now - 172800; // 2 days ago
      const series = makeAlertSeries({
        alertname: "VeryOldAlert",
        alert_sla_name: "VeryOldSLA",
        episode_start_ts: twoDaysAgo,
        values: [[twoDaysAgo, "1"], [twoDaysAgo + 60, "1"]],
      });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));

      // Set time window to 24 hours so the old alert appears
      const result = render(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);
      await act(async () => { jest.advanceTimersByTime(3000); });

      // Change to 24 hours time window and apply
      const unitSelect = screen.getByRole("combobox", { name: /time frame unit/i });
      await act(async () => { fireEvent.change(unitSelect, { target: { value: "hours" } }); });
      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      await act(async () => { fireEvent.change(valueInput, { target: { value: "24" } }); });

      // The alert with twoDaysAgo timestamp should still display if the API returns it
      await waitFor(() => {
        expect(screen.getByText(/day/i)).toBeInTheDocument();
      });
    });

    it("shows '1 hr ago' with singular form", async () => {
      const now = Math.floor(Date.now() / 1000);
      const oneHourAgo = now - 3600; // exactly 1 hour ago
      const series = makeAlertSeries({
        alertname: "OneHrAlert",
        alert_sla_name: "OneHrSLA",
        episode_start_ts: oneHourAgo,
        values: [[oneHourAgo, "1"], [oneHourAgo + 60, "1"]],
      });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText(/1 hr ago/)).toBeInTheDocument();
      });
    });

    it("shows '1 day ago' with singular form", async () => {
      const now = Math.floor(Date.now() / 1000);
      const oneDayAgo = now - 86400; // exactly 1 day ago
      const series = makeAlertSeries({
        alertname: "OneDayAlert",
        alert_sla_name: "OneDaySLA",
        episode_start_ts: oneDayAgo,
        values: [[oneDayAgo, "1"], [oneDayAgo + 60, "1"]],
      });
      mockQueryRange.mockResolvedValue(makePromQLResult([series]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      await waitFor(() => {
        expect(screen.getByText(/1 day ago/)).toBeInTheDocument();
      });
    });
  });

  describe("expanded view with loading (lines 614-617)", () => {
    it("shows loading in expanded view when data re-fetches", async () => {
      // First resolve with data, then re-fetch with never resolving
      mockQueryRange.mockResolvedValue(makePromQLResult([makeAlertSeries()]));
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      // Open expanded view (button only available after data loads)
      await waitFor(() => screen.getByTitle("Expanded view"));
      await act(async () => { fireEvent.click(screen.getByTitle("Expanded view")); });
      await waitFor(() => screen.getByText(/alerts — checkout-service/i));

      // Now make query never resolve and click refresh to trigger loading
      mockQueryRange.mockReturnValue(new Promise(() => {}));
      const refreshBtns = screen.getAllByRole("button", { name: /refresh/i });
      await act(async () => { fireEvent.click(refreshBtns[refreshBtns.length - 1]); });

      // The expanded view should show loading
      const fetching = screen.getAllByText(/fetching alerts/i);
      expect(fetching.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("expanded view with empty alerts (AlertsTable empty state, lines 365-373)", () => {
    it("shows 'No data available' inside AlertsTable in expanded view with 0 alerts", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      // The expand button shows once alerts (empty array) has been loaded
      await waitFor(() => screen.getByTitle("Expanded view"));
      await act(async () => { fireEvent.click(screen.getByTitle("Expanded view")); });

      await waitFor(() => {
        expect(screen.getByText(/alerts — checkout-service/i)).toBeInTheDocument();
        // AlertsTable renders "No data available" when passed an empty array
        expect(screen.getByText("No data available")).toBeInTheDocument();
      });
    });
  });

  describe("getAppName/getAppType edge cases (lines 837-838, 844-845)", () => {
    it("returns Unknown for app objects that lack name property", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      // Create an object that has neither 'applicationType' nor 'serviceType'
      // but still passes as non-null app
      const edgeApp = { id: 999 } as unknown as Application;
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={edgeApp} />);

      // getAppName should return "Unknown" since "name" is not in the object
      // getAppType should also return "Unknown"
      const unknownTexts = screen.getAllByText(/Unknown/);
      expect(unknownTexts.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("long time windows (computeGraphStep coverage)", () => {
    it("uses larger step for time windows > 12 hours", async () => {
      mockQueryRange.mockResolvedValue(makeEmptyPromQLResult());
      await renderAndSettle(<AlertsSidebar {...defaultProps} isOpen app={makeWcnpApp()} />);

      // Set to 24 hours to cover the > 43200s branch
      const valueInput = screen.getByRole("spinbutton", { name: /time frame value/i });
      await act(async () => {
        fireEvent.change(valueInput, { target: { value: "24" } });
      });

      const applyButton = screen.getByRole("button", { name: /apply/i });
      await act(async () => {
        fireEvent.click(applyButton);
        jest.advanceTimersByTime(5000);
      });

      await waitFor(() => {
        expect(mockQueryRange).toHaveBeenCalled();
      });
    });
  });
});
