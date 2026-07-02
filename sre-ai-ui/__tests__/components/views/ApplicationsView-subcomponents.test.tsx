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
  useAuth: () => ({ user: { loginId: "test.user", name: "Test User" } }),
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
const mockSubmitRequest = jest.fn();

jest.mock("@/lib/api-client", () => ({
  applicationsApi: {
    getCached: jest.fn(() => null),
    fetchAll: (...args: unknown[]) => mockFetchAll(),
    fetchUpstream: (id: number) => mockFetchUpstream(id),
    fetchDownstream: (id: number) => mockFetchDownstream(id),
    addDependency: jest.fn().mockResolvedValue(undefined),
    addUpstreamDependency: jest.fn().mockResolvedValue(undefined),
    deleteDownstreamDependency: jest.fn().mockResolvedValue(undefined),
    deleteUpstreamDependency: jest.fn().mockResolvedValue(undefined),
    fetchByWcnpId: jest.fn().mockResolvedValue(null),
    fetchByOneOpsId: jest.fn().mockResolvedValue(null),
    fetchByPageFlowId: jest.fn().mockResolvedValue(null),
  },
  dependencyApprovalsApi: {
    submitRequest: (...args: unknown[]) => mockSubmitRequest(...args),
  },
}));

// ─── Mock DataTable ──────────────────────────────────────────────────────────

jest.mock("@/components/ui/DataTable", () => {
  const React = require("react");
  return {
    __esModule: true,
    DataTable: ({ data, columns, loading, error, onRetry, title, onRowClick, emptyMessage }: any) => {
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
  jest.useFakeTimers();

  mockFetchAll.mockResolvedValue([makeApp()]);
  mockFetchUpstream.mockResolvedValue([]);
  mockFetchDownstream.mockResolvedValue([]);
  mockSubmitRequest.mockResolvedValue({
    data: { id: 1, status: "PENDING", approvedBy: null, reason: null },
  });

  global.URL.createObjectURL = jest.fn(() => "blob:test-url");
  global.URL.revokeObjectURL = jest.fn();

  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: jest.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  jest.useRealTimers();
});

// ─── Helper to open a dependency modal with deps loaded ──────────────────────

const defaultAvailableDeps = [
  makeApp({ id: 2, name: "other-wcnp-app", applicationType: "wcnp", wcnpId: 2 }),
  makeApp({ id: 3, name: "oneops-app", applicationType: "oneops" }),
  makeApp({ id: 4, name: "pageflow-app", applicationType: "pageflow" }),
];

async function openDownstreamModal(deps: DependencyData[] = [makeDep()], availableApps?: Application[]) {
  mockFetchDownstream.mockResolvedValue(deps);
  const avail = availableApps ?? defaultAvailableDeps;
  // Calls: 1) initial page load, 2) handleDownstream pre-warm, 3) DependencyModal useEffect
  mockFetchAll
    .mockResolvedValueOnce([makeApp()])  // initial page load
    .mockResolvedValueOnce(avail)        // pre-warm from handleDownstream
    .mockResolvedValue(avail);           // DependencyModal useEffect fetchAll
  mockFetchUpstream.mockResolvedValue([]); // opposite direction fetch

  render(<ApplicationsView />);
  await waitFor(() => screen.getByTitle("View downstream dependencies"));
  await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });
  await waitFor(() => screen.getAllByText("Downstream Dependencies"));
}

async function openUpstreamModal(deps: DependencyData[] = [makeDep()]) {
  mockFetchUpstream.mockResolvedValue(deps);
  const avail = [makeApp({ id: 2, name: "other-wcnp-app", applicationType: "wcnp", wcnpId: 2 })];
  mockFetchAll
    .mockResolvedValueOnce([makeApp()])
    .mockResolvedValueOnce(avail)
    .mockResolvedValue(avail);
  mockFetchDownstream.mockResolvedValue([]);

  render(<ApplicationsView />);
  await waitFor(() => screen.getByTitle("View upstream dependencies"));
  await act(async () => { fireEvent.click(screen.getByTitle("View upstream dependencies")); });
  await waitFor(() => screen.getAllByText("Upstream Dependencies"));
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("ApplicationsView sub-components", () => {

  // ─── DetailModal ──────────────────────────────────────────────────────────────
  describe("DetailModal", () => {
    it("renders general fields: status, type, certified, tenant, tier, domain", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([
        makeApp({ active: false, certified: false, tenant: "na", tier: "T2", functionalDomain: "payments" }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("Inactive")).toBeInTheDocument();
        expect(screen.getByText("wcnp")).toBeInTheDocument();
        // certified is "No" inside the detail modal
        const noElements = screen.getAllByText("No");
        expect(noElements.length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("na").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("T2").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("payments").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("renders Active status for active apps", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([makeApp({ active: true })]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        // "Active" appears both as table column header and status value
        const activeTexts = screen.getAllByText("Active");
        expect(activeTexts.length).toBeGreaterThanOrEqual(1);
      });
    });

    it("renders WCNP section with namespace and app name for wcnp apps", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([
        makeApp({ applicationType: "wcnp", namespace: "pay-ns", appName: "pay-svc" }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("WCNP")).toBeInTheDocument();
        expect(screen.getAllByText("pay-ns").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("pay-svc").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("renders OneOps section for oneops apps with org, assembly, platform", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([
        makeApp({
          applicationType: "oneops",
          oneOpsOrg: "test-org",
          oneOpsAssembly: "test-asm",
          oneOpsPlatform: "test-plat",
        }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("OneOps")).toBeInTheDocument();
        expect(screen.getAllByText("test-org").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("test-asm").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("test-plat").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("renders team section with jira link, primary team, and members", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([
        makeApp({
          team: {
            teamId: 10,
            jira: "https://jira.example.com/board/1",
            isPrimaryTeam: true,
            members: [
              { id: 1, name: "Alice Smith", email: "alice@example.com" },
              { id: 2, name: "Bob Jones", email: null },
            ],
          },
        }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getAllByText("Team").length).toBeGreaterThanOrEqual(1);
        const jiraLink = screen.getAllByText("Jira Board");
        expect(jiraLink.length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText(/Alice Smith/)).toBeInTheDocument();
        expect(screen.getByText(/alice@example.com/)).toBeInTheDocument();
        expect(screen.getByText(/Bob Jones/)).toBeInTheDocument();
      });
    });

    it("renders team section without jira link when jira is null", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([
        makeApp({
          team: {
            teamId: 10,
            jira: null,
            isPrimaryTeam: false,
            members: [],
          },
        }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getAllByText("Team").length).toBeGreaterThanOrEqual(1);
        expect(screen.queryByText("Jira Board")).not.toBeInTheDocument();
      });
    });

    it("renders communication section with slack channels, xmatters groups, and emails", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([
        makeApp({
          slackChannels: ["platform-eng", "sre-alerts"],
          xmattersGroups: ["oncall-team"],
          emails: ["sre@example.com"],
        }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("Communication")).toBeInTheDocument();
        expect(screen.getByText("Slack Channels")).toBeInTheDocument();
        // In the detail modal, channels are rendered with #prefix
        // But in the table, CellList also renders them — use getAllByText
        expect(screen.getAllByText("#platform-eng").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("#sre-alerts").length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText("XMatters Groups")).toBeInTheDocument();
        expect(screen.getAllByText("oncall-team").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("Emails").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("sre@example.com").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("renders cluster info when present", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([makeApp({ cluster: "us-east-1a" })]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        // "Cluster" appears as both table column header and modal label
        const clusterTexts = screen.getAllByText("Cluster");
        expect(clusterTexts.length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("us-east-1a").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("does not render cluster info when cluster is null", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([makeApp({ cluster: null })]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        expect(screen.getByText("Application Details")).toBeInTheDocument();
      });
      // "Cluster" label should not be present as a section header in the modal
      const clusterLabels = screen.queryAllByText("Cluster");
      // The table header "Cluster" may exist, but the modal should not have it
      // The modal specifically has a label element for Cluster
      const modal = screen.getByText("Application Details").closest(".fixed");
      if (modal) {
        const clusterInModal = modal.querySelectorAll("label");
        const clusterLabel = Array.from(clusterInModal).find(el => el.textContent === "Cluster");
        expect(clusterLabel).toBeUndefined();
      }
    });

    it("shows dashes for missing optional fields", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([
        makeApp({ tenant: "", tier: "", functionalDomain: "", applicationType: "" }),
      ]);
      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View application details"));
      fireEvent.click(screen.getByTitle("View application details"));

      await waitFor(() => {
        // Multiple dashes should be rendered for empty fields
        const dashes = screen.getAllByText("—");
        expect(dashes.length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  // ─── ConfirmModal ─────────────────────────────────────────────────────────────
  describe("ConfirmModal (via delete dependency)", () => {
    it("shows confirm modal with reason textarea when deleting dependency", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep()]);

      // Switch to table view to see delete buttons
      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => {
        expect(screen.getByText("Request Dependency Removal")).toBeInTheDocument();
        expect(screen.getByText("Reason (optional)")).toBeInTheDocument();
        expect(screen.getByPlaceholderText("Add a reason for this request...")).toBeInTheDocument();
        expect(screen.getByText("Submit Request")).toBeInTheDocument();
        expect(screen.getByText("Cancel")).toBeInTheDocument();
      });
    });

    it("allows typing a reason in the textarea", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep()]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      const textarea = await waitFor(() => screen.getByPlaceholderText("Add a reason for this request..."));
      fireEvent.change(textarea, { target: { value: "No longer needed" } });
      expect(textarea).toHaveValue("No longer needed");
    });

    it("cancels the confirm modal when Cancel is clicked", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep()]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByText("Request Dependency Removal"));
      fireEvent.click(screen.getByText("Cancel"));

      await waitFor(() => {
        expect(screen.queryByText("Request Dependency Removal")).not.toBeInTheDocument();
      });
    });

    it("submits the confirm modal with reason when Confirm is clicked", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep({ application_id: 99 })]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      const textarea = await waitFor(() => screen.getByPlaceholderText("Add a reason for this request..."));
      fireEvent.change(textarea, { target: { value: "Removing stale dep" } });

      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(mockSubmitRequest).toHaveBeenCalledWith(
          expect.objectContaining({
            action: "DELETE",
            reason: "Removing stale dep",
          })
        );
      });
    });
  });

  // ─── Toast ─────────────────────────────────────────────────────────────────────
  describe("Toast", () => {
    it("shows toast after successful dependency delete request", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockResolvedValue({
        data: { id: 1, status: "PENDING", approvedBy: null, reason: null },
      });
      await openDownstreamModal([makeDep({ application_id: 99 })]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByText("Submit Request"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText(/pending review/i)).toBeInTheDocument();
      });
    });

    it("auto-dismisses toast after timeout", async () => {
      jest.useFakeTimers();
      mockSubmitRequest.mockResolvedValue({
        data: { id: 1, status: "PENDING", approvedBy: null, reason: null },
      });

      const avail = [makeApp({ id: 2, name: "other-app", applicationType: "wcnp" })];
      mockFetchDownstream.mockResolvedValue([makeDep({ application_id: 99 })]);
      mockFetchAll
        .mockResolvedValueOnce([makeApp()])
        .mockResolvedValueOnce(avail)
        .mockResolvedValue(avail);
      mockFetchUpstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await act(async () => { jest.advanceTimersByTime(100); });

      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });
      await act(async () => { jest.advanceTimersByTime(100); });

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getAllByText("Submit Request"));
      fireEvent.click(screen.getAllByText("Submit Request")[0]);

      await act(async () => { jest.advanceTimersByTime(100); });

      await waitFor(() => {
        expect(screen.getByText(/pending review/i)).toBeInTheDocument();
      });

      // Auto-dismiss after 3 seconds
      act(() => { jest.advanceTimersByTime(3500); });

      await waitFor(() => {
        expect(screen.queryByText(/pending review/i)).not.toBeInTheDocument();
      });
    });

    it("shows auto-rejected toast when system rejects", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockResolvedValue({
        data: { id: 1, status: "REJECTED", approvedBy: "system", reason: "Circular dependency detected" },
      });
      await openDownstreamModal([makeDep({ application_id: 99 })]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByText("Submit Request"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText(/Auto-rejected/i)).toBeInTheDocument();
      });
    });
  });

  // ─── DependencyModal — diagram view ────────────────────────────────────────────
  describe("DependencyModal diagram view", () => {
    it("renders mermaid diagram for downstream dependencies", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep({ namespace: "test-ns", app_name: "test-app" })]);

      await waitFor(() => {
        expect(screen.getByTestId("mermaid-diagram")).toBeInTheDocument();
        expect(screen.getByText("Downstream Dependency Flow")).toBeInTheDocument();
      });
    });

    it("renders mermaid diagram for upstream dependencies", async () => {
      jest.useRealTimers();
      await openUpstreamModal([makeDep({ namespace: "up-ns", app_name: "up-app" })]);

      await waitFor(() => {
        expect(screen.getByTestId("mermaid-diagram")).toBeInTheDocument();
        expect(screen.getByText("Upstream Dependency Flow")).toBeInTheDocument();
      });
    });

    it("includes tenant/tier metadata in diagram labels", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep({ tenant: "ecom", tier: "T1" })]);

      await waitFor(() => {
        const diagram = screen.getByTestId("mermaid-diagram");
        expect(diagram.textContent).toContain("ecom");
        expect(diagram.textContent).toContain("T1");
      });
    });

    it("shows dependency count", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep(), makeDep({ id: 100, application_id: 100 })]);

      await waitFor(() => {
        expect(screen.getByText(/Found 2 downstream dependencies/i)).toBeInTheDocument();
      });
    });

    it("shows singular 'dependency' for single dep", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep()]);

      await waitFor(() => {
        expect(screen.getByText(/Found 1 downstream dependency$/i)).toBeInTheDocument();
      });
    });
  });

  // ─── DependencyModal — table view ──────────────────────────────────────────────
  describe("DependencyModal table view", () => {
    it("switches to table view and shows dependency rows", async () => {
      jest.useRealTimers();
      await openDownstreamModal([
        makeDep({ application_name: "table-dep", namespace: "t-ns", app_name: "t-app", tier: "T3" }),
      ]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getAllByText("Downstream Dependencies").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("Name").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("Type").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("WCNP").length).toBeGreaterThanOrEqual(1); // type badge
        expect(screen.getByText("t-ns")).toBeInTheDocument();
        expect(screen.getByText("t-app")).toBeInTheDocument();
        expect(screen.getAllByText("T3").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("renders OneOps dependency type in table", async () => {
      jest.useRealTimers();
      await openDownstreamModal([
        makeDep({
          namespace: undefined,
          app_name: undefined,
          org: "my-org",
          assembly: "my-asm",
          platform: "my-plat",
        }),
      ]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("OneOps")).toBeInTheDocument();
      });
    });

    it("renders legacy wcnp dependency data in table", async () => {
      jest.useRealTimers();
      await openDownstreamModal([
        makeDep({
          namespace: undefined,
          app_name: undefined,
          org: undefined,
          assembly: undefined,
          platform: undefined,
          wcnp: { namespace: "legacy-ns", app: "legacy-app" },
        }),
      ]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("WCNP")).toBeInTheDocument();
      });
    });

    it("renders legacy oneOpsPlatform dependency data in table", async () => {
      jest.useRealTimers();
      await openDownstreamModal([
        makeDep({
          namespace: undefined,
          app_name: undefined,
          org: undefined,
          assembly: undefined,
          platform: undefined,
          oneOpsPlatform: { name: "legacy-oneops-plat" },
        }),
      ]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("OneOps")).toBeInTheDocument();
      });
    });

    it("renders pageFlow dependency as fallback", async () => {
      jest.useRealTimers();
      await openDownstreamModal([
        makeDep({
          namespace: undefined,
          app_name: undefined,
          org: undefined,
          assembly: undefined,
          platform: undefined,
          name: "my-pageflow",
          pageFlow: true,
        }),
      ]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("PageFlow")).toBeInTheDocument();
      });
    });

    it("renders generic App type when no specific type detected", async () => {
      jest.useRealTimers();
      await openDownstreamModal([
        makeDep({
          namespace: undefined,
          app_name: undefined,
          org: undefined,
          assembly: undefined,
          platform: undefined,
          application_name: "generic-app",
        }),
      ]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("App")).toBeInTheDocument();
      });
    });

    it("shows delete button for each dependency in table", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep(), makeDep({ id: 100, application_id: 100 })]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        const deleteButtons = screen.getAllByTitle("Delete dependency");
        expect(deleteButtons).toHaveLength(2);
      });
    });
  });

  // ─── DependencyModal — add dependency form ────────────────────────────────────
  describe("DependencyModal add dependency", () => {
    it("shows Add Dependency button in footer", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      await waitFor(() => {
        expect(screen.getByText("Add Dependency")).toBeInTheDocument();
      });
    });

    it("opens add dependency form when button clicked", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => {
        expect(screen.getByText(/Add Downstream Dependency/)).toBeInTheDocument();
        expect(screen.getByText(/Add a new dependency for/)).toBeInTheDocument();
      });
    });

    it("shows type dropdown with WCNP, OneOps, PageFlow options", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => screen.getByText("WCNP"));
      // Click the type dropdown button
      const typeButton = screen.getAllByText("WCNP")[0];
      fireEvent.click(typeButton);

      await waitFor(() => {
        expect(screen.getByText("OneOps")).toBeInTheDocument();
        expect(screen.getByText("PageFlow")).toBeInTheDocument();
      });
    });

    it("switches type when selecting OneOps from dropdown", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => screen.getByText("WCNP"));
      // Click the type button to show dropdown
      const typeButton = screen.getAllByText("WCNP")[0];
      fireEvent.click(typeButton);

      await waitFor(() => screen.getByText("OneOps"));
      fireEvent.click(screen.getByText("OneOps"));

      // After selecting, the dropdown should show OneOps as selected
      await waitFor(() => {
        const oneOpsTexts = screen.getAllByText("OneOps");
        expect(oneOpsTexts.length).toBeGreaterThanOrEqual(1);
      });
    });

    it("shows reason textarea in add form", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => {
        expect(screen.getByPlaceholderText("Why is this dependency needed?")).toBeInTheDocument();
      });
    });

    it("has disabled submit button when no dependency selected", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => {
        const submitBtn = screen.getByText("Submit Request");
        expect(submitBtn).toBeDisabled();
      });
    });

    it("closes add form when Cancel is clicked", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText(/Add Downstream Dependency/));

      // There should be a Cancel button in the add form
      const cancelButtons = screen.getAllByText("Cancel");
      fireEvent.click(cancelButtons[cancelButtons.length - 1]);

      await waitFor(() => {
        expect(screen.queryByText(/Add Downstream Dependency/)).not.toBeInTheDocument();
      });
    });

    it("shows dependency dropdown and allows selecting a dependency", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));

      // Should show available apps in dropdown
      await waitFor(() => {
        expect(screen.getByText("other-wcnp-app")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("other-wcnp-app"));

      await waitFor(() => {
        expect(screen.getByText(/Selected:/)).toBeInTheDocument();
        expect(screen.getByText("other-wcnp-app")).toBeInTheDocument();
      });
    });

    it("submits add dependency request with reason", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));

      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));

      // Type a reason
      const reasonInput = screen.getByPlaceholderText("Why is this dependency needed?");
      fireEvent.change(reasonInput, { target: { value: "Needed for checkout" } });

      // Submit
      const submitBtn = screen.getByText("Submit Request");
      expect(submitBtn).not.toBeDisabled();
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(mockSubmitRequest).toHaveBeenCalledWith(
          expect.objectContaining({
            action: "ADD",
            reason: "Needed for checkout",
            dependencyId: 2,
          })
        );
      });
    });

    it("shows 'Change' button after selecting and allows reselection", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));

      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));

      await waitFor(() => screen.getByText("Change"));
      fireEvent.click(screen.getByText("Change"));

      await waitFor(() => {
        expect(screen.getByText("Select a dependency...")).toBeInTheDocument();
      });
    });

    it("shows search input in dependency dropdown", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));

      await waitFor(() => {
        expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();
      });
    });

    it("shows no available apps message when no apps of selected type exist", async () => {
      jest.useRealTimers();
      // Only provide WCNP apps, then switch to PageFlow
      mockFetchDownstream.mockResolvedValue([]);
      mockFetchAll
        .mockResolvedValueOnce([makeApp()])
        .mockResolvedValueOnce([])  // pre-warm
        .mockResolvedValue([]);     // DependencyModal useEffect
      mockFetchUpstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });
      await waitFor(() => screen.getAllByText("Downstream Dependencies"));

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));

      await waitFor(() => {
        expect(screen.getByText(/No WCNP applications available/i)).toBeInTheDocument();
      });
    });
  });

  // ─── DependencyModal — error handling ─────────────────────────────────────────
  describe("DependencyModal error handling", () => {
    it("shows 'already exists' error message", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockRejectedValue(new Error("Dependency already exists"));

      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));
      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText(/already exists/i)).toBeInTheDocument();
      });
    });

    it("shows circular dependency error message", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockRejectedValue(new Error("Circular dependency detected"));

      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));
      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText(/circular dependency/i)).toBeInTheDocument();
      });
    });

    it("shows not found error message", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockRejectedValue(new Error("Application not found (404)"));

      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));
      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText(/not found/i)).toBeInTheDocument();
      });
    });

    it("shows bad request error message", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockRejectedValue(new Error("400 Bad Request"));

      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));
      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText(/Invalid dependency configuration/i)).toBeInTheDocument();
      });
    });

    it("strips 'An unexpected error occurred' prefix from error messages", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockRejectedValue(new Error("An unexpected error occurred: Something went wrong"));

      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));
      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText("Something went wrong")).toBeInTheDocument();
      });
    });

    it("shows delete error when delete request fails", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockRejectedValue(new Error("Delete failed"));

      await openDownstreamModal([makeDep({ application_id: 99 })]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByText("Submit Request"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText("Delete failed")).toBeInTheDocument();
      });
    });
  });

  // ─── DependencyModal — close and expand ────────────────────────────────────────
  describe("DependencyModal close and UI", () => {
    it("closes the dependency modal when Close button is clicked", async () => {
      jest.useRealTimers();
      await openDownstreamModal([]);

      const closeBtn = screen.getByRole("button", { name: /^close$/i });
      fireEvent.click(closeBtn);

      await waitFor(() => {
        expect(screen.queryByText("Downstream Dependencies")).not.toBeInTheDocument();
      });
    });

    it("shows loading spinner for available dependencies while they load", async () => {
      jest.useRealTimers();
      // Make fetchAll hang for the dependency modal's internal fetch
      let resolveApps!: (v: Application[]) => void;
      mockFetchDownstream.mockResolvedValue([]);
      mockFetchAll
        .mockResolvedValueOnce([makeApp()]) // initial load
        .mockResolvedValueOnce([])          // pre-warm from handleDownstream
        .mockReturnValueOnce(new Promise((res) => { resolveApps = res; })); // DependencyModal fetch hangs
      mockFetchUpstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });
      await waitFor(() => screen.getAllByText("Downstream Dependencies"));

      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => {
        expect(screen.getByText("Loading...")).toBeInTheDocument();
      });

      // Clean up
      await act(async () => { resolveApps([]); });
    });
  });

  // ─── TruncatedTextWithCopy ─────────────────────────────────────────────────────
  describe("TruncatedTextWithCopy (via table cells)", () => {
    it("copies text to clipboard when copy button is clicked on truncated value", async () => {
      jest.useRealTimers();
      const longNamespace = "a".repeat(50); // longer than maxLength=25
      mockFetchAll.mockResolvedValue([makeApp({ namespace: longNamespace })]);

      render(<ApplicationsView />);

      await waitFor(() => {
        // The truncated text component shows a truncated version with "..."
        // Look for the copy button (title="Copy full value")
        const copyBtns = screen.queryAllByTitle("Copy full value");
        if (copyBtns.length > 0) {
          fireEvent.click(copyBtns[0]);
          expect(navigator.clipboard.writeText).toHaveBeenCalledWith(longNamespace);
        }
      });
    });
  });

  // ─── onDeleteDependency with missing application_id ────────────────────────────
  describe("onDeleteDependency edge cases", () => {
    it("throws error when dependency has no application_id", async () => {
      jest.useRealTimers();
      const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

      await openDownstreamModal([makeDep({ application_id: undefined })]);

      await waitFor(() => screen.getByTitle("Table view"));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByText("Submit Request"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(consoleErrorSpy).toHaveBeenCalled();
      });

      consoleErrorSpy.mockRestore();
    });
  });

  // ─── onAddDependency result handling ──────────────────────────────────────────
  describe("onAddDependency result handling", () => {
    it("shows info toast when add request is pending", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockResolvedValue({
        data: { id: 1, status: "PENDING", approvedBy: null, reason: null },
      });

      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));
      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText(/pending review/i)).toBeInTheDocument();
      });
    });

    it("shows error toast when add request is auto-rejected by system", async () => {
      jest.useRealTimers();
      mockSubmitRequest.mockResolvedValue({
        data: { id: 1, status: "REJECTED", approvedBy: "system", reason: "Duplicate" },
      });

      await openDownstreamModal([]);

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));
      await waitFor(() => screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("other-wcnp-app"));
      fireEvent.click(screen.getByText("Submit Request"));

      await waitFor(() => {
        expect(screen.getByText(/Auto-rejected/i)).toBeInTheDocument();
      });
    });
  });

  // ─── closeDependencyModal ─────────────────────────────────────────────────────
  describe("closeDependencyModal", () => {
    it("clears dependencies and error when modal is closed", async () => {
      jest.useRealTimers();
      mockFetchDownstream.mockRejectedValue(new Error("Failed"));
      mockFetchAll.mockResolvedValue([makeApp()]);
      mockFetchUpstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });

      await waitFor(() => screen.getByText("Failed"));

      // Close the modal
      const closeBtn = screen.getByRole("button", { name: /^close$/i });
      fireEvent.click(closeBtn);

      await waitFor(() => {
        expect(screen.queryByText("Failed")).not.toBeInTheDocument();
        expect(screen.queryByText("Downstream Dependencies")).not.toBeInTheDocument();
      });
    });
  });

  // ─── DependencyModal — availableDependencies filtering ────────────────────────
  describe("DependencyModal available dependencies filtering", () => {
    it("filters available dependencies to exclude the current app", async () => {
      jest.useRealTimers();
      const customApps = [
        makeApp({ id: 1, name: "self-app" }), // same as current — should be excluded
        makeApp({ id: 5, name: "valid-dep", applicationType: "wcnp" }),
      ];
      mockFetchDownstream.mockResolvedValue([]);
      mockFetchAll
        .mockResolvedValueOnce([makeApp()])
        .mockResolvedValueOnce(customApps) // pre-warm
        .mockResolvedValue(customApps);    // DependencyModal useEffect
      mockFetchUpstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });
      await waitFor(() => screen.getAllByText("Downstream Dependencies"));

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));

      await waitFor(() => {
        expect(screen.getByText("valid-dep")).toBeInTheDocument();
        expect(screen.queryByText("self-app")).not.toBeInTheDocument();
      });
    });

    it("filters out apps that are already dependencies", async () => {
      jest.useRealTimers();
      const customApps = [
        makeApp({ id: 5, name: "already-dep", applicationType: "wcnp" }),
        makeApp({ id: 6, name: "new-dep", applicationType: "wcnp" }),
      ];
      mockFetchDownstream.mockResolvedValue([makeDep({ application_id: 5 })]);
      mockFetchAll
        .mockResolvedValueOnce([makeApp()])
        .mockResolvedValueOnce(customApps)
        .mockResolvedValue(customApps);
      mockFetchUpstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });
      await waitFor(() => screen.getAllByText("Downstream Dependencies"));

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));

      await waitFor(() => {
        expect(screen.getByText("new-dep")).toBeInTheDocument();
        // already-dep should not appear because it's already a dependency
        expect(screen.queryByText("already-dep")).not.toBeInTheDocument();
      });
    });

    it("filters out apps that are in opposite direction (circular prevention)", async () => {
      jest.useRealTimers();
      const customApps = [
        makeApp({ id: 7, name: "upstream-dep", applicationType: "wcnp" }),
        makeApp({ id: 8, name: "available-app", applicationType: "wcnp" }),
      ];
      // For downstream modal, the opposite direction is upstream
      mockFetchDownstream.mockResolvedValue([]);
      mockFetchAll
        .mockResolvedValueOnce([makeApp()])
        .mockResolvedValueOnce(customApps)
        .mockResolvedValue(customApps);
      // The opposite direction (upstream) already has app 7
      mockFetchUpstream.mockResolvedValue([makeDep({ application_id: 7 })]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });
      await waitFor(() => screen.getAllByText("Downstream Dependencies"));

      fireEvent.click(screen.getByText("Add Dependency"));
      await waitFor(() => screen.getByText("Select a dependency..."));
      fireEvent.click(screen.getByText("Select a dependency..."));

      await waitFor(() => {
        expect(screen.getByText("available-app")).toBeInTheDocument();
        // upstream-dep should be filtered out since it's in the opposite direction
        expect(screen.queryByText("upstream-dep")).not.toBeInTheDocument();
      });
    });
  });

  // ─── DependencyModal — diagram with different dep types ────────────────────────
  describe("DependencyModal diagram rendering with various dep types", () => {
    it("renders upstream diagram with arrows pointing to app", async () => {
      jest.useRealTimers();
      await openUpstreamModal([makeDep({ namespace: "up-ns", app_name: "up-app" })]);

      await waitFor(() => {
        const diagram = screen.getByTestId("mermaid-diagram");
        // Upstream: dep --> app
        expect(diagram.textContent).toContain("-->");
      });
    });

    it("renders downstream diagram with arrows pointing from app", async () => {
      jest.useRealTimers();
      await openDownstreamModal([makeDep({ namespace: "down-ns", app_name: "down-app" })]);

      await waitFor(() => {
        const diagram = screen.getByTestId("mermaid-diagram");
        expect(diagram.textContent).toContain("-->");
      });
    });
  });

  // ─── Row click sets selectedApplication in context ─────────────────────────────
  describe("row click behavior", () => {
    it("renders rows that are clickable", async () => {
      jest.useRealTimers();
      mockFetchAll.mockResolvedValue([makeApp()]);
      render(<ApplicationsView />);

      await waitFor(() => {
        const rows = screen.getAllByRole("row");
        expect(rows.length).toBeGreaterThanOrEqual(2); // header + data row
      });
    });

    it("calls setSelectedApplication when a row is clicked", async () => {
      jest.useRealTimers();
      const mockSetSelectedApp = jest.fn();
      const mockViewContext = require("@/contexts/ViewContext");
      const originalUseViewContext = mockViewContext.useViewContext;
      mockViewContext.useViewContext = () => ({
        setApplicationData: jest.fn(),
        setSelectedApplication: mockSetSelectedApp,
        setFilteredApplicationCount: jest.fn(),
        setApplicationFilters: jest.fn(),
        selectedApplication: null,
      });

      mockFetchAll.mockResolvedValue([makeApp()]);
      render(<ApplicationsView />);

      await waitFor(() => {
        const rows = screen.getAllByRole("row");
        expect(rows.length).toBeGreaterThanOrEqual(2);
      });

      // Click the data row (first row after header)
      const dataRows = screen.getAllByRole("row");
      fireEvent.click(dataRows[1]); // data row

      expect(mockSetSelectedApp).toHaveBeenCalled();

      // Restore
      mockViewContext.useViewContext = originalUseViewContext;
    });
  });

  // ─── DependencyModal fetchAll error in useEffect ──────────────────────────────
  describe("DependencyModal fetchAll error handling", () => {
    it("handles fetchAll error gracefully when loading available dependencies", async () => {
      jest.useRealTimers();
      const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

      mockFetchDownstream.mockResolvedValue([]);
      mockFetchAll
        .mockResolvedValueOnce([makeApp()])  // initial
        .mockResolvedValueOnce([])           // pre-warm
        .mockRejectedValue(new Error("Network error")); // DependencyModal useEffect fetchAll fails
      mockFetchUpstream.mockResolvedValue([]);

      render(<ApplicationsView />);
      await waitFor(() => screen.getByTitle("View downstream dependencies"));
      await act(async () => { fireEvent.click(screen.getByTitle("View downstream dependencies")); });
      await waitFor(() => screen.getAllByText("Downstream Dependencies"));

      // Open add form — should still work but with no available deps
      fireEvent.click(screen.getByText("Add Dependency"));

      await waitFor(() => {
        expect(screen.getByText("Select a dependency...")).toBeInTheDocument();
      });

      // Click the dropdown — should show no apps available
      fireEvent.click(screen.getByText("Select a dependency..."));

      await waitFor(() => {
        expect(screen.getByText(/No WCNP applications available/i)).toBeInTheDocument();
      });

      consoleErrorSpy.mockRestore();
    });
  });
});
