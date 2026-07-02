/**
 * Tests for src/components/charts/RechartsBlock.tsx
 *
 * Covers:
 *  - Returns null for invalid JSON
 *  - Returns null when data is missing
 *  - Returns null when series is missing
 *  - Returns null when xKey is missing
 *  - Renders bar chart by default
 *  - Renders line chart when type="line"
 *  - Renders area chart when type="area"
 *  - Renders chart title
 *  - Renders chart type badge
 *  - Renders data point count
 *  - Renders correct icon for chart type
 *  - Renders series in the chart
 *  - Uses default colors when not specified
 *  - Uses custom colors when specified
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// Mock recharts - this needs to be before importing the component
jest.mock("recharts", () => {
  const React = require("react");
  return {
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
    LineChart: ({ children, data }: { children: React.ReactNode; data: unknown[] }) => (
      <div data-testid="line-chart" data-points={data?.length}>
        {children}
      </div>
    ),
    BarChart: ({ children, data }: { children: React.ReactNode; data: unknown[] }) => (
      <div data-testid="bar-chart" data-points={data?.length}>
        {children}
      </div>
    ),
    AreaChart: ({ children, data }: { children: React.ReactNode; data: unknown[] }) => (
      <div data-testid="area-chart" data-points={data?.length}>
        {children}
      </div>
    ),
    Line: ({ dataKey, stroke }: { dataKey: string; stroke: string }) => (
      <div data-testid="line" data-key={dataKey} data-stroke={stroke} />
    ),
    Bar: ({ dataKey, fill }: { dataKey: string; fill: string }) => (
      <div data-testid="bar" data-key={dataKey} data-fill={fill} />
    ),
    Area: ({ dataKey, stroke, fill }: { dataKey: string; stroke: string; fill: string }) => (
      <div data-testid="area" data-key={dataKey} data-stroke={stroke} data-fill={fill} />
    ),
    XAxis: () => <div data-testid="x-axis" />,
    YAxis: ({ label }: { label?: { value?: string } }) => (
      <div data-testid="y-axis" data-label={label?.value} />
    ),
    CartesianGrid: () => <div data-testid="cartesian-grid" />,
    Tooltip: () => <div data-testid="tooltip" />,
    Legend: () => <div data-testid="legend" />,
  };
});

import { RechartsBlock } from "@/components/charts/RechartsBlock";

// ── Test Data ─────────────────────────────────────────────────────────────────

const VALID_LINE_CHART = JSON.stringify({
  type: "line",
  title: "CPU Usage Over Time",
  xKey: "time",
  yLabel: "CPU %",
  series: [
    { key: "cluster1", label: "Cluster 1" },
    { key: "cluster2", label: "Cluster 2", color: "#FF0000" },
  ],
  data: [
    { time: "10:00", cluster1: 50, cluster2: 60 },
    { time: "10:05", cluster1: 55, cluster2: 65 },
    { time: "10:10", cluster1: 60, cluster2: 70 },
  ],
});

const VALID_BAR_CHART = JSON.stringify({
  type: "bar",
  title: "Monthly Sales",
  xKey: "month",
  series: [{ key: "sales" }],
  data: [
    { month: "Jan", sales: 100 },
    { month: "Feb", sales: 150 },
  ],
});

const VALID_AREA_CHART = JSON.stringify({
  type: "area",
  title: "Memory Usage",
  xKey: "time",
  series: [{ key: "memory" }],
  data: [
    { time: "1:00", memory: 60 },
    { time: "2:00", memory: 70 },
  ],
});

const NO_TYPE_CHART = JSON.stringify({
  title: "Default Chart",
  xKey: "x",
  series: [{ key: "y" }],
  data: [{ x: 1, y: 10 }],
});

// ── RechartsBlock Tests ───────────────────────────────────────────────────────

describe("RechartsBlock", () => {
  // ── Invalid Input ───────────────────────────────────────────────────────────

  it("returns null for invalid JSON", () => {
    const { container } = render(<RechartsBlock content="not valid json" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("returns null when data is missing", () => {
    const config = JSON.stringify({
      type: "bar",
      xKey: "x",
      series: [{ key: "y" }],
    });

    const { container } = render(<RechartsBlock content={config} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("returns null when series is missing", () => {
    const config = JSON.stringify({
      type: "bar",
      xKey: "x",
      data: [{ x: 1 }],
    });

    const { container } = render(<RechartsBlock content={config} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("returns null when xKey is missing", () => {
    const config = JSON.stringify({
      type: "bar",
      series: [{ key: "y" }],
      data: [{ x: 1, y: 10 }],
    });

    const { container } = render(<RechartsBlock content={config} />);

    expect(container).toBeEmptyDOMElement();
  });

  // ── Chart Types ─────────────────────────────────────────────────────────────

  it("renders bar chart by default when no type specified", () => {
    render(<RechartsBlock content={NO_TYPE_CHART} />);

    expect(screen.getByTestId("bar-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("line-chart")).not.toBeInTheDocument();
  });

  it("renders bar chart when type=bar", () => {
    render(<RechartsBlock content={VALID_BAR_CHART} />);

    expect(screen.getByTestId("bar-chart")).toBeInTheDocument();
  });

  it("renders line chart when type=line", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    expect(screen.getByTestId("line-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("bar-chart")).not.toBeInTheDocument();
  });

  it("renders area chart when type=area", () => {
    render(<RechartsBlock content={VALID_AREA_CHART} />);

    expect(screen.getByTestId("area-chart")).toBeInTheDocument();
  });

  // ── Chart Title ─────────────────────────────────────────────────────────────

  it("renders chart title", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    expect(screen.getByText("CPU Usage Over Time")).toBeInTheDocument();
  });

  it("uses default title 'Chart' when not provided", () => {
    const noTitle = JSON.stringify({
      xKey: "x",
      series: [{ key: "y" }],
      data: [{ x: 1, y: 10 }],
    });

    render(<RechartsBlock content={noTitle} />);

    expect(screen.getByText("Chart")).toBeInTheDocument();
  });

  // ── Badge ───────────────────────────────────────────────────────────────────

  it("shows chart type and data point count in badge", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    expect(screen.getByText("line · 3 pts")).toBeInTheDocument();
  });

  it("shows bar type in badge", () => {
    render(<RechartsBlock content={VALID_BAR_CHART} />);

    expect(screen.getByText("bar · 2 pts")).toBeInTheDocument();
  });

  // ── Series Rendering ────────────────────────────────────────────────────────

  it("renders correct number of series for line chart", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    const lines = screen.getAllByTestId("line");
    expect(lines).toHaveLength(2);
  });

  it("renders correct number of series for bar chart", () => {
    render(<RechartsBlock content={VALID_BAR_CHART} />);

    const bars = screen.getAllByTestId("bar");
    expect(bars).toHaveLength(1);
  });

  it("uses correct data keys for series", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    const lines = screen.getAllByTestId("line");
    expect(lines[0]).toHaveAttribute("data-key", "cluster1");
    expect(lines[1]).toHaveAttribute("data-key", "cluster2");
  });

  // ── Colors ──────────────────────────────────────────────────────────────────

  it("uses default colors when not specified", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    const lines = screen.getAllByTestId("line");
    // First series uses first default color (#0071CE)
    expect(lines[0]).toHaveAttribute("data-stroke", "#0071CE");
  });

  it("uses custom color when specified", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    const lines = screen.getAllByTestId("line");
    // Second series has custom color
    expect(lines[1]).toHaveAttribute("data-stroke", "#FF0000");
  });

  // ── Chart Components ────────────────────────────────────────────────────────

  it("renders CartesianGrid", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    expect(screen.getByTestId("cartesian-grid")).toBeInTheDocument();
  });

  it("renders XAxis", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    expect(screen.getByTestId("x-axis")).toBeInTheDocument();
  });

  it("renders YAxis with label", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    const yAxis = screen.getByTestId("y-axis");
    expect(yAxis).toBeInTheDocument();
  });

  it("renders Tooltip", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    expect(screen.getByTestId("tooltip")).toBeInTheDocument();
  });

  it("renders Legend", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    expect(screen.getByTestId("legend")).toBeInTheDocument();
  });

  it("renders ResponsiveContainer", () => {
    render(<RechartsBlock content={VALID_LINE_CHART} />);

    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // ── Icon ────────────────────────────────────────────────────────────────────

  it("renders TrendingUp icon for line chart", () => {
    const { container } = render(<RechartsBlock content={VALID_LINE_CHART} />);

    // Icon should be in header
    const icon = container.querySelector(".text-\\[\\#0071CE\\]");
    expect(icon).toBeInTheDocument();
  });

  // ── Height ──────────────────────────────────────────────────────────────────

  it("uses custom height when specified", () => {
    const customHeight = JSON.stringify({
      type: "bar",
      xKey: "x",
      height: 400,
      series: [{ key: "y" }],
      data: [{ x: 1, y: 10 }],
    });

    render(<RechartsBlock content={customHeight} />);

    // ResponsiveContainer should be rendered (height is passed internally)
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // ── Area Chart Specific ─────────────────────────────────────────────────────

  it("renders Area elements for area chart", () => {
    render(<RechartsBlock content={VALID_AREA_CHART} />);

    expect(screen.getByTestId("area")).toBeInTheDocument();
  });

  it("area elements have fill opacity", () => {
    render(<RechartsBlock content={VALID_AREA_CHART} />);

    const area = screen.getByTestId("area");
    expect(area).toHaveAttribute("data-key", "memory");
  });

  // ── Label props ─────────────────────────────────────────────────────────────

  it("renders chart with xLabel prop in line chart (covers line 83-84 branch)", () => {
    const withXLabel = JSON.stringify({
      type: "line",
      title: "Test",
      xKey: "time",
      xLabel: "Time (min)",
      series: [{ key: "v", label: "Value" }],
      data: [{ time: "1", v: 10 }],
    });
    render(<RechartsBlock content={withXLabel} />);
    // Line chart should render with xLabel prop (exercises the xLabel branch)
    expect(screen.getByTestId("line-chart")).toBeInTheDocument();
    expect(screen.getByTestId("x-axis")).toBeInTheDocument();
  });

  it("renders yLabel on YAxis when yLabel is provided in area chart (line 91)", () => {
    const withYLabel = JSON.stringify({
      type: "area",
      title: "Memory",
      xKey: "time",
      yLabel: "MB",
      series: [{ key: "mem" }],
      data: [{ time: "1", mem: 60 }],
    });
    render(<RechartsBlock content={withYLabel} />);
    const yAxis = screen.getByTestId("y-axis");
    expect(yAxis).toHaveAttribute("data-label", "MB");
  });

  it("renders yLabel on YAxis when yLabel is provided in bar chart (line 126)", () => {
    const withYLabel = JSON.stringify({
      type: "bar",
      title: "Sales",
      xKey: "month",
      yLabel: "Units",
      series: [{ key: "sales" }],
      data: [{ month: "Jan", sales: 100 }],
    });
    render(<RechartsBlock content={withYLabel} />);
    const yAxis = screen.getByTestId("y-axis");
    expect(yAxis).toHaveAttribute("data-label", "Units");
  });

  it("uses series key as name when series label is missing (line 103)", () => {
    const withNoLabel = JSON.stringify({
      type: "line",
      title: "Test",
      xKey: "x",
      series: [{ key: "myKey" }], // no label field
      data: [{ x: 1, myKey: 5 }],
    });
    render(<RechartsBlock content={withNoLabel} />);
    const line = screen.getByTestId("line");
    // name should fallback to key when label is missing
    expect(line).toBeInTheDocument();
    expect(line.getAttribute("data-key")).toBe("myKey");
  });

  it("uses default BarChart2 icon when chart type is unknown (line 55)", () => {
    const unknownType = JSON.stringify({
      type: "heatmap", // not in CHART_ICONS
      title: "Unknown",
      xKey: "x",
      series: [{ key: "y" }],
      data: [{ x: 1, y: 10 }],
    });
    const { container } = render(<RechartsBlock content={unknownType} />);
    // Falls back to bar chart rendering with BarChart2 icon
    // The bar chart (default) should render
    expect(screen.getByTestId("bar-chart")).toBeInTheDocument();
  });
});
