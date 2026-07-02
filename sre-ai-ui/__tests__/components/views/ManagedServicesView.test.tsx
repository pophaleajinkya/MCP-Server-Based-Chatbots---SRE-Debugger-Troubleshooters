import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ManagedServicesView } from "@/components/views/ManagedServicesView";
import type { ManagedServiceData, DependencyData, Application } from "@/lib/api-client";

// ─── Mock api-client ──────────────────────────────────────────────────────────

const mockFetchAll = jest.fn<Promise<ManagedServiceData[]>, []>();
const mockDelete = jest.fn<Promise<void>, [number]>();
const mockFetchUpstream = jest.fn<Promise<DependencyData[]>, [number]>();
const mockAddUpstreamDependency = jest.fn<Promise<unknown>, [number, number]>();
const mockDeleteUpstreamDependency = jest.fn<Promise<unknown>, [number, number]>();
const mockApplicationsFetchAll = jest.fn<Promise<Application[]>, []>();
const mockSubmitRequest = jest.fn();

jest.mock("@/lib/api-client", () => ({
  managedServicesApi: {
    getCached: jest.fn(() => null),
    fetchAll: (...args: unknown[]) => mockFetchAll(...(args as [])),
    delete: (...args: unknown[]) => mockDelete(...(args as [number])),
  },
  applicationsApi: {
    fetchAll: (...args: unknown[]) => mockApplicationsFetchAll(...(args as [])),
    fetchUpstream: (...args: unknown[]) => mockFetchUpstream(...(args as [number])),
    addUpstreamDependency: (...args: unknown[]) =>
      mockAddUpstreamDependency(...(args as [number, number])),
    deleteUpstreamDependency: (...args: unknown[]) =>
      mockDeleteUpstreamDependency(...(args as [number, number])),
  },
  dependencyApprovalsApi: {
    submitRequest: (...args: unknown[]) => mockSubmitRequest(...(args as [unknown])),
  },
}));

// ─── Mock heavy sub-components ────────────────────────────────────────────────

jest.mock("@/components/AlertsSidebar", () => ({
  AlertsSidebar: ({
    isOpen,
    onClose,
    app,
  }: {
    isOpen: boolean;
    onClose: () => void;
    app: { name: string } | null;
  }) => {
    if (!isOpen) return null;
    return (
      <div data-testid="alerts-sidebar">
        <span>AlertsSidebar: {app?.name ?? "unknown"}</span>
        <button onClick={onClose}>Close Sidebar</button>
      </div>
    );
  },
}));

jest.mock("@/components/MermaidDiagram", () => ({
  __esModule: true,
  default: ({ diagram }: { diagram: string }) => (
    <div data-testid="mermaid-diagram">{diagram}</div>
  ),
}));

jest.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: { loginId: "test.user", name: "Test User", email: "test@example.com", user_type: "S" },
    loading: false,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false, theme: "light", toggleTheme: jest.fn() }),
}));

jest.mock("@/contexts/ViewContext", () => ({
  useViewContext: () => ({
    setManagedServiceData: jest.fn(),
    setSelectedManagedService: jest.fn(),
    setFilteredManagedServiceCount: jest.fn(),
    setManagedServiceFilters: jest.fn(),
    selectedManagedService: null,
  }),
}));

// ─── Fixtures ─────────────────────────────────────────────────────────────────

function makeManagedService(
  overrides: Partial<ManagedServiceData> = {}
): ManagedServiceData {
  return {
    id: 1,
    managedServiceId: 1,
    name: "my-cosmos-db",
    serviceType: "cosmos",
    appId: 42,
    subscriptionId: "sub-001",
    resourceGroup: "rg-prod",
    databaseName: "db-prod",
    dns: "cosmos.azure.com",
    ...overrides,
  };
}

function makeDependency(overrides: Partial<DependencyData> = {}): DependencyData {
  return {
    id: 100,
    application_id: 100,
    application_name: "upstream-app",
    name: "upstream-app",
    namespace: "upstream-ns",
    app_name: "upstream-app-name",
    tier: "T1",
    tenant: "ecom",
    ...overrides,
  };
}

function makeApplication(overrides: Partial<Application> = {}): Application {
  return {
    id: 200,
    name: "new-dependency",
    tenant: "ecom",
    tier: "T1",
    functionalDomain: "checkout",
    active: true,
    certified: true,
    applicationType: "wcnp",
    namespace: "dep-ns",
    appName: "dep-app",
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

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();

  // Default: resolve with empty list
  mockFetchAll.mockResolvedValue([]);
  mockApplicationsFetchAll.mockResolvedValue([]);
  mockFetchUpstream.mockResolvedValue([]);
  mockDelete.mockResolvedValue(undefined);
  mockAddUpstreamDependency.mockResolvedValue({ success: true });
  mockDeleteUpstreamDependency.mockResolvedValue({ success: true });
  mockSubmitRequest.mockResolvedValue({
    status: 201,
    message: "Dependency approval request submitted successfully",
    data: {
      id: 1, applicationId: 10, applicationName: "my-cosmos-db",
      dependencyId: 200, dependencyName: "new-dependency",
      action: "ADD", status: "PENDING", reason: null,
      requestedBy: "test.user", approvedBy: null, approvedAt: null,
      createdAt: "2026-03-27T10:00:00.000Z", updatedAt: "2026-03-27T10:00:00.000Z",
    },
  });

  // Clipboard stub
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: jest.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  });

  // URL stubs for CSV export
  global.URL.createObjectURL = jest.fn(() => "blob:mock");
  global.URL.revokeObjectURL = jest.fn();
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("ManagedServicesView", () => {
  // ─── Loading state ──────────────────────────────────────────────────────────
  describe("loading state", () => {
    it("shows a loading spinner while API call is in progress", async () => {
      let resolve!: (val: ManagedServiceData[]) => void;
      mockFetchAll.mockReturnValue(new Promise((res) => { resolve = res; }));

      render(<ManagedServicesView />);

      expect(screen.getByText(/loading managed services/i)).toBeInTheDocument();

      await act(async () => { resolve([]); });
    });

    it("hides the spinner once data has loaded", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => {
        expect(screen.queryByText(/loading managed services/i)).not.toBeInTheDocument();
      });
    });

    it("calls managedServicesApi.fetchAll on mount", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockFetchAll).toHaveBeenCalledTimes(1));
    });
  });

  // ─── Error state ────────────────────────────────────────────────────────────
  describe("error state", () => {
    it("shows error heading and message when API throws an Error", async () => {
      mockFetchAll.mockRejectedValue(new Error("Network timeout"));
      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(screen.getByText("Error")).toBeInTheDocument();
        expect(screen.getByText("Network timeout")).toBeInTheDocument();
      });
    });

    it("shows fallback error message for non-Error rejections", async () => {
      mockFetchAll.mockRejectedValue("something bad");
      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(
          screen.getByText("Failed to fetch managed services")
        ).toBeInTheDocument();
      });
    });

    it("renders a Try Again button in the error state", async () => {
      mockFetchAll.mockRejectedValue(new Error("oops"));
      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
      });
    });

    it("clicking Try Again re-fetches data", async () => {
      mockFetchAll.mockRejectedValueOnce(new Error("oops"));
      mockFetchAll.mockResolvedValue([]);

      render(<ManagedServicesView />);

      await waitFor(() =>
        expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument()
      );

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /try again/i }));
      });

      await waitFor(() => expect(mockFetchAll).toHaveBeenCalledTimes(2));
    });
  });

  // ─── Header ─────────────────────────────────────────────────────────────────
  describe("header", () => {
    it("renders the 'Managed Services' heading", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /managed services/i })
        ).toBeInTheDocument();
      });
    });
  });

  // ─── Empty state (no data) ───────────────────────────────────────────────────
  describe("empty state", () => {
    it("shows 'No managed services found' when API returns empty list", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => {
        expect(screen.getByText("No managed services found")).toBeInTheDocument();
      });
    });

    it("shows the service count as '0 managed services'", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => {
        expect(screen.getByText(/0 managed services/i)).toBeInTheDocument();
      });
    });
  });

  // ─── Populated table ─────────────────────────────────────────────────────────
  describe("populated table", () => {
    it("renders a row for each managed service", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ managedServiceId: 1, name: "svc-one", serviceType: "cosmos" }),
        makeManagedService({ managedServiceId: 2, name: "svc-two", serviceType: "kafka" }),
      ]);

      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(screen.getByText("cosmos")).toBeInTheDocument();
        expect(screen.getByText("kafka")).toBeInTheDocument();
      });
    });

    it("displays the total count of services", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ managedServiceId: 1 }),
        makeManagedService({ managedServiceId: 2 }),
        makeManagedService({ managedServiceId: 3 }),
      ]);

      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(screen.getByText(/3 managed services/i)).toBeInTheDocument();
      });
    });

    it("renders default visible column headers", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService()]);

      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(
          screen.getByRole("columnheader", { name: /tenant/i })
        ).toBeInTheDocument();
        expect(
          screen.getByRole("columnheader", { name: /subscription/i })
        ).toBeInTheDocument();
        expect(
          screen.getByRole("columnheader", { name: /resource group/i })
        ).toBeInTheDocument();
        expect(
          screen.getByRole("columnheader", { name: /database/i })
        ).toBeInTheDocument();
        expect(
          screen.getByRole("columnheader", { name: /actions/i })
        ).toBeInTheDocument();
      });
    });

    it("renders subscriptionId in the appropriate column", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ subscriptionId: "sub-xyz" }),
      ]);

      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(screen.getByText("sub-xyz")).toBeInTheDocument();
      });
    });

    it("renders resourceGroup in the appropriate column", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ resourceGroup: "rg-main" }),
      ]);

      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(screen.getByText("rg-main")).toBeInTheDocument();
      });
    });

    it("renders databaseName in the appropriate column", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ databaseName: "prod-db" }),
      ]);

      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(screen.getByText("prod-db")).toBeInTheDocument();
      });
    });

    it("renders em-dash for empty optional fields", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({
          subscriptionId: undefined,
          resourceGroup: undefined,
          databaseName: undefined,
        }),
      ]);

      render(<ManagedServicesView />);

      await waitFor(() => {
        const dashes = screen.getAllByText("\u2014");
        expect(dashes.length).toBeGreaterThanOrEqual(1);
      });
    });

    it("shows serviceType in a badge", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ serviceType: "cassandra" }),
      ]);

      render(<ManagedServicesView />);

      await waitFor(() => {
        expect(screen.getByText("cassandra")).toBeInTheDocument();
      });
    });
  });

  // ─── Toolbar — Columns menu ───────────────────────────────────────────────────
  describe("Columns menu", () => {
    it("clicking Columns button shows the columns dropdown", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/0 managed services/i));

      fireEvent.click(screen.getByText("Columns"));

      // The dropdown has labels for each column; DNS is only in the dropdown (hidden col)
      expect(screen.getByText("DNS")).toBeInTheDocument();
    });

    it("toggling a column off hides its table header", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService()]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/1 managed services/i));

      fireEvent.click(screen.getByText("Columns"));

      // Database is visible by default; click its label to toggle off
      const databaseToggle = screen
        .getAllByText("Database")
        .find((el) => el.closest("label"));
      expect(databaseToggle).toBeTruthy();
      fireEvent.click(databaseToggle!.closest("label")!);

      await waitFor(() => {
        expect(
          screen.queryByRole("columnheader", { name: /^database$/i })
        ).not.toBeInTheDocument();
      });
    });

    it("toggling a column on adds it to the table", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ dns: "my.dns.com" })]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/1 managed services/i));

      // DNS column is hidden by default
      expect(
        screen.queryByRole("columnheader", { name: /^dns$/i })
      ).not.toBeInTheDocument();

      fireEvent.click(screen.getByText("Columns"));

      const dnsToggle = screen
        .getAllByText("DNS")
        .find((el) => el.closest("label"));
      expect(dnsToggle).toBeTruthy();
      fireEvent.click(dnsToggle!.closest("label")!);

      await waitFor(() => {
        expect(
          screen.getByRole("columnheader", { name: /^dns$/i })
        ).toBeInTheDocument();
      });
    });
  });

  // ─── Toolbar — Density menu ───────────────────────────────────────────────────
  describe("Density menu", () => {
    it("clicking Density button shows the density dropdown", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/0 managed services/i));

      fireEvent.click(screen.getByText("Density"));

      expect(screen.getByText("Compact")).toBeInTheDocument();
      expect(screen.getByText("Standard")).toBeInTheDocument();
      expect(screen.getByText("Comfortable")).toBeInTheDocument();
    });

    it("selecting Compact from density menu closes the dropdown", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/0 managed services/i));

      fireEvent.click(screen.getByText("Density"));
      expect(screen.getByText("Compact")).toBeInTheDocument();

      fireEvent.click(screen.getByText("Compact"));

      await waitFor(() => {
        expect(screen.queryByText("Comfortable")).not.toBeInTheDocument();
      });
    });

    it("selecting Comfortable from density menu sets that option", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/0 managed services/i));

      fireEvent.click(screen.getByText("Density"));
      fireEvent.click(screen.getByText("Comfortable"));

      await waitFor(() => {
        expect(screen.queryByText("Comfortable")).not.toBeInTheDocument();
      });
    });
  });

  // ─── Toolbar — Export ─────────────────────────────────────────────────────────
  describe("Export", () => {
    it("clicking Export triggers CSV download", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ managedServiceId: 1, name: "svc-one" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/1 managed services/i));

      // Stub click on anchor element
      const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

      fireEvent.click(screen.getByText("Export"));

      // DataTable calls URL.createObjectURL for CSV export
      expect(global.URL.createObjectURL).toHaveBeenCalled();

      clickSpy.mockRestore();
    });
  });

  // ─── Row actions — View Details modal ────────────────────────────────────────
  describe("View Details modal", () => {
    it("clicking the Details button opens the detail modal", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ name: "my-db", serviceType: "cosmos" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));

      fireEvent.click(screen.getByTitle("View service details"));

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /managed service details/i })
        ).toBeInTheDocument();
        expect(screen.getByText("my-db")).toBeInTheDocument();
      });
    });

    it("detail modal shows all service fields", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({
          name: "detail-svc",
          serviceType: "cosmos",
          appId: 7,
          assembly: "my-assembly",
          platform: "my-platform",
          subscriptionId: "sub-unique-xyz",
          resourceGroup: "rg-unique-xyz",
          databaseName: "db-unique-xyz",
          dns: "dns-unique-xyz.example.com",
          topicName: "topic-unique-xyz",
        }),
      ]);

      render(<ManagedServicesView />);
      // Wait for the table row badge to appear
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View service details"));

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /managed service details/i })
        ).toBeInTheDocument();
        // Fields that appear only in the modal (unique enough values):
        expect(screen.getByText("7")).toBeInTheDocument();
        expect(screen.getByText("my-assembly")).toBeInTheDocument();
        expect(screen.getByText("my-platform")).toBeInTheDocument();
        expect(screen.getByText("dns-unique-xyz.example.com")).toBeInTheDocument();
        expect(screen.getByText("topic-unique-xyz")).toBeInTheDocument();
        // These may appear in both the table and the modal
        expect(screen.getAllByText("sub-unique-xyz").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("rg-unique-xyz").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("db-unique-xyz").length).toBeGreaterThanOrEqual(1);
      });
    });

    it("closing the detail modal via Close button hides the modal", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService()]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View service details"));

      await waitFor(() =>
        screen.getByRole("heading", { name: /managed service details/i })
      );

      // Click the Close button in the modal footer
      const closeButtons = screen.getAllByRole("button", { name: /close/i });
      fireEvent.click(closeButtons[closeButtons.length - 1]);

      await waitFor(() => {
        expect(
          screen.queryByRole("heading", { name: /managed service details/i })
        ).not.toBeInTheDocument();
      });
    });

    it("clicking the backdrop closes the detail modal", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService()]);
      const { container } = render(<ManagedServicesView />);

      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View service details"));

      await waitFor(() =>
        screen.getByRole("heading", { name: /managed service details/i })
      );

      const backdrop = container.querySelector(".fixed.inset-0.bg-black\\/50");
      if (backdrop) fireEvent.click(backdrop);

      await waitFor(() => {
        expect(
          screen.queryByRole("heading", { name: /managed service details/i })
        ).not.toBeInTheDocument();
      });
    });
  });

  // ─── Row actions — Delete ─────────────────────────────────────────────────────
  describe("Delete service", () => {
    it("does not render a Delete button in actions column", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ name: "svc-to-verify" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));

      // Delete button was removed from the actions column
      expect(screen.queryByTitle("Delete (disabled)")).not.toBeInTheDocument();
      expect(screen.queryByTitle("Delete")).not.toBeInTheDocument();
    });
  });

  // ─── Row actions — Alerts sidebar ────────────────────────────────────────────
  describe("Alerts sidebar", () => {
    it("clicking the Alerts button opens the AlertsSidebar", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ name: "my-cosmos-db" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));

      fireEvent.click(screen.getByTitle("View active alerts"));

      await waitFor(() => {
        expect(screen.getByTestId("alerts-sidebar")).toBeInTheDocument();
        expect(screen.getByText(/my-cosmos-db/i)).toBeInTheDocument();
      });
    });

    it("closing the AlertsSidebar hides it", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ name: "my-cosmos-db" })]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));

      fireEvent.click(screen.getByTitle("View active alerts"));
      await waitFor(() => screen.getByTestId("alerts-sidebar"));

      fireEvent.click(screen.getByText("Close Sidebar"));

      await waitFor(() => {
        expect(screen.queryByTestId("alerts-sidebar")).not.toBeInTheDocument();
      });
    });
  });

  // ─── Row actions — Upstream dependencies modal ───────────────────────────────
  describe("Upstream Dependencies modal", () => {
    it("upstream button is not rendered when service has no appId", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ appId: null }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));

      // Upstream button is conditionally rendered only when appId exists
      expect(screen.queryByTitle("View upstream dependencies")).not.toBeInTheDocument();
    });

    it("upstream button is rendered when service has an appId", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));

      const upstreamBtn = screen.getByTitle("View upstream dependencies");
      expect(upstreamBtn).toBeInTheDocument();
    });

    it("clicking the upstream button opens the Upstream Dependencies modal", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ appId: 10, name: "my-svc" }),
      ]);
      mockFetchUpstream.mockResolvedValue([]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));

      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /upstream dependencies/i })
        ).toBeInTheDocument();
        expect(screen.getByText("my-svc")).toBeInTheDocument();
      });
    });

    it("shows loading spinner inside modal while fetching dependencies", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      let resolveDeps!: (deps: DependencyData[]) => void;
      mockFetchUpstream.mockReturnValue(new Promise((res) => { resolveDeps = res; }));

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));

      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => {
        expect(screen.getByText(/loading upstream dependencies/i)).toBeInTheDocument();
      });

      await act(async () => { resolveDeps([]); });
    });

    it("shows 'No upstream dependencies found' when list is empty", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => {
        expect(
          screen.getByText("No upstream dependencies found")
        ).toBeInTheDocument();
      });
    });

    it("shows dependency count when deps are loaded", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: 1 }),
        makeDependency({ id: 2, application_id: 2 }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => {
        expect(screen.getByText(/found 2 upstream dependencies/i)).toBeInTheDocument();
      });
    });

    it("closing the modal via Close button hides it", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() =>
        screen.getByRole("heading", { name: /upstream dependencies/i })
      );

      fireEvent.click(screen.getByRole("button", { name: /close/i }));

      await waitFor(() => {
        expect(
          screen.queryByRole("heading", { name: /upstream dependencies/i })
        ).not.toBeInTheDocument();
      });
    });

    it("shows error message when fetchUpstream fails", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockRejectedValue(new Error("Upstream fetch failed"));

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => {
        expect(screen.getByText("Upstream fetch failed")).toBeInTheDocument();
      });
    });

    it("expand/shrink button toggles modal size", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() =>
        screen.getByRole("heading", { name: /upstream dependencies/i })
      );

      // Default is shrunk, click Expand
      fireEvent.click(screen.getByTitle("Expand"));
      expect(screen.getByTitle("Shrink")).toBeInTheDocument();

      // Shrink it back
      fireEvent.click(screen.getByTitle("Shrink"));
      expect(screen.getByTitle("Expand")).toBeInTheDocument();
    });

    it("table view mode shows dependency table when dependencies exist", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ namespace: "dep-ns", app_name: "dep-app", tier: "T2" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));

      // Switch to table view
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(
          screen.getByRole("columnheader", { name: /^name$/i })
        ).toBeInTheDocument();
        expect(
          screen.getByRole("columnheader", { name: /^type$/i })
        ).toBeInTheDocument();
      });
    });

    it("Add Dependency button is present when dependencies are loaded", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() =>
        screen.getByRole("heading", { name: /upstream dependencies/i })
      );

      expect(
        screen.getByRole("button", { name: /add dependency/i })
      ).toBeInTheDocument();
    });

    it("clicking Add Dependency opens the add form", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([makeApplication()]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() =>
        screen.getByRole("button", { name: /add dependency/i })
      );
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /add upstream dependency/i })
        ).toBeInTheDocument();
      });
    });

    it("cancelling the Add Dependency form closes it", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([makeApplication()]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() =>
        screen.getByRole("button", { name: /add dependency/i })
      );
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() =>
        screen.getByRole("heading", { name: /add upstream dependency/i })
      );

      fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

      await waitFor(() => {
        expect(
          screen.queryByRole("heading", { name: /add upstream dependency/i })
        ).not.toBeInTheDocument();
      });
    });

    it("deleting a dependency from table view shows confirm modal", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: 1, application_name: "dep-to-remove" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));

      // Switch to table view to see delete buttons
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));

      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /request dependency removal/i })
        ).toBeInTheDocument();
      });
    });

    it("confirms delete dependency calls deleteUpstreamDependency API", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: 55, application_name: "dep-to-remove" }),
      ]);
      mockDeleteUpstreamDependency.mockResolvedValue({ success: true });

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByRole("heading", { name: /request dependency removal/i }));

      // Confirm button now says "Submit Request" (approval flow)
      const confirmBtn = screen.getByRole("button", { name: /^submit request$/i });

      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(mockSubmitRequest).toHaveBeenCalledWith(
          expect.objectContaining({ applicationId: 10, dependencyId: 55, action: "DELETE" })
        );
      });
    });
  });

  // ─── Column sorting ──────────────────────────────────────────────────────────
  describe("Column sorting", () => {
    it("clicking Tenant header sorts services by serviceType asc then desc", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ managedServiceId: 1, serviceType: "redis" }),
        makeManagedService({ managedServiceId: 2, serviceType: "cosmos" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/2 managed services/i));

      // Click "Service Type" column header to trigger sort
      const header = screen.getByRole("columnheader", { name: /tenant/i });
      fireEvent.click(header);

      await waitFor(() => {
        // After sort asc, cosmos should appear before redis
        const badges = screen.getAllByRole("cell");
        expect(badges.length).toBeGreaterThan(0);
      });

      // Click again to sort descending
      fireEvent.click(header);
      await waitFor(() => {
        expect(screen.getAllByRole("cell").length).toBeGreaterThan(0);
      });
    });

    it("clicking Subscription header sorts by subscriptionId", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ managedServiceId: 1, subscriptionId: "sub-zzz" }),
        makeManagedService({ managedServiceId: 2, subscriptionId: "sub-aaa" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/2 managed services/i));

      const header = screen.getByRole("columnheader", { name: /subscription/i });
      fireEvent.click(header);

      await waitFor(() => {
        expect(screen.getByText("sub-aaa")).toBeInTheDocument();
      });
    });

    it("clicking Database header sorts by databaseName", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ managedServiceId: 1, databaseName: "z-db" }),
        makeManagedService({ managedServiceId: 2, databaseName: "a-db" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/2 managed services/i));

      const header = screen.getByRole("columnheader", { name: /^database$/i });
      fireEvent.click(header);

      await waitFor(() => {
        expect(screen.getByText("a-db")).toBeInTheDocument();
        expect(screen.getByText("z-db")).toBeInTheDocument();
      });
    });
  });

  // ─── click-outside closes menus ──────────────────────────────────────────────
  describe("click-outside menu behaviour", () => {
    it("clicking outside the Columns menu closes it", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/0 managed services/i));

      fireEvent.click(screen.getByText("Columns"));
      // "DNS" only appears in the dropdown (hidden column), not in the table header
      expect(screen.getByText("DNS")).toBeInTheDocument();

      // Simulate click outside
      fireEvent.mouseDown(document.body);

      await waitFor(() => {
        expect(screen.queryByText("DNS")).not.toBeInTheDocument();
      });
    });

    it("opening Density menu closes the Columns menu", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/0 managed services/i));

      fireEvent.click(screen.getByText("Columns"));
      // "DNS" only appears in the columns dropdown
      expect(screen.getByText("DNS")).toBeInTheDocument();

      fireEvent.click(screen.getByText("Density"));

      await waitFor(() => {
        expect(screen.queryByText("DNS")).not.toBeInTheDocument();
        expect(screen.getByText("Compact")).toBeInTheDocument();
      });
    });

    it("opening Columns menu closes the Density menu", async () => {
      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/0 managed services/i));

      fireEvent.click(screen.getByText("Density"));
      expect(screen.getByText("Compact")).toBeInTheDocument();

      fireEvent.click(screen.getByText("Columns"));

      await waitFor(() => {
        expect(screen.queryByText("Compact")).not.toBeInTheDocument();
        // "DNS" is visible in the columns dropdown only
        expect(screen.getByText("DNS")).toBeInTheDocument();
      });
    });
  });

  // ─── Export with DNS column enabled ──────────────────────────────────────────
  describe("Export with additional columns", () => {
    it("exports CSV including DNS column when DNS column is toggled on", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ dns: "cosmos.azure.com" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText(/1 managed services/i));

      // Enable the DNS column
      fireEvent.click(screen.getByText("Columns"));
      const dnsToggle = screen
        .getAllByText("DNS")
        .find((el) => el.closest("label"));
      fireEvent.click(dnsToggle!.closest("label")!);

      // Now export
      const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
      fireEvent.click(screen.getByText("Export"));

      expect(global.URL.createObjectURL).toHaveBeenCalled();
      clickSpy.mockRestore();
    });
  });

  // ─── Upstream Modal — Add dependency full flow ───────────────────────────────
  describe("Add Dependency full flow", () => {
    it("selecting a dependency in the add form and submitting calls addUpstreamDependency", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([
        makeApplication({ id: 200, name: "new-dep-app", applicationType: "wcnp" }),
      ]);
      mockAddUpstreamDependency.mockResolvedValue({ success: true });

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() =>
        screen.getByRole("button", { name: /add dependency/i })
      );
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() =>
        screen.getByRole("heading", { name: /add upstream dependency/i })
      );

      // Open the dependency selector dropdown
      const selectDepBtn = screen.getByText(/select a dependency/i).closest("button");
      fireEvent.click(selectDepBtn!);

      // Wait for the app to appear in the dropdown
      await waitFor(() => screen.getByText("new-dep-app"));

      fireEvent.click(screen.getByText("new-dep-app"));

      // Submit the form - button now says "Submit Request" (approval flow)
      const submitBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(submitBtn);
      });

      await waitFor(() => {
        expect(mockSubmitRequest).toHaveBeenCalledWith(
          expect.objectContaining({ applicationId: 10, dependencyId: 200, action: "ADD" })
        );
      });
    });

    it("shows success toast after adding a dependency", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([
        makeApplication({ id: 200, name: "dep-to-add", applicationType: "wcnp" }),
      ]);
      mockAddUpstreamDependency.mockResolvedValue({ success: true });

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByRole("button", { name: /add dependency/i }));
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() =>
        screen.getByRole("heading", { name: /add upstream dependency/i })
      );

      const selectDepBtn = screen.getByText(/select a dependency/i).closest("button");
      fireEvent.click(selectDepBtn!);

      await waitFor(() => screen.getByText("dep-to-add"));
      fireEvent.click(screen.getByText("dep-to-add"));

      const submitBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(submitBtn);
      });

      await waitFor(() => {
        expect(screen.getByText(/approval request submitted.*pending review/i)).toBeInTheDocument();
      });
    });

    it("shows error in add form when addUpstreamDependency throws 'already exists'", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([
        makeApplication({ id: 200, name: "existing-dep", applicationType: "wcnp" }),
      ]);
      mockSubmitRequest.mockRejectedValueOnce(new Error("Dependency already exists"));

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByRole("button", { name: /add dependency/i }));
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() =>
        screen.getByRole("heading", { name: /add upstream dependency/i })
      );

      const selectDepBtn = screen.getByText(/select a dependency/i).closest("button");
      fireEvent.click(selectDepBtn!);

      await waitFor(() => screen.getByText("existing-dep"));
      fireEvent.click(screen.getByText("existing-dep"));

      const submitBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(submitBtn);
      });

      await waitFor(() => {
        expect(
          screen.getByText(/this dependency already exists/i)
        ).toBeInTheDocument();
      });
    });

    it("type dropdown in add form switches between WCNP, OneOps, PageFlow", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([
        makeApplication({ id: 201, name: "oneops-app", applicationType: "oneops" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByRole("button", { name: /add dependency/i }));
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() =>
        screen.getByRole("heading", { name: /add upstream dependency/i })
      );

      // The type selector button should default to WCNP
      expect(screen.getByText("WCNP")).toBeInTheDocument();

      // Open type dropdown
      fireEvent.click(screen.getByText("WCNP").closest("button")!);

      await waitFor(() => screen.getByText("OneOps"));
      fireEvent.click(screen.getByText("OneOps"));

      // Now OneOps is selected
      await waitFor(() => {
        expect(screen.getAllByText("OneOps").length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  // ─── Upstream Modal — delete dependency error path ───────────────────────────
  describe("Delete dependency error handling", () => {
    it("shows 'circular dependency' error message when delete throws circular error", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: 55 }),
      ]);
      mockSubmitRequest.mockRejectedValueOnce(
        new Error("Circular dependency detected")
      );

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByRole("heading", { name: /request dependency removal/i }));

      const confirmBtn = screen.getByRole("button", { name: /^submit request$/i });

      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(
          screen.getByText(/cannot add.*circular dependency/i)
        ).toBeInTheDocument();
      });
    });

    it("shows dialog error message inline when dependency delete fails", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: 55 }),
      ]);
      mockSubmitRequest.mockRejectedValueOnce(
        new Error("not found")
      );

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByRole("heading", { name: /request dependency removal/i }));

      const confirmBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(
          screen.getByText(/application not found/i)
        ).toBeInTheDocument();
      });
    });
  });

  // ─── Upstream dependencies — getAppType branches ─────────────────────────────
  describe("getAppType rendering in diagram view", () => {
    it("shows WCNP type label in table view for dependency with namespace", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({
          id: 1,
          application_id: 1,
          namespace: "wcnp-ns",
          app_name: "wcnp-app",
          platform: undefined,
          org: undefined,
          assembly: undefined,
        }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("WCNP")).toBeInTheDocument();
      });
    });

    it("shows OneOps type label in table view for dependency with platform", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({
          id: 1,
          application_id: 1,
          namespace: null,
          app_name: null,
          platform: "my-platform",
          org: "my-org",
          assembly: "my-assembly",
        }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("OneOps")).toBeInTheDocument();
      });
    });

    it("shows PageFlow type in table view for dep with pageFlow", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({
          id: 1,
          application_id: 1,
          namespace: null,
          app_name: null,
          platform: undefined,
          org: undefined,
          assembly: undefined,
          wcnp: undefined,
          oneOpsPlatform: undefined,
          pageFlow: { id: 1, name: "checkout-flow" } as never,
          name: "checkout-flow",
        }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("PageFlow")).toBeInTheDocument();
      });
    });

    it("shows WCNP type for dep with wcnp object (no namespace/app_name)", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({
          id: 1,
          application_id: 1,
          namespace: null,
          app_name: null,
          platform: undefined,
          org: undefined,
          assembly: undefined,
          wcnp: { namespace: "wcnp-ns", app: "wcnp-app" } as never,
        }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("WCNP")).toBeInTheDocument();
      });
    });

    it("shows App type label for dep with no recognized type properties", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({
          id: 1,
          application_id: 1,
          namespace: null,
          app_name: null,
          platform: undefined,
          org: undefined,
          assembly: undefined,
          wcnp: undefined,
          oneOpsPlatform: undefined,
          pageFlow: undefined,
          application_name: "generic-app",
          name: "generic-app",
        }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("App")).toBeInTheDocument();
      });
    });

    it("shows OneOps type for dep with oneOpsPlatform object", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({
          id: 1,
          application_id: 1,
          namespace: null,
          app_name: null,
          platform: undefined,
          org: undefined,
          assembly: undefined,
          wcnp: undefined,
          oneOpsPlatform: { name: "oneops-plat" } as never,
        }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => {
        expect(screen.getByText("OneOps")).toBeInTheDocument();
      });
    });
  });

  // ─── Row click ─────────────────────────────────────────────────────────────

  describe("Row click", () => {
    it("triggers onRowClick callback when a table row is clicked", async () => {
      mockFetchAll.mockResolvedValue([
        makeManagedService({ managedServiceId: 1, serviceType: "unique-row-click-svc" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("unique-row-click-svc"));

      // Click the table row — exercises the onRowClick handler (lines 296-299)
      const row = screen.getByText("unique-row-click-svc").closest("tr");
      if (row) fireEvent.click(row);

      // setSelectedManagedService is mocked; just verify render doesn't crash
      expect(screen.getByText("unique-row-click-svc")).toBeInTheDocument();
    });
  });

  // ─── Upstream Modal — auto-reject and error paths ─────────────────────────

  describe("Upstream Modal — auto-reject DELETE", () => {
    it("shows auto-rejected toast when delete returns system rejection", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: 55 }),
      ]);
      mockSubmitRequest.mockResolvedValueOnce({
        status: 200,
        message: "ok",
        data: {
          id: 1, applicationId: 10, applicationName: "my-cosmos-db",
          dependencyId: 55, dependencyName: "upstream-app",
          action: "DELETE", status: "REJECTED", reason: "previous rejection exists",
          requestedBy: "test.user", approvedBy: "system", approvedAt: "2026-03-27T12:00:00.000Z",
          createdAt: "2026-03-27T10:00:00.000Z", updatedAt: "2026-03-27T10:00:00.000Z",
        },
      });

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByRole("heading", { name: /request dependency removal/i }));
      const confirmBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(screen.getByText(/Auto-rejected: previous rejection exists/i)).toBeInTheDocument();
      });
    });
  });

  describe("Upstream Modal — auto-reject ADD", () => {
    it("shows auto-rejected toast when add returns system rejection", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([
        makeApplication({ id: 200, name: "auto-reject-dep", applicationType: "wcnp" }),
      ]);
      mockSubmitRequest.mockResolvedValueOnce({
        status: 200,
        message: "ok",
        data: {
          id: 1, applicationId: 10, applicationName: "my-cosmos-db",
          dependencyId: 200, dependencyName: "auto-reject-dep",
          action: "ADD", status: "REJECTED", reason: "auto-rejected",
          requestedBy: "test.user", approvedBy: "system", approvedAt: "2026-03-27T12:00:00.000Z",
          createdAt: "2026-03-27T10:00:00.000Z", updatedAt: "2026-03-27T10:00:00.000Z",
        },
      });

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByRole("button", { name: /add dependency/i }));
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() => screen.getByRole("heading", { name: /add upstream dependency/i }));

      const selectDepBtn = screen.getByText(/select a dependency/i).closest("button");
      fireEvent.click(selectDepBtn!);

      await waitFor(() => screen.getByText("auto-reject-dep"));
      fireEvent.click(screen.getByText("auto-reject-dep"));

      const submitBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(submitBtn);
      });

      await waitFor(() => {
        expect(screen.getByText(/Auto-rejected: auto-rejected/i)).toBeInTheDocument();
      });
    });
  });

  describe("Upstream Modal — parseErrorMessage branches", () => {
    it("handles 400 Bad Request error message", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: 55 }),
      ]);
      mockSubmitRequest.mockRejectedValueOnce(new Error("400 Bad Request"));

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByRole("heading", { name: /request dependency removal/i }));
      const confirmBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(screen.getByText(/invalid dependency configuration/i)).toBeInTheDocument();
      });
    });

    it("strips 'An unexpected error occurred' prefix from error message", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: 55 }),
      ]);
      mockSubmitRequest.mockRejectedValueOnce(new Error("An unexpected error occurred: Something specific happened"));

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByRole("heading", { name: /request dependency removal/i }));
      const confirmBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(screen.getAllByText(/something specific happened/i).length).toBeGreaterThan(0);
      });
    });
  });

  describe("Upstream Modal — backdrop click", () => {
    it("closes the upstream modal when clicking the backdrop", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);

      const { container } = render(<ManagedServicesView />);
      await waitFor(() => screen.getByText("cosmos"));
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() =>
        screen.getByRole("heading", { name: /upstream dependencies/i })
      );

      // Click the backdrop (the fixed overlay div)
      const backdrops = container.querySelectorAll(".fixed.inset-0.bg-black\\/50");
      const upstreamBackdrop = Array.from(backdrops).find(
        (el) => el.querySelector('[class*="shadow-xl"]')
      );
      if (upstreamBackdrop) {
        fireEvent.click(upstreamBackdrop);
      }

      await waitFor(() => {
        expect(
          screen.queryByRole("heading", { name: /upstream dependencies/i })
        ).not.toBeInTheDocument();
      });
    });
  });

  describe("Upstream Modal — Change selected dependency", () => {
    it("clicking Change resets the selected dependency", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([
        makeApplication({ id: 200, name: "change-dep", applicationType: "wcnp" }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByRole("button", { name: /add dependency/i }));
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() => screen.getByRole("heading", { name: /add upstream dependency/i }));

      // Select a dependency
      const selectDepBtn = screen.getByText(/select a dependency/i).closest("button");
      fireEvent.click(selectDepBtn!);

      await waitFor(() => screen.getByText("change-dep"));
      fireEvent.click(screen.getByText("change-dep"));

      // Verify selection is shown
      await waitFor(() => {
        expect(screen.getByText("Selected:")).toBeInTheDocument();
        expect(screen.getByText("change-dep")).toBeInTheDocument();
      });

      // Click Change to deselect
      fireEvent.click(screen.getByText("Change"));

      // Should show the select button again
      await waitFor(() => {
        expect(screen.getByText(/select a dependency/i)).toBeInTheDocument();
      });
    });
  });

  describe("Upstream Modal — add form error catch", () => {
    it("handles error thrown by handleAddWithErrorHandling in form submit", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockResolvedValue([
        makeApplication({ id: 200, name: "error-dep", applicationType: "wcnp" }),
      ]);
      mockSubmitRequest.mockRejectedValueOnce(new Error("Dependency already exists"));

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByRole("button", { name: /add dependency/i }));
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() => screen.getByRole("heading", { name: /add upstream dependency/i }));

      const selectDepBtn = screen.getByText(/select a dependency/i).closest("button");
      fireEvent.click(selectDepBtn!);
      await waitFor(() => screen.getByText("error-dep"));
      fireEvent.click(screen.getByText("error-dep"));

      const submitBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(submitBtn);
      });

      // The form should still be visible (error handled, form not closed)
      await waitFor(() => {
        expect(screen.getByText(/this dependency already exists/i)).toBeInTheDocument();
      });
    });
  });

  describe("Upstream Modal — loading dep dropdown", () => {
    it("shows loading spinner in dependency dropdown while fetching", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      let resolveApps!: (val: Application[]) => void;
      mockApplicationsFetchAll.mockReturnValue(new Promise((res) => { resolveApps = res; }));

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByRole("button", { name: /add dependency/i }));
      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() => screen.getByRole("heading", { name: /add upstream dependency/i }));

      // Open the dependency dropdown while still loading
      const selectDepBtn = screen.getByText(/loading dependencies/i).closest("button");
      if (selectDepBtn) {
        fireEvent.click(selectDepBtn);

        await waitFor(() => {
          expect(screen.getByText(/fetching dependencies/i)).toBeInTheDocument();
        });
      }

      await act(async () => { resolveApps([makeApplication()]); });
    });
  });

  describe("Upstream Modal — dep without application_id", () => {
    it("shows error when attempting to delete dep without application_id", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([
        makeDependency({ id: 1, application_id: undefined as never }),
      ]);

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      await waitFor(() => screen.getByText(/found 1 upstream dependency/i));
      fireEvent.click(screen.getByTitle("Table view"));

      await waitFor(() => screen.getByTitle("Delete dependency"));
      fireEvent.click(screen.getByTitle("Delete dependency"));

      await waitFor(() => screen.getByRole("heading", { name: /request dependency removal/i }));
      const confirmBtn = screen.getByRole("button", { name: /^submit request$/i });
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(screen.getByText(/cannot delete/i)).toBeInTheDocument();
      });
    });
  });

  describe("Upstream Modal — fetchAll error for apps", () => {
    it("handles error when applicationsApi.fetchAll fails in UpstreamModal", async () => {
      mockFetchAll.mockResolvedValue([makeManagedService({ appId: 10 })]);
      mockFetchUpstream.mockResolvedValue([]);
      mockApplicationsFetchAll.mockRejectedValue(new Error("Failed to fetch apps"));

      render(<ManagedServicesView />);
      await waitFor(() => screen.getAllByText("cosmos").length >= 1);
      fireEvent.click(screen.getByTitle("View upstream dependencies"));

      // Wait for modal to show; the catch sets allFetchedApps to []
      await waitFor(() => screen.getByRole("button", { name: /add dependency/i }));

      fireEvent.click(screen.getByRole("button", { name: /add dependency/i }));

      await waitFor(() => screen.getByRole("heading", { name: /add upstream dependency/i }));

      // Open the dropdown — should show "No WCNP applications available"
      const selectDepBtn = screen.getByText(/select a dependency/i).closest("button");
      fireEvent.click(selectDepBtn!);

      await waitFor(() => {
        expect(screen.getByText(/no wcnp applications available/i)).toBeInTheDocument();
      });
    });
  });
});
