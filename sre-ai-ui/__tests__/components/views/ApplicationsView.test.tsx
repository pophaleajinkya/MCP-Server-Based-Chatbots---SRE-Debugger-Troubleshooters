import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ApplicationsView } from "@/components/views/ApplicationsView";
import type { Application, DependencyData } from "@/lib/api-client";

// ─── Mock heavy sub-components ────────────────────────────────────────────────

jest.mock("@/components/HealthReportModal", () => ({
  __esModule: true,
  default: ({ onClose }: { app: unknown; onClose: () => void }) => (
    <div data-testid="health-report-modal">
      <button onClick={onClose}>Close Health Report</button>
    </div>
  ),
}));

jest.mock("@/components/AlertsSidebar", () => ({
  AlertsSidebar: ({
    isOpen,
    onClose,
  }: {
    isOpen: boolean;
    onClose: () => void;
    app: unknown;
  }) =>
    isOpen ? (
      <div data-testid="alerts-sidebar">
        <button onClick={onClose}>Close Alerts</button>
      </div>
    ) : null,
}));

jest.mock("@/components/MermaidDiagram", () => ({
  __esModule: true,
  default: ({ diagram }: { diagram: string }) => (
    <div data-testid="mermaid-diagram">{diagram}</div>
  ),
}));

// ─── Mock ThemeContext ─────────────────────────────────────────────────────────

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false, theme: "light", toggleTheme: jest.fn() }),
}));

// ─── Mock AuthContext ──────────────────────────────────────────────────────────

jest.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: null }),
}));

// ─── Mock ViewContext ──────────────────────────────────────────────────────────

jest.mock("@/contexts/ViewContext", () => ({
  useViewContext: () => ({
    setApplicationData: jest.fn(),
    setSelectedApplication: jest.fn(),
    setFilteredApplicationCount: jest.fn(),
    setApplicationFilters: jest.fn(),
    selectedApplication: null,
  }),
}));

// ─── Mock api-client ─────────────────────────────────────────────────────────

const mockFetchAll = jest.fn<Promise<Application[]>, []>();
const mockFetchUpstream = jest.fn<Promise<DependencyData[]>, [number]>();
const mockFetchDownstream = jest.fn<Promise<DependencyData[]>, [number]>();
const mockAddDependency = jest.fn<Promise<void>, [number, number]>();
const mockAddUpstreamDependency = jest.fn<Promise<void>, [number, number]>();
const mockDeleteDownstreamDependency = jest.fn<Promise<void>, [number, number]>();
const mockDeleteUpstreamDependency = jest.fn<Promise<void>, [number, number]>();

jest.mock("@/lib/api-client", () => ({
  applicationsApi: {
    getCached: jest.fn(() => null),
    fetchAll: () => mockFetchAll(),
    fetchUpstream: (id: number) => mockFetchUpstream(id),
    fetchDownstream: (id: number) => mockFetchDownstream(id),
    addDependency: (appId: number, depId: number) => mockAddDependency(appId, depId),
    addUpstreamDependency: (appId: number, upId: number) => mockAddUpstreamDependency(appId, upId),
    deleteDownstreamDependency: (appId: number, depId: number) =>
      mockDeleteDownstreamDependency(appId, depId),
    deleteUpstreamDependency: (appId: number, depId: number) =>
      mockDeleteUpstreamDependency(appId, depId),
    fetchByWcnpId: jest.fn().mockResolvedValue(null),
    fetchByOneOpsId: jest.fn().mockResolvedValue(null),
    fetchByPageFlowId: jest.fn().mockResolvedValue(null),
  },
  dependencyApprovalsApi: {
    submitRequest: jest.fn().mockResolvedValue({
      data: { id: 1, status: "PENDING", approvedBy: null, reason: null },
    }),
  },
}));

// ─── Mock DataTable ──────────────────────────────────────────────────────────
// Renders a simplified table that invokes column cell functions, so
// ApplicationsView-specific logic (modals, handlers, context wiring) can be tested.

jest.mock("@/components/ui/DataTable", () => {
  const React = require("react");
  return {
    __esModule: true,
    DataTable: ({ data, columns, loading, error, onRetry, title, onRowClick, emptyMessage, filterEmptyMessage }: any) => {
      if (loading) {
        return (
          <div>
            <div className="w-12 h-12 border-4 border-[#002244] dark:border-blue-400 border-t-transparent dark:border-t-transparent rounded-full animate-spin" />
            <p>Loading {title?.toLowerCase() || "data"}...</p>
          </div>
        );
      }
      if (error) {
        return (
          <div>
            <h3 role="heading">Error</h3>
            <p>{error}</p>
            {onRetry && <button onClick={onRetry}>Try Again</button>}
          </div>
        );
      }
      if (data.length === 0) {
        return <div><h1 role="heading">{title}</h1><p>{emptyMessage || "No data found"}</p></div>;
      }
      return (
        <div>
          <h1 role="heading">{title}</h1>
          <p>{data.length} {title?.toLowerCase() || "rows"}</p>
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
                <tr key={rowIdx} onClick={() => onRowClick?.(row)}>
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
    CellBadge: ({ children }: any) => <span>{children}</span>,
    CellBoolean: ({ value }: any) => <span>{value ? "Yes" : "No"}</span>,
    CellTruncated: ({ text }: any) => <span>{text}</span>,
    CellCopyable: ({ text }: any) => <span>{text}</span>,
    CellList: ({ items, prefix }: any) =>
      items?.length ? (
        <span>{items.map((item: string) => `${prefix || ""}${item}`).join(", ")}</span>
      ) : null,
    multiSelectFilterFn: jest.fn(),
    booleanFilterFn: jest.fn(),
  };
});

// ─── Fixtures ─────────────────────────────────────────────────────────────────

function makeApp(overrides: Partial<Application> = {}): Application {
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

function makeDep(overrides: Partial<DependencyData> = {}): DependencyData {
  return {
    id: 99,
    application_id: 99,
    application_name: "dep-service",
    namespace: "dep-ns",
    app_name: "dep-app",
    tier: "T2",
    ...overrides,
  };
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  // Default: fetchAll returns a list of one app
  mockFetchAll.mockResolvedValue([makeApp()]);
  mockFetchUpstream.mockResolvedValue([]);
  mockFetchDownstream.mockResolvedValue([]);
  mockAddDependency.mockResolvedValue(undefined);
  mockAddUpstreamDependency.mockResolvedValue(undefined);
  mockDeleteDownstreamDependency.mockResolvedValue(undefined);
  mockDeleteUpstreamDependency.mockResolvedValue(undefined);

  // Stub URL APIs used by CSV export
  global.URL.createObjectURL = jest.fn(() => "blob:test-url");
  global.URL.revokeObjectURL = jest.fn();

  // jsdom doesn't implement clipboard
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: jest.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  });
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("ApplicationsView", () => {
  // ─── Loading state ──────────────────────────────────────────────────────────
  describe("loading state", () => {
    it("shows a loading spinner while fetching applications", () => {
      let resolve!: (v: Application[]) => void;
      mockFetchAll.mockReturnValue(new Promise((res) => { resolve = res; }));

      render(<ApplicationsView />);

      expect(screen.getByText(/loading applications/i)).toBeInTheDocument();

      // Clean up by resolving
      act(() => { resolve([]); });
    });

    it("does not show the table while loading", () => {
      let resolve!: (v: Application[]) => void;
      mockFetchAll.mockReturnValue(new Promise((res) => { resolve = res; }));

      render(<ApplicationsView />);

      expect(screen.queryByRole("table")).not.toBeInTheDocument();

      act(() => { resolve([]); });
    });
  });

  // ─── Error state ────────────────────────────────────────────────────────────
  describe("error state", () => {
    it("shows an error message when fetchAll throws", async () => {
      mockFetchAll.mockRejectedValue(new Error("Network failure"));

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText("Network failure")).toBeInTheDocument();
      });
    });

    it("shows fallback error for non-Error rejections", async () => {
      mockFetchAll.mockRejectedValue("something bad");

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText("Failed to fetch applications")).toBeInTheDocument();
      });
    });

    it("shows an Error heading in the error view", async () => {
      mockFetchAll.mockRejectedValue(new Error("Timeout"));

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: /error/i })).toBeInTheDocument();
      });
    });

    it("retries fetching when 'Try Again' is clicked", async () => {
      mockFetchAll
        .mockRejectedValueOnce(new Error("first failure"))
        .mockResolvedValue([]);

      render(<ApplicationsView />);

      await waitFor(() => screen.getByRole("button", { name: /try again/i }));
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));

      await waitFor(() => {
        expect(mockFetchAll).toHaveBeenCalledTimes(2);
      });
    });
  });

  // ─── Populated table ────────────────────────────────────────────────────────
  describe("populated state", () => {
    it("renders the Applications heading after load", async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: /applications/i })).toBeInTheDocument();
      });
    });

    it("renders a table with application rows", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ namespace: "order-ns" })]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText("order-ns")).toBeInTheDocument();
      });
    });

    it("shows count of applications in the toolbar", async () => {
      mockFetchAll.mockResolvedValue([makeApp(), makeApp({ id: 2, name: "payment-service" })]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText(/2 applications/i)).toBeInTheDocument();
      });
    });

    it("shows 'No applications found' when fetchAll returns empty list", async () => {
      mockFetchAll.mockResolvedValue([]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText(/no applications found/i)).toBeInTheDocument();
      });
    });

    it("renders wcnp applications in the table", async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        const table = screen.getByRole("table");
        expect(table).toBeInTheDocument();
      });
    });

    it("renders certified 'Yes' badge for certified apps", async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText("Yes")).toBeInTheDocument();
      });
    });

    it("renders certified 'No' badge for uncertified apps", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ certified: false })]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText("No")).toBeInTheDocument();
      });
    });

    it("renders slack channels in the table when present", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ slackChannels: ["platform-eng"] })]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText("#platform-eng")).toBeInTheDocument();
      });
    });

    it("renders xmatters groups in the table when present", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ xmattersGroups: ["sre-group"] })]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText("sre-group")).toBeInTheDocument();
      });
    });

    it("renders email addresses in the table when present", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ emails: ["sre@example.com"] })]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText("sre@example.com")).toBeInTheDocument();
      });
    });
  });

  // ─── Detail modal ────────────────────────────────────────────────────────────
  describe("detail modal", () => {
    it("opens the detail modal when Details button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));

      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("Application Details")).toBeInTheDocument();
      });
    });

    it("shows the app name in the detail modal subheading", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ name: "my-special-app" })]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getAllByText("my-special-app").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("closes the detail modal when the X button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => screen.getByText("Application Details"));

      // There is an X button in the modal header
      const allCloseButtons = screen.getAllByRole("button");
      const closeBtn = allCloseButtons.find(
        (btn) => btn.closest(".bg-\\[\\#002244\\]") && btn.querySelector("svg")
      );
      if (closeBtn) fireEvent.click(closeBtn);

      await waitFor(() => {
        expect(screen.queryByText("Application Details")).not.toBeInTheDocument();
      });
    });

    it("closes the detail modal when clicking the modal Close button in the footer", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => screen.getByText("Application Details"));

      // The footer has an explicit "Close" button
      const closeBtn = screen.getByRole("button", { name: /^close$/i });
      fireEvent.click(closeBtn);

      await waitFor(() => {
        expect(screen.queryByText("Application Details")).not.toBeInTheDocument();
      });
    });

    it("closes the detail modal when clicking the backdrop", async () => {
      const { container } = render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => screen.getByText("Application Details"));

      // Click the backdrop (outermost div of modal)
      const backdrop = container.querySelector(".fixed.inset-0.bg-black\\/50");
      if (backdrop) fireEvent.click(backdrop);

      await waitFor(() => {
        expect(screen.queryByText("Application Details")).not.toBeInTheDocument();
      });
    });

    it("shows WCNP section for wcnp apps with namespace", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("WCNP")).toBeInTheDocument();
      });
    });

    it("shows OneOps section for oneops apps", async () => {
      mockFetchAll.mockResolvedValue([
        makeApp({
          applicationType: "oneops",
          oneOpsOrg: "my-org",
          oneOpsAssembly: "my-assembly",
          oneOpsPlatform: "my-platform",
        }),
      ]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("OneOps")).toBeInTheDocument();
        expect(screen.getAllByText("my-org").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("shows team section when app has team data", async () => {
      mockFetchAll.mockResolvedValue([
        makeApp({
          team: {
            jira: "https://jira.example.com",
            isPrimaryTeam: true,
            members: [{ id: 1, name: "Alice", email: "alice@example.com" }],
          },
        }),
      ]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getAllByText("Team").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("Jira Board").length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText(/Alice/)).toBeInTheDocument();
      });
    });

    it("shows communication section when app has slack channels", async () => {
      mockFetchAll.mockResolvedValue([
        makeApp({ slackChannels: ["platform-sre"] }),
      ]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("Communication")).toBeInTheDocument();
      });
    });

    it("shows cluster info when app has a cluster", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ cluster: "eus2-prod-a21" })]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        const clusterEls = screen.getAllByText("eus2-prod-a21");
        expect(clusterEls.length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  // ─── Alerts sidebar ──────────────────────────────────────────────────────────
  describe("alerts sidebar", () => {
    it("opens the alerts sidebar when Alerts button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View active alerts"));

      fireEvent.click(screen.getByTitle("View active alerts"));

      await waitFor(() => {
        expect(screen.getByTestId("alerts-sidebar")).toBeInTheDocument();
      });
    });

    it("closes the alerts sidebar when the stub's close button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View active alerts"));
      fireEvent.click(screen.getByTitle("View active alerts"));

      await waitFor(() => screen.getByTestId("alerts-sidebar"));
      fireEvent.click(screen.getByRole("button", { name: /close alerts/i }));

      await waitFor(() => {
        expect(screen.queryByTestId("alerts-sidebar")).not.toBeInTheDocument();
      });
    });
  });

  // ─── Health report modal ─────────────────────────────────────────────────────
  describe("health report modal", () => {
    it("opens health report modal when Health Report button is clicked for wcnp app", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("Run health check report"));

      fireEvent.click(screen.getByTitle("Run health check report"));

      await waitFor(() => {
        expect(screen.getByTestId("health-report-modal")).toBeInTheDocument();
      });
    });

    it("closes the health report modal when its close button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("Run health check report"));
      fireEvent.click(screen.getByTitle("Run health check report"));

      await waitFor(() => screen.getByTestId("health-report-modal"));
      fireEvent.click(screen.getByRole("button", { name: /close health report/i }));

      await waitFor(() => {
        expect(screen.queryByTestId("health-report-modal")).not.toBeInTheDocument();
      });
    });

    it("does not show health report button for non-wcnp apps", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ applicationType: "oneops" })]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));

      // Health check button is not rendered for non-wcnp apps
      expect(screen.queryByTitle("Run health check report")).not.toBeInTheDocument();
    });
  });

  // ─── Downstream dependencies ─────────────────────────────────────────────────
  describe("downstream dependencies modal", () => {
    it("opens the downstream modal when Downstream button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));

      act(() => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => {
        expect(screen.getByText("Downstream Dependencies")).toBeInTheDocument();
      });
    });

    it("shows loading state while fetching downstream dependencies", async () => {
      let resolveDeps!: (v: DependencyData[]) => void;
      mockFetchDownstream.mockReturnValue(new Promise((res) => { resolveDeps = res; }));

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => {
        expect(screen.getByText(/loading downstream dependencies/i)).toBeInTheDocument();
      });

      act(() => { resolveDeps([]); });
    });

    it("shows the empty state when no downstream dependencies exist", async () => {
      mockFetchDownstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => {
        expect(screen.getByText(/no downstream dependencies found/i)).toBeInTheDocument();
      });
    });

    it("shows an error when fetchDownstream throws", async () => {
      mockFetchDownstream.mockRejectedValue(new Error("Downstream fetch failed"));

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => {
        expect(screen.getByText("Downstream fetch failed")).toBeInTheDocument();
      });
    });

    it("shows the flow diagram when dependencies have data", async () => {
      mockFetchDownstream.mockResolvedValue([makeDep()]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => {
        expect(screen.getByTestId("mermaid-diagram")).toBeInTheDocument();
      });
    });

    it("switches to table view when Table button is clicked", async () => {
      mockFetchDownstream.mockResolvedValue([makeDep()]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        // In table view the diagram should no longer be visible
        expect(screen.queryByTestId("mermaid-diagram")).not.toBeInTheDocument();
      });
    });
  });

  // ─── Upstream dependencies ───────────────────────────────────────────────────
  describe("upstream dependencies modal", () => {
    it("opens the upstream modal when Upstream button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View upstream dependencies"));

      act(() => { fireEvent.click(screen.getByTitle("View upstream dependencies")); });

      await waitFor(() => {
        expect(screen.getByText("Upstream Dependencies")).toBeInTheDocument();
      });
    });

    it("shows the empty state when no upstream dependencies exist", async () => {
      mockFetchUpstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View upstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View upstream dependencies")); });

      await waitFor(() => {
        expect(screen.getByText(/no upstream dependencies found/i)).toBeInTheDocument();
      });
    });

    it("shows an error when fetchUpstream throws", async () => {
      mockFetchUpstream.mockRejectedValue(new Error("Upstream fetch failed"));

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View upstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View upstream dependencies")); });

      await waitFor(() => {
        expect(screen.getByText("Upstream fetch failed")).toBeInTheDocument();
      });
    });
  });

  // ─── Application type rendering ────────────────────────────────────────────
  describe("application type rendering", () => {
    it("renders 'oneops' type applications correctly", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ applicationType: "oneops" })]);

      render(<ApplicationsView />);
      await waitFor(() => {
        const table = screen.getByRole("table");
        expect(table).toBeInTheDocument();
      });
    });

    it("renders 'pageflow' type applications correctly", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ applicationType: "pageflow" })]);

      render(<ApplicationsView />);
      await waitFor(() => {
        const table = screen.getByRole("table");
        expect(table).toBeInTheDocument();
      });
    });

    it("shows oneOpsAssembly in namespace column for oneops apps", async () => {
      mockFetchAll.mockResolvedValue([
        makeApp({ applicationType: "oneops", oneOpsAssembly: "my-assembly" }),
      ]);

      render(<ApplicationsView />);
      await waitFor(() => {
        expect(screen.getByText("my-assembly")).toBeInTheDocument();
      });
    });

    it("shows oneOpsPlatform in appName column for oneops apps", async () => {
      mockFetchAll.mockResolvedValue([
        makeApp({ applicationType: "oneops", oneOpsPlatform: "my-platform" }),
      ]);

      render(<ApplicationsView />);
      await waitFor(() => {
        expect(screen.getByText("my-platform")).toBeInTheDocument();
      });
    });
  });

  // ─── Dependency modal expand / shrink ────────────────────────────────────────
  describe("dependency modal expand/shrink", () => {
    it("expands the downstream modal when Expand button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => screen.getByTitle("Expand"));
      fireEvent.click(screen.getByTitle("Expand"));

      await waitFor(() => {
        expect(screen.getByTitle("Shrink")).toBeInTheDocument();
      });
    });

    it("shrinks the downstream modal when Shrink button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      act(() => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => screen.getByTitle("Expand"));
      fireEvent.click(screen.getByTitle("Expand"));

      await waitFor(() => screen.getByTitle("Shrink"));
      fireEvent.click(screen.getByTitle("Shrink"));

      await waitFor(() => {
        expect(screen.getByTitle("Expand")).toBeInTheDocument();
      });
    });
  });

  // ─── handleAlerts ─────────────────────────────────────────────────────────────
  describe("handleAlerts", () => {
    it("opens the AlertsSidebar when the Alerts button is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View active alerts"));

      fireEvent.click(screen.getByTitle("View active alerts"));

      await waitFor(() => {
        expect(screen.getByTestId("alerts-sidebar")).toBeInTheDocument();
      });
    });

    it("shows the AlertsSidebar for the correct app (sidebar is visible)", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ name: "alerts-test-svc" })]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View active alerts"));

      fireEvent.click(screen.getByTitle("View active alerts"));

      // The mock AlertsSidebar renders when isOpen is true
      await waitFor(() => {
        expect(screen.getByTestId("alerts-sidebar")).toBeInTheDocument();
      });
    });

    it("closes the AlertsSidebar when Close Alerts is clicked", async () => {
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View active alerts"));
      fireEvent.click(screen.getByTitle("View active alerts"));

      await waitFor(() => screen.getByTestId("alerts-sidebar"));
      fireEvent.click(screen.getByRole("button", { name: /close alerts/i }));

      await waitFor(() => {
        expect(screen.queryByTestId("alerts-sidebar")).not.toBeInTheDocument();
      });
    });

    it("opens a new AlertsSidebar for a different row when clicked again", async () => {
      mockFetchAll.mockResolvedValue([
        makeApp({ id: 1, namespace: "svc-a-ns" }),
        makeApp({ id: 2, name: "svc-b", namespace: "svc-b-ns" }),
      ]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByText("svc-a-ns"));

      // There are two Alerts buttons now
      const alertsBtns = screen.getAllByTitle("View active alerts");
      expect(alertsBtns).toHaveLength(2);

      fireEvent.click(alertsBtns[0]);
      await waitFor(() => screen.getByTestId("alerts-sidebar"));

      // Close and reopen for the second app
      fireEvent.click(screen.getByRole("button", { name: /close alerts/i }));
      await waitFor(() => expect(screen.queryByTestId("alerts-sidebar")).not.toBeInTheDocument());

      fireEvent.click(alertsBtns[1]);
      await waitFor(() => {
        expect(screen.getByTestId("alerts-sidebar")).toBeInTheDocument();
      });
    });
  });

  // ─── _renderCellContent — column rendering branches ──────────────────────────
  describe("_renderCellContent column rendering", () => {
    it("renders namespace value for wcnp app", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ namespace: "my-wcnp-ns" })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("my-wcnp-ns")).toBeInTheDocument());
    });

    it("renders oneOpsAssembly in the namespace column for oneops apps", async () => {
      mockFetchAll.mockResolvedValue([
        makeApp({ applicationType: "oneops", oneOpsAssembly: "my-assembly-cell" }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("my-assembly-cell")).toBeInTheDocument());
    });

    it("renders appName value for wcnp app", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ appName: "my-wcnp-appname" })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("my-wcnp-appname")).toBeInTheDocument());
    });

    it("renders oneOpsPlatform in the appName column for oneops apps", async () => {
      mockFetchAll.mockResolvedValue([
        makeApp({ applicationType: "oneops", oneOpsPlatform: "my-platform-cell" }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("my-platform-cell")).toBeInTheDocument());
    });

    it("renders tenant badge in the table", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ tenant: "ecom" })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("ecom")).toBeInTheDocument());
    });

    it("renders tier value in the tier column", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ tier: "T3" })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("T3")).toBeInTheDocument());
    });

    it("renders cluster value in the cluster column", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ cluster: "eus2-prod-cluster" })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("eus2-prod-cluster")).toBeInTheDocument());
    });

    it("renders slack channel with '#' prefix in the table", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ slackChannels: ["platform-sre"] })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("#platform-sre")).toBeInTheDocument());
    });

    it("renders xmatters group value in the table", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ xmattersGroups: ["sre-oncall"] })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("sre-oncall")).toBeInTheDocument());
    });

    it("renders email address in the table", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ emails: ["sre@example.com"] })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("sre@example.com")).toBeInTheDocument());
    });

    it("renders 'Yes' certified badge for certified apps", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ certified: true })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("Yes")).toBeInTheDocument());
    });

    it("renders 'No' certified badge for uncertified apps", async () => {
      mockFetchAll.mockResolvedValue([makeApp({ certified: false })]);
      render(<ApplicationsView />);
      await waitFor(() => expect(screen.getByText("No")).toBeInTheDocument());
    });
  });
});
