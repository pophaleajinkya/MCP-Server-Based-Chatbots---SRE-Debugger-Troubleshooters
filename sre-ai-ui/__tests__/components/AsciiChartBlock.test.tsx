/**
 * Tests for src/components/charts/AsciiChartBlock.tsx
 *
 * Covers:
 *  - Renders content in a <pre> element
 *  - Shows provided title
 *  - Shows "Chart" as default title when title prop is omitted
 *  - Shows "Copy" button initially
 *  - Clicking copy calls navigator.clipboard.writeText with the content
 *  - Shows "Copied" immediately after clicking copy
 *  - Returns to "Copy" after 2000 ms timeout (fake timers)
 *  - Shows "ascii" label
 *  - Shows "Scroll horizontally" footer text
 */

import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";

import { AsciiChartBlock } from "@/components/charts/AsciiChartBlock";

// ── Clipboard mock ────────────────────────────────────────────────────────────

Object.assign(navigator, {
  clipboard: {
    writeText: jest.fn().mockResolvedValue(undefined),
  },
});

// ── Fake timers ───────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.useFakeTimers();
  (navigator.clipboard.writeText as jest.Mock).mockClear();
});

afterEach(() => {
  jest.useRealTimers();
});

// ── Constants ─────────────────────────────────────────────────────────────────

const SAMPLE_CONTENT = " 160 ┤ ▄█▄\n 140 ┤ ▄██\n 120 ┤ ███";

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AsciiChartBlock", () => {
  it("renders the content in a pre element", () => {
    const { container } = render(<AsciiChartBlock content={SAMPLE_CONTENT} />);
    const pre = container.querySelector("pre");
    expect(pre).toBeInTheDocument();
    expect(pre?.textContent).toBe(SAMPLE_CONTENT);
  });

  it("shows the provided title", () => {
    render(<AsciiChartBlock content={SAMPLE_CONTENT} title="CPU Usage" />);
    expect(screen.getByText("CPU Usage")).toBeInTheDocument();
  });

  it("shows 'Chart' as default title when title prop is omitted", () => {
    render(<AsciiChartBlock content={SAMPLE_CONTENT} />);
    expect(screen.getByText("Chart")).toBeInTheDocument();
  });

  it("shows 'Copy' button initially", () => {
    render(<AsciiChartBlock content={SAMPLE_CONTENT} />);
    expect(screen.getByRole("button", { name: /Copy/i })).toBeInTheDocument();
    expect(screen.queryByText("Copied")).not.toBeInTheDocument();
  });

  it("calls navigator.clipboard.writeText with the content when copy is clicked", () => {
    render(<AsciiChartBlock content={SAMPLE_CONTENT} />);
    fireEvent.click(screen.getByRole("button", { name: /Copy/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(SAMPLE_CONTENT);
  });

  it("shows 'Copied' immediately after clicking copy", () => {
    render(<AsciiChartBlock content={SAMPLE_CONTENT} />);
    fireEvent.click(screen.getByRole("button", { name: /Copy/i }));
    expect(screen.getByText("Copied")).toBeInTheDocument();
  });

  it("returns to 'Copy' after 2000 ms timeout", () => {
    render(<AsciiChartBlock content={SAMPLE_CONTENT} />);

    fireEvent.click(screen.getByRole("button", { name: /Copy/i }));
    expect(screen.getByText("Copied")).toBeInTheDocument();

    act(() => {
      jest.advanceTimersByTime(2000);
    });

    expect(screen.queryByText("Copied")).not.toBeInTheDocument();
    expect(screen.getByText("Copy")).toBeInTheDocument();
  });

  it("shows the 'ascii' label", () => {
    render(<AsciiChartBlock content={SAMPLE_CONTENT} />);
    expect(screen.getByText("ascii")).toBeInTheDocument();
  });

  it("shows 'Scroll horizontally to see full chart' footer text", () => {
    render(<AsciiChartBlock content={SAMPLE_CONTENT} />);
    expect(
      screen.getByText(/Scroll horizontally to see full chart/i)
    ).toBeInTheDocument();
  });
});
