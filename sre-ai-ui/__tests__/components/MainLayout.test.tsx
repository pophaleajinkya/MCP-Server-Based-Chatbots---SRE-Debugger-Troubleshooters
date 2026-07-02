import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { MainLayout } from "@/components/MainLayout";

// ─── Context mocks ────────────────────────────────────────────────────────────
// Both hooks are wrapped in jest.fn() so tests can override the return value
// with mockReturnValue / mockReturnValueOnce inside individual test cases.

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false, theme: "light", toggleTheme: jest.fn() }),
}));

const mockUseAuth = jest.fn(() => ({ user: null }));
jest.mock("@/contexts/AuthContext", () => ({
  useAuth: (...args: unknown[]) => mockUseAuth(...args),
}));

jest.mock("@/contexts/ViewContext", () => ({
  ViewContextProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useViewContext: () => ({
    setActiveView: jest.fn(),
    selectedApplication: null,
    selectedManagedService: null,
  }),
}));

// ─── ChatSlideOver mock ──────────────────────────────────────────────────────

jest.mock("@/components/ChatSlideOver", () => ({
  ChatSlideOver: () => <div data-testid="chat-slide-over" />,
}));

// ─── API client mock ─────────────────────────────────────────────────────────

jest.mock("@/lib/api-client", () => ({
  managedServicesApi: {
    fetchAll: jest.fn().mockResolvedValue([]),
  },
  applicationsApi: {
    fetchAll: jest.fn().mockResolvedValue([]),
  },
}));

// ─── View / sub-component mocks ───────────────────────────────────────────────

jest.mock("@/components/ChatInterface", () => ({
  ChatInterface: () => <div data-testid="chat-interface" />,
}));

jest.mock("@/components/views/ApplicationsView", () => ({
  ApplicationsView: () => <div data-testid="applications-view" />,
}));

jest.mock("@/components/views/ManagedServicesView", () => ({
  ManagedServicesView: () => <div data-testid="managed-services-view" />,
}));

jest.mock("@/components/views/AlertsView", () => ({
  AlertsView: () => <div data-testid="alerts-view" />,
}));

jest.mock("@/components/views/OperationsView", () => ({
  OperationsView: () => <div data-testid="operations-view" />,
}));

jest.mock("@/components/views/DependencyApprovalsView", () => ({
  DependencyApprovalsView: () => <div data-testid="approvals-view" />,
}));

// Controllable IconSidebar mock — exposes navigation buttons and the current
// activeView so tests can assert on it and trigger view changes.
jest.mock("@/components/IconSidebar", () => ({
  IconSidebar: ({
    onViewChange,
    activeView,
  }: {
    onViewChange: (v: string) => void;
    activeView: string;
  }) => (
    <div data-testid="icon-sidebar">
      <button onClick={() => onViewChange("applications")}>Go Applications</button>
      <button onClick={() => onViewChange("chat")}>Go Chat</button>
      <button onClick={() => onViewChange("managed-services")}>Go ManagedServices</button>
      <button onClick={() => onViewChange("alerts")}>Go Alerts</button>
      <button onClick={() => onViewChange("operations")}>Go Operations</button>
      <button onClick={() => onViewChange("approvals")}>Go Approvals</button>
      <span data-testid="active-view">{activeView}</span>
    </div>
  ),
}));

// ─── Helpers ──────────────────────────────────────────────────────────────────

function renderLayout(props: { initialSessionId?: string } = {}) {
  return render(<MainLayout {...props} />);
}

// ─── Tests ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  mockUseAuth.mockReturnValue({ user: null });
  // Reset pathname mock to "/" and browser location before each test.
  const { usePathname } = require("next/navigation");
  (usePathname as jest.Mock).mockReturnValue("/");
  window.history.pushState(null, "", "/");
});

describe("MainLayout", () => {
  describe("rendering structure", () => {
    it("renders the IconSidebar", () => {
      renderLayout();
      expect(screen.getByTestId("icon-sidebar")).toBeInTheDocument();
    });

    it("renders with no initialSessionId prop without crashing", () => {
      expect(() => renderLayout()).not.toThrow();
    });

    it("renders with an initialSessionId prop without crashing", () => {
      expect(() => renderLayout({ initialSessionId: "session-abc" })).not.toThrow();
    });
  });

  describe("initial view based on pathname", () => {
    it("renders ChatInterface when pathname is '/'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/");
      renderLayout();
      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();
    });

    it("renders ApplicationsView when pathname is '/applications'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/applications");
      renderLayout();
      expect(screen.getByTestId("applications-view")).toBeInTheDocument();
    });

    it("renders ManagedServicesView when pathname is '/managedservices'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/managedservices");
      renderLayout();
      expect(screen.getByTestId("managed-services-view")).toBeInTheDocument();
    });

    it("renders AlertsView when pathname is '/alerts'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/alerts");
      renderLayout();
      expect(screen.getByTestId("alerts-view")).toBeInTheDocument();
    });

    it("falls back to ChatInterface for unknown pathnames", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/unknown-route");
      renderLayout();
      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();
    });

    it("maps '/applications/detail' (startsWith) to ApplicationsView", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/applications/detail");
      renderLayout();
      expect(screen.getByTestId("applications-view")).toBeInTheDocument();
    });

    it("maps '/managedservices/sub' (startsWith) to ManagedServicesView", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/managedservices/sub");
      renderLayout();
      expect(screen.getByTestId("managed-services-view")).toBeInTheDocument();
    });

    it("maps '/alerts/detail' (startsWith) to AlertsView", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/alerts/detail");
      renderLayout();
      expect(screen.getByTestId("alerts-view")).toBeInTheDocument();
    });
  });

  describe("active view is passed to IconSidebar", () => {
    it("passes activeView='chat' to IconSidebar when pathname='/'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/");
      renderLayout();
      expect(screen.getByTestId("active-view").textContent).toBe("chat");
    });

    it("passes activeView='applications' to IconSidebar when pathname='/applications'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/applications");
      renderLayout();
      expect(screen.getByTestId("active-view").textContent).toBe("applications");
    });

    it("passes activeView='managed-services' to IconSidebar when pathname='/managedservices'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/managedservices");
      renderLayout();
      expect(screen.getByTestId("active-view").textContent).toBe("managed-services");
    });

    it("passes activeView='alerts' to IconSidebar when pathname='/alerts'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/alerts");
      renderLayout();
      expect(screen.getByTestId("active-view").textContent).toBe("alerts");
    });
  });

  describe("view switching via sidebar buttons", () => {
    it("switches to ApplicationsView when 'Go Applications' is clicked", () => {
      renderLayout();
      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();

      fireEvent.click(screen.getByText("Go Applications"));

      expect(screen.getByTestId("applications-view")).toBeInTheDocument();
      expect(screen.queryByTestId("chat-interface")).not.toBeInTheDocument();
    });

    it("switches to ManagedServicesView when 'Go ManagedServices' is clicked", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go ManagedServices"));
      expect(screen.getByTestId("managed-services-view")).toBeInTheDocument();
      expect(screen.queryByTestId("chat-interface")).not.toBeInTheDocument();
    });

    it("switches to AlertsView when 'Go Alerts' is clicked", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go Alerts"));
      expect(screen.getByTestId("alerts-view")).toBeInTheDocument();
      expect(screen.queryByTestId("chat-interface")).not.toBeInTheDocument();
    });

    it("switches back to ChatInterface when 'Go Chat' is clicked after navigating away", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go Applications"));
      expect(screen.getByTestId("applications-view")).toBeInTheDocument();

      fireEvent.click(screen.getByText("Go Chat"));
      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();
      expect(screen.queryByTestId("applications-view")).not.toBeInTheDocument();
    });

    it("updates the activeView passed to IconSidebar when view changes", () => {
      renderLayout();
      expect(screen.getByTestId("active-view").textContent).toBe("chat");

      fireEvent.click(screen.getByText("Go Applications"));
      expect(screen.getByTestId("active-view").textContent).toBe("applications");
    });

    it("updates activeView to 'managed-services' after clicking Go ManagedServices", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go ManagedServices"));
      expect(screen.getByTestId("active-view").textContent).toBe("managed-services");
    });

    it("updates activeView to 'alerts' after clicking Go Alerts", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go Alerts"));
      expect(screen.getByTestId("active-view").textContent).toBe("alerts");
    });
  });

  describe("window.history.pushState on view change", () => {
    let pushStateSpy: jest.SpyInstance;

    beforeEach(() => {
      pushStateSpy = jest.spyOn(window.history, "pushState");
    });

    afterEach(() => {
      pushStateSpy.mockRestore();
    });

    it("calls pushState with '/applications' when switching to applications", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go Applications"));
      expect(pushStateSpy).toHaveBeenCalledWith(null, "", "/applications");
    });

    it("calls pushState with '/managedservices' when switching to managed-services", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go ManagedServices"));
      expect(pushStateSpy).toHaveBeenCalledWith(null, "", "/managedservices");
    });

    it("calls pushState with '/alerts' when switching to alerts", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go Alerts"));
      expect(pushStateSpy).toHaveBeenCalledWith(null, "", "/alerts");
    });

    it("calls pushState with '/' when switching back to chat from applications", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/applications");
      window.history.pushState(null, "", "/applications");
      renderLayout();

      fireEvent.click(screen.getByText("Go Chat"));
      expect(pushStateSpy).toHaveBeenCalledWith(null, "", "/");
    });

    it("does NOT call pushState when navigating to the same path already in the URL", () => {
      // Start on "/" (set in beforeEach) — activeView resolves to "chat".
      // Clicking "Go Chat" maps to "/" which equals window.location.pathname.
      renderLayout();
      fireEvent.click(screen.getByText("Go Chat"));
      expect(pushStateSpy).not.toHaveBeenCalled();
    });
  });

  describe("browser back/forward (popstate)", () => {
    it("updates activeView when a popstate event fires with a new pathname", () => {
      renderLayout();
      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();

      // Simulate browser navigating to /applications
      window.history.pushState(null, "", "/applications");
      fireEvent(window, new PopStateEvent("popstate", { state: null }));

      expect(screen.getByTestId("applications-view")).toBeInTheDocument();
    });

    it("updates activeView to chat when popstate fires at '/'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/applications");
      window.history.pushState(null, "", "/applications");
      renderLayout();
      expect(screen.getByTestId("applications-view")).toBeInTheDocument();

      window.history.pushState(null, "", "/");
      fireEvent(window, new PopStateEvent("popstate", { state: null }));

      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();
    });

    it("updates activeView to managed-services via popstate", () => {
      renderLayout();
      window.history.pushState(null, "", "/managedservices");
      fireEvent(window, new PopStateEvent("popstate", { state: null }));
      expect(screen.getByTestId("managed-services-view")).toBeInTheDocument();
    });

    it("updates activeView to alerts via popstate", () => {
      renderLayout();
      window.history.pushState(null, "", "/alerts");
      fireEvent(window, new PopStateEvent("popstate", { state: null }));
      expect(screen.getByTestId("alerts-view")).toBeInTheDocument();
    });
  });

  describe("user from AuthContext", () => {
    it("renders without error when user is null (no userId)", () => {
      mockUseAuth.mockReturnValue({ user: null });
      expect(() => renderLayout()).not.toThrow();
    });

    it("renders without error when user has a loginId", () => {
      mockUseAuth.mockReturnValue({ user: { loginId: "test-user@example.com" } });
      expect(() => renderLayout()).not.toThrow();
    });

    it("renders without error when user loginId is undefined", () => {
      mockUseAuth.mockReturnValue({ user: { loginId: undefined } });
      expect(() => renderLayout()).not.toThrow();
    });
  });

  // ── Pre-warm cache failure (lines 89-94) ───────────────────────────────────

  describe("pre-warm cache error handling", () => {
    it("renders without error when applicationsApi.fetchAll rejects", async () => {
      const { applicationsApi } = require("@/lib/api-client");
      (applicationsApi.fetchAll as jest.Mock).mockRejectedValueOnce(new Error("network error"));

      expect(() => renderLayout()).not.toThrow();

      // Wait for the effect to fire and the catch to be called
      await new Promise((r) => setTimeout(r, 0));

      // Still renders normally
      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();
    });

    it("renders without error when managedServicesApi.fetchAll rejects", async () => {
      const { managedServicesApi } = require("@/lib/api-client");
      (managedServicesApi.fetchAll as jest.Mock).mockRejectedValueOnce(new Error("network error"));

      expect(() => renderLayout()).not.toThrow();

      await new Promise((r) => setTimeout(r, 0));

      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();
    });

    it("renders without error when both API pre-warm calls reject", async () => {
      const { applicationsApi, managedServicesApi } = require("@/lib/api-client");
      (applicationsApi.fetchAll as jest.Mock).mockRejectedValueOnce(new Error("fail 1"));
      (managedServicesApi.fetchAll as jest.Mock).mockRejectedValueOnce(new Error("fail 2"));

      expect(() => renderLayout()).not.toThrow();

      await new Promise((r) => setTimeout(r, 0));

      expect(screen.getByTestId("chat-interface")).toBeInTheDocument();
    });
  });

  // ── Operations and Approvals views (lines 89-102) ───────────────────────────

  describe("renderContent — operations and approvals cases", () => {
    it("renders OperationsView when pathname is '/operations'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/operations");
      renderLayout();
      expect(screen.getByTestId("operations-view")).toBeInTheDocument();
    });

    it("renders OperationsView when 'Go Operations' is clicked", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go Operations"));
      expect(screen.getByTestId("operations-view")).toBeInTheDocument();
      expect(screen.queryByTestId("chat-interface")).not.toBeInTheDocument();
    });

    it("renders DependencyApprovalsView when pathname is '/approvals'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/approvals");
      renderLayout();
      expect(screen.getByTestId("approvals-view")).toBeInTheDocument();
    });

    it("renders DependencyApprovalsView when 'Go Approvals' is clicked", () => {
      renderLayout();
      fireEvent.click(screen.getByText("Go Approvals"));
      expect(screen.getByTestId("approvals-view")).toBeInTheDocument();
      expect(screen.queryByTestId("chat-interface")).not.toBeInTheDocument();
    });

    it("passes activeView='operations' to IconSidebar when pathname='/operations'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/operations");
      renderLayout();
      expect(screen.getByTestId("active-view").textContent).toBe("operations");
    });

    it("passes activeView='approvals' to IconSidebar when pathname='/approvals'", () => {
      const { usePathname } = require("next/navigation");
      (usePathname as jest.Mock).mockReturnValue("/approvals");
      renderLayout();
      expect(screen.getByTestId("active-view").textContent).toBe("approvals");
    });

    it("calls pushState with '/operations' when switching to operations", () => {
      const pushStateSpy = jest.spyOn(window.history, "pushState");
      renderLayout();
      fireEvent.click(screen.getByText("Go Operations"));
      expect(pushStateSpy).toHaveBeenCalledWith(null, "", "/operations");
      pushStateSpy.mockRestore();
    });

    it("calls pushState with '/approvals' when switching to approvals", () => {
      const pushStateSpy = jest.spyOn(window.history, "pushState");
      renderLayout();
      fireEvent.click(screen.getByText("Go Approvals"));
      expect(pushStateSpy).toHaveBeenCalledWith(null, "", "/approvals");
      pushStateSpy.mockRestore();
    });

    it("updates activeView to 'operations' via popstate", () => {
      renderLayout();
      window.history.pushState(null, "", "/operations");
      fireEvent(window, new PopStateEvent("popstate", { state: null }));
      expect(screen.getByTestId("operations-view")).toBeInTheDocument();
    });

    it("updates activeView to 'approvals' via popstate", () => {
      renderLayout();
      window.history.pushState(null, "", "/approvals");
      fireEvent(window, new PopStateEvent("popstate", { state: null }));
      expect(screen.getByTestId("approvals-view")).toBeInTheDocument();
    });
  });
});
