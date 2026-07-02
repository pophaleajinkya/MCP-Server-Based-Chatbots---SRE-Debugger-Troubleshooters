/**
 * Tests for src/components/AlertsSidebarTimeline.tsx
 *
 * Coverage targets:
 *  ✓ Loading state — shows "Loading timeline..." spinner
 *  ✓ Error state — shows error message text
 *  ✓ Empty state — shows "No alerts to display on timeline"
 *  ✓ Normal view — renders chart with alert count text
 *  ✓ Legend rendering — one entry per alert with correct label
 *  ✓ Expand/collapse — fullscreen overlay opens and closes
 *  ✓ Dark mode support
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlertsSidebarTimeline } from "@/components/AlertsSidebarTimeline";
import type { AlertResultAlert } from "@/lib/api-client";

// ─── Mock ThemeContext ──────────────────────────────────────────────────────
let mockIsDark = false;
jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: mockIsDark }),
}));

// ─── Mock Recharts ──────────────────────────────────────────────────────────
// Recharts components use SVG which jsdom can't fully render. Stub them.
jest.mock("recharts", () => {
  const React = require("react");
  const Original = jest.requireActual("recharts");
  return {
    ...Original,
    ResponsiveContainer: ({ children }: any) => (
      <div data-testid="responsive-container">{children}</div>
    ),
    ScatterChart: ({ children, onMouseDown, onMouseMove, onMouseUp }: any) => (
      <div
        data-testid="scatter-chart"
        onMouseDown={() => onMouseDown?.({ activeLabel: 1700000000 })}
        onMouseMove={() => onMouseMove?.({ activeLabel: 1700000300 })}
        onMouseUp={() => onMouseUp?.()}
      >
        {children}
      </div>
    ),
    Scatter: () => <div data-testid="scatter" />,
    XAxis: ({ tickFormatter }: any) => {
      // Call tickFormatter to cover formatTime
      if (tickFormatter) tickFormatter(1700000000);
      return null;
    },
    YAxis: ({ tickFormatter }: any) => {
      // Call tickFormatter to cover label truncation
      if (tickFormatter) {
        tickFormatter(0);
        tickFormatter(1);
      }
      return null;
    },
    CartesianGrid: () => null,
    Tooltip: ({ content }: any) => {
      // Render the custom tooltip element to cover its branches
      if (content && React.isValidElement(content)) {
        const TooltipComp = (content as any).type;
        if (typeof TooltipComp === "function") {
          return (
            <div data-testid="tooltip-wrapper">
              {React.createElement(TooltipComp, { active: true, payload: [{ payload: { x: 1700000000, y: 0, label: "Test Alert", alertName: "Different" } }] })}
              {React.createElement(TooltipComp, { active: false, payload: [] })}
              {React.createElement(TooltipComp, { active: true, payload: [] })}
            </div>
          );
        }
      }
      return null;
    },
    ReferenceArea: () => null,
    Cell: () => null,
  };
});

// ─── Fixtures ─────────────────────────────────────────────────────────────────

function makeAlert(overrides: Partial<AlertResultAlert> = {}): AlertResultAlert {
  return {
    alert_id: "alert-1",
    alertname: "HighCPU",
    alert_sla_name: "CPU SLA",
    episode_is_open: true,
    episode_start_ts: 1700000000,
    episode_end_ts: null,
    cluster: "prod-1",
    values: [
      [1700000000, "1"],
      [1700000060, "1"],
      [1700000120, "1"],
    ],
    ...overrides,
  } as AlertResultAlert;
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockIsDark = false;
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("AlertsSidebarTimeline", () => {
  // ── Loading state ──────────────────────────────────────────────────────
  describe("loading state", () => {
    it("shows loading spinner and text", () => {
      render(<AlertsSidebarTimeline alerts={[]} loading={true} />);
      expect(screen.getByText(/loading timeline/i)).toBeInTheDocument();
    });

    it("does not render chart when loading", () => {
      render(<AlertsSidebarTimeline alerts={[makeAlert()]} loading={true} />);
      expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
    });
  });

  // ── Error state ────────────────────────────────────────────────────────
  describe("error state", () => {
    it("shows error message text", () => {
      render(<AlertsSidebarTimeline alerts={[]} error="Failed to load" />);
      expect(screen.getByText("Failed to load")).toBeInTheDocument();
    });

    it("does not render chart when error", () => {
      render(<AlertsSidebarTimeline alerts={[makeAlert()]} error="Network error" />);
      expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
    });
  });

  // ── Empty state ────────────────────────────────────────────────────────
  describe("empty state", () => {
    it("shows empty message when alerts array is empty", () => {
      render(<AlertsSidebarTimeline alerts={[]} />);
      expect(screen.getByText(/no alerts to display on timeline/i)).toBeInTheDocument();
    });

    it("shows empty message when alerts is undefined-like", () => {
      render(<AlertsSidebarTimeline alerts={[] as any} />);
      expect(screen.getByText(/no alerts to display on timeline/i)).toBeInTheDocument();
    });
  });

  // ── Normal rendering ───────────────────────────────────────────────────
  describe("normal rendering", () => {
    it("renders chart container when alerts have data", () => {
      render(<AlertsSidebarTimeline alerts={[makeAlert()]} />);
      expect(screen.getByTestId("scatter-chart")).toBeInTheDocument();
    });

    it("shows alert count in header", () => {
      render(<AlertsSidebarTimeline alerts={[makeAlert()]} />);
      expect(screen.getByText(/1 alert/i)).toBeInTheDocument();
    });

    it("pluralizes alert count", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[
            makeAlert({ alert_id: "a1", alert_sla_name: "SLA A" }),
            makeAlert({ alert_id: "a2", alert_sla_name: "SLA B" }),
          ]}
        />
      );
      expect(screen.getByText(/2 alerts/i)).toBeInTheDocument();
    });

    it("shows 'Drag to zoom' helper text", () => {
      render(<AlertsSidebarTimeline alerts={[makeAlert()]} />);
      expect(screen.getByText(/drag to zoom/i)).toBeInTheDocument();
    });
  });

  // ── Legend ──────────────────────────────────────────────────────────────
  describe("legend", () => {
    it("renders legend entry for each alert", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[
            makeAlert({ alert_sla_name: "CPU SLA" }),
            makeAlert({ alert_id: "a2", alert_sla_name: "Memory SLA" }),
          ]}
        />
      );
      expect(screen.getByText("CPU SLA")).toBeInTheDocument();
      expect(screen.getByText("Memory SLA")).toBeInTheDocument();
    });

    it("falls back to alertname when alert_sla_name is missing", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[makeAlert({ alert_sla_name: undefined, alertname: "DiskSpaceLow" })]}
        />
      );
      expect(screen.getByText("DiskSpaceLow")).toBeInTheDocument();
    });

    it("falls back to 'Alert N' when both names are missing", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[makeAlert({ alert_sla_name: undefined, alertname: undefined })]}
        />
      );
      expect(screen.getByText("Alert 1")).toBeInTheDocument();
    });
  });

  // ── Expand / Collapse ──────────────────────────────────────────────────
  describe("expand and collapse", () => {
    it("opens expanded fullscreen view when expand button is clicked", () => {
      render(<AlertsSidebarTimeline alerts={[makeAlert()]} />);

      // The expand button has a Maximize2 icon
      const expandBtn = screen.getByRole("button", { name: "" }); // icon-only button
      // Find by the parent that has the expand icon — we look for the Maximize2 usage
      const buttons = screen.getAllByRole("button");
      // The last non-zoom button should be expand
      const expandButton = buttons[buttons.length - 1];
      fireEvent.click(expandButton);

      // Expanded view shows "Alert Timeline" heading and a minimize button
      expect(screen.getByText("Alert Timeline")).toBeInTheDocument();
    });

    it("closes expanded view when minimize button is clicked", () => {
      render(<AlertsSidebarTimeline alerts={[makeAlert()]} />);

      // Open expanded
      const buttons = screen.getAllByRole("button");
      fireEvent.click(buttons[buttons.length - 1]);

      expect(screen.getByText("Alert Timeline")).toBeInTheDocument();

      // Find the minimize button in expanded view (has Minimize2 icon)
      const expandedButtons = screen.getAllByRole("button");
      // The last button in expanded view is the minimize button
      const minimizeBtn = expandedButtons[expandedButtons.length - 1];
      fireEvent.click(minimizeBtn);

      // "Alert Timeline" heading should be gone (normal view doesn't show it)
      expect(screen.queryByText("Alert Timeline")).not.toBeInTheDocument();
    });

    it("closes expanded view when backdrop is clicked", () => {
      const { container } = render(<AlertsSidebarTimeline alerts={[makeAlert()]} />);

      // Open expanded
      const buttons = screen.getAllByRole("button");
      fireEvent.click(buttons[buttons.length - 1]);

      expect(screen.getByText("Alert Timeline")).toBeInTheDocument();

      // Click the backdrop
      const backdrop = container.querySelector(".fixed.inset-0.bg-black\\/60");
      if (backdrop) fireEvent.click(backdrop);

      expect(screen.queryByText("Alert Timeline")).not.toBeInTheDocument();
    });

    it("shows alert count in expanded view header", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[
            makeAlert({ alert_id: "a1" }),
            makeAlert({ alert_id: "a2" }),
            makeAlert({ alert_id: "a3" }),
          ]}
        />
      );

      const buttons = screen.getAllByRole("button");
      fireEvent.click(buttons[buttons.length - 1]);

      expect(screen.getByText(/3 alerts/i)).toBeInTheDocument();
    });
  });

  // ── Zoom interaction ────────────────────────────────────────────────
  describe("zoom interaction", () => {
    it("shows Reset Zoom button after drag-zoom and resets on click", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[
            makeAlert({ alert_id: "z1", values: [[1700000000, "1"], [1700000300, "1"]] }),
          ]}
        />
      );

      // Initially no Reset Zoom button
      expect(screen.queryByText("Reset Zoom")).not.toBeInTheDocument();

      // Simulate drag-zoom via the mocked ScatterChart: mouseDown → mouseMove → mouseUp
      const chart = screen.getAllByTestId("scatter-chart")[0];
      fireEvent.mouseDown(chart);
      fireEvent.mouseMove(chart);
      fireEvent.mouseUp(chart);

      // After zoom, Reset Zoom button should appear
      expect(screen.getByText("Reset Zoom")).toBeInTheDocument();

      // Click Reset Zoom
      fireEvent.click(screen.getByText("Reset Zoom"));
      expect(screen.queryByText("Reset Zoom")).not.toBeInTheDocument();
    });

    it("does not zoom when mouseUp without prior mouseMove", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[makeAlert({ alert_id: "z2", values: [[1700000000, "1"], [1700001000, "1"]] })]}
        />
      );

      const chart = screen.getAllByTestId("scatter-chart")[0];
      // Only mouseDown + mouseUp (no mouseMove) — should NOT zoom
      fireEvent.mouseDown(chart);
      fireEvent.mouseUp(chart);

      expect(screen.queryByText("Reset Zoom")).not.toBeInTheDocument();
    });

    it("shows Reset Zoom in expanded view after zoom", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[makeAlert({ alert_id: "z3", values: [[1700000000, "1"], [1700000300, "1"]] })]}
        />
      );

      // Zoom first
      const chart = screen.getAllByTestId("scatter-chart")[0];
      fireEvent.mouseDown(chart);
      fireEvent.mouseMove(chart);
      fireEvent.mouseUp(chart);

      // Expand
      const buttons = screen.getAllByRole("button");
      // Find the expand button (not the Reset Zoom)
      const expandBtn = buttons.find(b => !b.textContent?.includes("Reset Zoom"));
      if (expandBtn) fireEvent.click(expandBtn);

      // Reset Zoom should be visible in expanded view too
      expect(screen.getByText("Reset Zoom")).toBeInTheDocument();
    });
  });

  // ── Alerts with no values ──────────────────────────────────────────────
  describe("alerts with edge cases", () => {
    it("handles alert with empty values array", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[makeAlert({ values: [] })]}
        />
      );
      // Should render without crashing — chart renders even if no data points
      expect(screen.getByTestId("scatter-chart")).toBeInTheDocument();
    });

    it("handles alert with undefined values", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[makeAlert({ values: undefined })]}
        />
      );
      expect(screen.getByTestId("scatter-chart")).toBeInTheDocument();
    });

    it("handles alert with no alert_sla_name and no alertname (falls back to Alert N)", () => {
      render(
        <AlertsSidebarTimeline
          alerts={[makeAlert({ alert_sla_name: undefined, alertname: undefined })]}
        />
      );
      expect(screen.getByText("Alert 1")).toBeInTheDocument();
    });
  });

  // ── Dark mode ──────────────────────────────────────────────────────────
  describe("dark mode", () => {
    it("uses dark background class when isDark=true", () => {
      mockIsDark = true;
      const { container } = render(<AlertsSidebarTimeline alerts={[makeAlert()]} />);
      // The outermost div should have the dark bg class
      const outer = container.firstElementChild;
      expect(outer?.className).toContain("bg-[#0d1117]");
    });

    it("uses light background class when isDark=false", () => {
      mockIsDark = false;
      const { container } = render(<AlertsSidebarTimeline alerts={[makeAlert()]} />);
      const outer = container.firstElementChild;
      expect(outer?.className).toContain("bg-white");
    });
  });
});
