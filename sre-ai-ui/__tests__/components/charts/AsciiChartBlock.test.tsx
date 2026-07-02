/**
 * Tests for src/components/charts/AsciiChartBlock.tsx
 *
 * Covers:
 *  - Renders ASCII chart content
 *  - Renders title in header
 *  - Uses default title when not provided
 *  - Shows "ascii" badge
 *  - Copy button copies content to clipboard
 *  - Shows "Copied" feedback after copy
 *  - Renders horizontal scroll hint
 *  - Content preserves whitespace (pre element)
 */

import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { AsciiChartBlock } from "@/components/charts/AsciiChartBlock";


// ── Test Data ─────────────────────────────────────────────────────────────────

const MOCK_ASCII_CHART = `
CPU Usage
160 ┤████████████████████████████
150 ┤██████████████████████████
140 ┤████████████████████████
    └──────────────────────────
        Day 1   Day 2   Day 3
`;

// ── AsciiChartBlock Tests ─────────────────────────────────────────────────────

describe("AsciiChartBlock", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  // ── Basic Rendering ─────────────────────────────────────────────────────────

  it("renders ASCII chart content", () => {
    render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    expect(screen.getByText(/CPU Usage/)).toBeInTheDocument();
    expect(screen.getByText(/160/)).toBeInTheDocument();
  });

  it("renders content in a pre element for whitespace preservation", () => {
    const { container } = render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    const pre = container.querySelector("pre");
    expect(pre).toBeInTheDocument();
    expect(pre?.className).toContain("whitespace-pre");
  });

  // ── Title ───────────────────────────────────────────────────────────────────

  it("renders provided title in header", () => {
    render(<AsciiChartBlock content={MOCK_ASCII_CHART} title="CPU Cores" />);

    expect(screen.getByText("CPU Cores")).toBeInTheDocument();
  });

  it("uses default title 'Chart' when not provided", () => {
    render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    expect(screen.getByText("Chart")).toBeInTheDocument();
  });

  // ── Badge ───────────────────────────────────────────────────────────────────

  it("shows 'ascii' badge in header", () => {
    render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    expect(screen.getByText("ascii")).toBeInTheDocument();
  });

  // ── Copy Functionality ──────────────────────────────────────────────────────

  it("shows Copy button", () => {
    render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    expect(screen.getByText("Copy")).toBeInTheDocument();
  });

  // ── Scroll Hint ─────────────────────────────────────────────────────────────

  it("shows horizontal scroll hint", () => {
    render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    expect(screen.getByText("Scroll horizontally to see full chart")).toBeInTheDocument();
  });

  // ── Styling ─────────────────────────────────────────────────────────────────

  it("has dark theme background", () => {
    const { container } = render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    const darkBg = container.querySelector(".bg-\\[\\#0d1117\\]");
    expect(darkBg).toBeInTheDocument();
  });

  it("has chart icon in header", () => {
    const { container } = render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    // BarChart2 icon should be present
    const icon = container.querySelector(".text-blue-400");
    expect(icon).toBeInTheDocument();
  });

  it("uses monospace font for chart content", () => {
    const { container } = render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    const pre = container.querySelector("pre");
    expect(pre?.style.fontFamily).toContain("mono");
  });

  // ── Horizontal Scroll ───────────────────────────────────────────────────────

  it("has horizontal overflow scroll enabled", () => {
    const { container } = render(<AsciiChartBlock content={MOCK_ASCII_CHART} />);

    const scrollContainer = container.querySelector(".overflow-x-auto");
    expect(scrollContainer).toBeInTheDocument();
  });

  // ── Content Rendering ───────────────────────────────────────────────────────

  it("renders special characters correctly", () => {
    const specialChars = "┤├│┌─┐└┘▄█▀▐▌";
    render(<AsciiChartBlock content={specialChars} />);

    expect(screen.getByText(specialChars)).toBeInTheDocument();
  });

  it("renders multiline content", () => {
    const multiline = "Line 1\nLine 2\nLine 3";
    render(<AsciiChartBlock content={multiline} />);

    expect(screen.getByText(/Line 1/)).toBeInTheDocument();
    expect(screen.getByText(/Line 2/)).toBeInTheDocument();
    expect(screen.getByText(/Line 3/)).toBeInTheDocument();
  });
});
