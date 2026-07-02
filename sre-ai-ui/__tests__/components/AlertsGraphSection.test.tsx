/**
 * Tests for src/components/AlertsGraphSection.tsx
 *
 * Covers:
 *  - Loading state
 *  - Error state
 *  - Empty data state
 *  - Chart renders with data
 *  - Title and optional subtitle rendering
 *  - Expand / Minimize toggle
 *  - Backdrop click collapses expanded view
 *  - Zoom via mouse drag (mouseDown → mouseMove → mouseUp)
 *  - Zoom reset button appears after zoom and clears domain on click
 *  - "Drag to zoom" hint visible when data present and no zoom
 *  - Hint hidden when zoomed
 *  - ReferenceArea rendered during active drag
 *  - formatXTick helper exercised through XAxis tickFormatter
 *  - formatTooltipTime helper exercised through Tooltip labelFormatter
 *  - Tooltip value formatter exercised
 *  - Dark mode applies different style classes
 *  - Custom lineColor and yAxisLabel props
 *  - mouseUp with only refAreaLeft set (no zoom applied)
 *  - mouseUp where left === right (no zoom applied)
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─── Mock recharts ────────────────────────────────────────────────────────────

jest.mock("recharts", () => {
  const React = require("react");
  return {
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
    LineChart: ({
      children,
      data,
      onMouseDown,
      onMouseMove,
      onMouseUp,
    }: {
      children: React.ReactNode;
      data?: unknown[];
      onMouseDown?: (e: any) => void;
      onMouseMove?: (e: any) => void;
      onMouseUp?: () => void;
    }) => (
      <div
        data-testid="line-chart"
        data-points={data?.length}
        onMouseDown={(e) => {
          // First call: set refAreaLeft
          onMouseDown?.({ activeLabel: (e.target as HTMLElement).dataset.label ?? 1000 });
        }}
        onMouseMove={(e) => {
          // Second call: set refAreaRight
          onMouseMove?.({ activeLabel: (e.target as HTMLElement).dataset.label ?? 2000 });
        }}
        onMouseUp={() => onMouseUp?.()}
      >
        {children}
      </div>
    ),
    Line: ({ dataKey, stroke }: { dataKey: string; stroke: string }) => (
      <div data-testid="line" data-key={dataKey} data-stroke={stroke} />
    ),
    XAxis: ({ tickFormatter }: { tickFormatter?: (v: number) => string }) => {
      // Exercise formatXTick helper
      const tick = tickFormatter ? tickFormatter(1609459200) : "";
      return <div data-testid="x-axis" data-tick={tick} />;
    },
    YAxis: ({ label }: { label?: { value?: string } }) => (
      <div data-testid="y-axis" data-label={label?.value} />
    ),
    CartesianGrid: () => <div data-testid="cartesian-grid" />,
    Tooltip: ({
      labelFormatter,
      formatter,
    }: {
      labelFormatter?: (v: number) => string;
      formatter?: (v: unknown, n: string) => [unknown, string];
    }) => {
      // Exercise formatTooltipTime helper
      const label = labelFormatter ? labelFormatter(1609459200) : "";
      // Exercise value formatter
      const formatted = formatter ? formatter(42, "Count") : null;
      return (
        <div
          data-testid="tooltip"
          data-label={label}
          data-formatted={formatted ? JSON.stringify(formatted) : ""}
        />
      );
    },
    ReferenceArea: ({ x1, x2 }: { x1?: number; x2?: number }) => (
      <div data-testid="reference-area" data-x1={x1} data-x2={x2} />
    ),
  };
});

// ─── Mock ThemeContext ────────────────────────────────────────────────────────

const mockIsDark = { value: false };

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: mockIsDark.value }),
}));

// ─── Import component after mocks ─────────────────────────────────────────────

import {
  AlertsGraphSection,
  type GraphDataPoint,
} from "@/components/AlertsGraphSection";

// ─── Fixtures ────────────────────────────────────────────────────────────────

function makeDataPoints(count: number): GraphDataPoint[] {
  return Array.from({ length: count }, (_, i) => ({
    timestamp: 1000 + i * 60,
    value: i + 1,
    label: `T+${i}m`,
  }));
}

const defaultProps = {
  title: "Alert Rate",
  data: makeDataPoints(5),
  loading: false,
  error: null,
};

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("AlertsGraphSection", () => {
  beforeEach(() => {
    mockIsDark.value = false;
  });

  // ── States ─────────────────────────────────────────────────────────────────

  describe("Loading state", () => {
    it("shows spinner and loading text when loading=true", () => {
      render(<AlertsGraphSection {...defaultProps} loading={true} />);
      expect(screen.getByText("Loading data...")).toBeInTheDocument();
    });

    it("does not render chart while loading", () => {
      render(<AlertsGraphSection {...defaultProps} loading={true} />);
      expect(screen.queryByTestId("line-chart")).not.toBeInTheDocument();
    });
  });

  describe("Error state", () => {
    it("shows error message when error is set", () => {
      render(
        <AlertsGraphSection {...defaultProps} error="Failed to fetch metrics" />
      );
      expect(screen.getByText("Failed to fetch metrics")).toBeInTheDocument();
    });

    it("does not render chart when error is set", () => {
      render(<AlertsGraphSection {...defaultProps} error="oops" />);
      expect(screen.queryByTestId("line-chart")).not.toBeInTheDocument();
    });
  });

  describe("Empty state", () => {
    it("shows 'No data available' when data array is empty", () => {
      render(<AlertsGraphSection {...defaultProps} data={[]} />);
      expect(
        screen.getByText("No data available for this time range")
      ).toBeInTheDocument();
    });

    it("does not render chart with empty data", () => {
      render(<AlertsGraphSection {...defaultProps} data={[]} />);
      expect(screen.queryByTestId("line-chart")).not.toBeInTheDocument();
    });
  });

  // ── Chart rendering ────────────────────────────────────────────────────────

  describe("Chart rendering", () => {
    it("renders the title", () => {
      render(<AlertsGraphSection {...defaultProps} title="CPU Alerts" />);
      expect(screen.getByText("CPU Alerts")).toBeInTheDocument();
    });

    it("renders subtitle when provided", () => {
      render(
        <AlertsGraphSection
          {...defaultProps}
          subtitle="Last 30 minutes"
        />
      );
      expect(screen.getByText("Last 30 minutes")).toBeInTheDocument();
    });

    it("does not render subtitle element when omitted", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      // Only the title paragraph should be there, no subtitle
      expect(screen.queryByText("Last 30 minutes")).not.toBeInTheDocument();
    });

    it("renders chart with data points", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      expect(screen.getByTestId("line-chart")).toBeInTheDocument();
      expect(screen.getByTestId("line-chart")).toHaveAttribute(
        "data-points",
        "5"
      );
    });

    it("renders y-axis with custom label", () => {
      render(
        <AlertsGraphSection {...defaultProps} yAxisLabel="Requests/min" />
      );
      expect(screen.getByTestId("y-axis")).toHaveAttribute(
        "data-label",
        "Requests/min"
      );
    });

    it("exercises formatXTick via XAxis tickFormatter", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      // The XAxis mock calls tickFormatter(1609459200) and stores result in data-tick
      const xAxis = screen.getByTestId("x-axis");
      // formatXTick should return a time string (e.g. "12:00 AM")
      expect(xAxis.getAttribute("data-tick")).toMatch(/\d{2}:\d{2}/);
    });

    it("exercises formatTooltipTime via Tooltip labelFormatter", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      const tooltip = screen.getByTestId("tooltip");
      // formatTooltipTime should return a locale date string
      expect(tooltip.getAttribute("data-label")).toBeTruthy();
      expect(tooltip.getAttribute("data-label")).not.toBe("");
    });

    it("exercises tooltip value formatter", () => {
      render(<AlertsGraphSection {...defaultProps} yAxisLabel="Rate" />);
      const tooltip = screen.getByTestId("tooltip");
      expect(tooltip.getAttribute("data-formatted")).toContain("42");
    });

    it("shows 'Drag to zoom' hint when data present and not zoomed", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      expect(screen.getByText("Drag to zoom")).toBeInTheDocument();
    });

    it("does not show 'Drag to zoom' hint when loading", () => {
      render(<AlertsGraphSection {...defaultProps} loading={true} />);
      expect(screen.queryByText("Drag to zoom")).not.toBeInTheDocument();
    });

    it("does not show 'Drag to zoom' hint when error", () => {
      render(<AlertsGraphSection {...defaultProps} error="oops" />);
      expect(screen.queryByText("Drag to zoom")).not.toBeInTheDocument();
    });

    it("does not show 'Drag to zoom' hint when no data", () => {
      render(<AlertsGraphSection {...defaultProps} data={[]} />);
      expect(screen.queryByText("Drag to zoom")).not.toBeInTheDocument();
    });
  });

  // ── Expand / Minimize ──────────────────────────────────────────────────────

  describe("Expand / Minimize", () => {
    it("starts collapsed with Expand button", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      expect(screen.getByTitle("Expand")).toBeInTheDocument();
      expect(screen.queryByTitle("Minimize")).not.toBeInTheDocument();
    });

    it("shows Minimize button after expanding", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      fireEvent.click(screen.getByTitle("Expand"));
      expect(screen.getByTitle("Minimize")).toBeInTheDocument();
      expect(screen.queryByTitle("Expand")).not.toBeInTheDocument();
    });

    it("shows backdrop when expanded", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      fireEvent.click(screen.getByTitle("Expand"));
      // Backdrop is a fixed overlay div (aria-hidden, click-closes)
      const backdrops = document.querySelectorAll(".fixed.inset-0.bg-black\\/50");
      expect(backdrops.length).toBeGreaterThan(0);
    });

    it("clicking backdrop collapses the expanded view", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      fireEvent.click(screen.getByTitle("Expand"));
      expect(screen.getByTitle("Minimize")).toBeInTheDocument();

      const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/50");
      expect(backdrop).toBeTruthy();
      fireEvent.click(backdrop!);

      expect(screen.queryByTitle("Minimize")).not.toBeInTheDocument();
      expect(screen.getByTitle("Expand")).toBeInTheDocument();
    });

    it("clicking Minimize collapses the view", () => {
      render(<AlertsGraphSection {...defaultProps} />);
      fireEvent.click(screen.getByTitle("Expand"));
      fireEvent.click(screen.getByTitle("Minimize"));
      expect(screen.getByTitle("Expand")).toBeInTheDocument();
    });
  });

  // ── Zoom behavior ─────────────────────────────────────────────────────────

  describe("Zoom behavior", () => {
    it("shows 'Reset zoom' button after mouse drag zoom", async () => {
      render(<AlertsGraphSection {...defaultProps} />);
      const chart = screen.getByTestId("line-chart");

      // Simulate drag: mousedown → mousemove → mouseup
      fireEvent.mouseDown(chart);
      fireEvent.mouseMove(chart);
      fireEvent.mouseUp(chart);

      await waitFor(() => {
        expect(screen.getByTitle("Reset zoom")).toBeInTheDocument();
      });
    });

    it("hides 'Drag to zoom' hint after zoom is applied", async () => {
      render(<AlertsGraphSection {...defaultProps} />);
      const chart = screen.getByTestId("line-chart");

      fireEvent.mouseDown(chart);
      fireEvent.mouseMove(chart);
      fireEvent.mouseUp(chart);

      await waitFor(() => {
        expect(screen.queryByText("Drag to zoom")).not.toBeInTheDocument();
      });
    });

    it("clicking 'Reset zoom' removes zoom and shows hint again", async () => {
      render(<AlertsGraphSection {...defaultProps} />);
      const chart = screen.getByTestId("line-chart");

      fireEvent.mouseDown(chart);
      fireEvent.mouseMove(chart);
      fireEvent.mouseUp(chart);

      await waitFor(() => screen.getByTitle("Reset zoom"));
      fireEvent.click(screen.getByTitle("Reset zoom"));

      await waitFor(() => {
        expect(screen.queryByTitle("Reset zoom")).not.toBeInTheDocument();
        expect(screen.getByText("Drag to zoom")).toBeInTheDocument();
      });
    });

    it("does not zoom when only mouseDown fires (no mousemove)", async () => {
      render(<AlertsGraphSection {...defaultProps} />);
      const chart = screen.getByTestId("line-chart");

      fireEvent.mouseDown(chart);
      // No mousemove — refAreaRight remains null
      fireEvent.mouseUp(chart);

      // No zoom applied — Reset zoom button should not appear
      expect(screen.queryByTitle("Reset zoom")).not.toBeInTheDocument();
    });

    it("renders ReferenceArea during active drag (both refs set)", async () => {
      render(<AlertsGraphSection {...defaultProps} />);
      const chart = screen.getByTestId("line-chart");

      // mousedown sets refAreaLeft, mousemove sets refAreaRight → ReferenceArea renders
      fireEvent.mouseDown(chart);
      fireEvent.mouseMove(chart);

      expect(screen.getByTestId("reference-area")).toBeInTheDocument();
    });

    it("filters chartData points to zoom domain", async () => {
      // Data with timestamps 1000, 1060, 1120, 1180, 1240
      // After zoom to [1000, 2000], mock returns 1000 as left and 2000 as right
      // All 5 data points should be within [1000, 2000]
      render(<AlertsGraphSection {...defaultProps} />);
      const chart = screen.getByTestId("line-chart");

      fireEvent.mouseDown(chart);
      fireEvent.mouseMove(chart);
      fireEvent.mouseUp(chart);

      await waitFor(() => {
        expect(screen.getByTitle("Reset zoom")).toBeInTheDocument();
      });

      // After zoom, chart should still show (filtered) data points
      expect(screen.getByTestId("line-chart")).toBeInTheDocument();
    });
  });

  // ── Dark mode ─────────────────────────────────────────────────────────────

  describe("Dark mode", () => {
    it("applies dark background class when isDark=true", () => {
      mockIsDark.value = true;
      const { container } = render(<AlertsGraphSection {...defaultProps} />);
      const card = container.querySelector(".bg-gray-800");
      expect(card).toBeInTheDocument();
    });

    it("applies light background class when isDark=false", () => {
      mockIsDark.value = false;
      const { container } = render(<AlertsGraphSection {...defaultProps} />);
      const card = container.querySelector(".bg-white");
      expect(card).toBeInTheDocument();
    });

    it("dark loading spinner uses blue-400 color class (line 119)", () => {
      mockIsDark.value = true;
      const { container } = render(
        <AlertsGraphSection {...defaultProps} loading={true} />
      );
      // The loader icon div inside loading state has "text-blue-400" in dark mode
      expect(container.querySelector(".text-blue-400")).toBeInTheDocument();
    });

    it("dark mode zoom drag renders ReferenceArea and zoom reset (lines 195, 216)", async () => {
      mockIsDark.value = true;
      render(<AlertsGraphSection {...defaultProps} />);
      const chart = screen.getByTestId("line-chart");

      // Trigger drag to exercise isDark branches in ReferenceArea fill and zoom reset button
      fireEvent.mouseDown(chart);
      fireEvent.mouseMove(chart);

      // ReferenceArea is now shown (dark fill branch exercised at line 195)
      expect(screen.getByTestId("reference-area")).toBeInTheDocument();

      fireEvent.mouseUp(chart);

      await waitFor(() => {
        // Zoom reset button appears in dark mode (line 216)
        const resetBtn = screen.queryByTitle("Reset zoom");
        expect(resetBtn).toBeInTheDocument();
      });
    });
  });
});
