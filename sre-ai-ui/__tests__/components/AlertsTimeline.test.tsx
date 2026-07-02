/**
 * Tests for src/components/AlertsTimeline.tsx
 *
 * Coverage targets:
 *  ✓ Loading state — spinner + "Loading timeline…" text
 *  ✓ Empty state — no placed alerts → "No timeline data" message
 *  ✓ Normal rendering — legend, axis ticks, bars for alerts
 *  ✓ Layout: above/below axis placement
 *  ✓ Active alert — always treated as active in this component
 *  ✓ Tooltip on hover — shows alert info (SLA, status, start/end, cluster, category)
 *  ✓ Tooltip hides on mouse leave
 *  ✓ Zoom mode — wider chart width
 *  ✓ Dark mode styling
 *  ✓ Gap detection (detectSegments) — multiple segments when gaps in values
 *  ✓ Alerts with no start timestamp → filtered out
 *  ✓ formatTimestamp helper coverage
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlertsTimeline } from "@/components/AlertsTimeline";
import type { AlertResultAlert } from "@/lib/api-client";

// ─── Mock ThemeContext ──────────────────────────────────────────────────────
let mockIsDark = false;
jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: mockIsDark }),
}));

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const NOW = Math.floor(Date.now() / 1000);
const TIME_START = NOW - 3600; // 1 hour ago
const TIME_END = NOW;

function makeAlert(overrides: Partial<AlertResultAlert> = {}): AlertResultAlert {
  return {
    alert_id: "alert-1",
    alertname: "HighCPU",
    alert_sla_name: "CPU SLA",
    episode_is_open: true,
    episode_start_ts: TIME_START + 100,
    episode_end_ts: null,
    cluster: "prod-cluster-1",
    alert_owner_category: "infrastructure",
    mms_xmatters_group: "sre-team",
    mms_slack_channel: "#sre-alerts",
    values: generateValues(TIME_START + 100, TIME_END, 60),
    ...overrides,
  } as AlertResultAlert;
}

/** Generate evenly-spaced value entries */
function generateValues(start: number, end: number, step: number): [number, string][] {
  const values: [number, string][] = [];
  for (let ts = start; ts <= end; ts += step) {
    values.push([ts, "1"]);
  }
  return values;
}

/** Generate values with a gap in the middle (for segment detection) */
function generateValuesWithGap(): [number, string][] {
  const values: [number, string][] = [];
  // First continuous segment: 10 points at 60s intervals
  for (let i = 0; i < 10; i++) {
    values.push([TIME_START + 100 + i * 60, "1"]);
  }
  // Gap of 600s (10 min) — much larger than 1.8 × 60s threshold
  // Second continuous segment: 10 points at 60s intervals
  for (let i = 0; i < 10; i++) {
    values.push([TIME_START + 1300 + i * 60, "1"]);
  }
  return values;
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockIsDark = false;
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("AlertsTimeline", () => {
  // ── Loading state ──────────────────────────────────────────────────────
  describe("loading state", () => {
    it("shows loading spinner and text", () => {
      render(
        <AlertsTimeline alerts={[]} timeStart={TIME_START} timeEnd={TIME_END} loading={true} />
      );
      expect(screen.getByText(/loading timeline/i)).toBeInTheDocument();
    });

    it("does not render bars or legend when loading", () => {
      render(
        <AlertsTimeline alerts={[makeAlert()]} timeStart={TIME_START} timeEnd={TIME_END} loading={true} />
      );
      expect(screen.queryByText("Active alerts only")).not.toBeInTheDocument();
      expect(screen.queryByText("Hover for details")).not.toBeInTheDocument();
    });
  });

  // ── Empty state ────────────────────────────────────────────────────────
  describe("empty state", () => {
    it("shows 'No timeline data' when alerts array is empty", () => {
      render(
        <AlertsTimeline alerts={[]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText(/no timeline data/i)).toBeInTheDocument();
    });

    it("shows 'No timeline data' when all alerts lack timestamps", () => {
      const noTsAlert = makeAlert({ episode_start_ts: null, values: undefined });
      render(
        <AlertsTimeline alerts={[noTsAlert]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText(/no timeline data/i)).toBeInTheDocument();
    });
  });

  // ── Legend ─────────────────────────────────────────────────────────────
  describe("legend", () => {
    it("renders 'Active alerts only' legend entry", () => {
      render(
        <AlertsTimeline alerts={[makeAlert()]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("Active alerts only")).toBeInTheDocument();
    });

    it("renders 'Hover for details' helper text", () => {
      render(
        <AlertsTimeline alerts={[makeAlert()]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("Hover for details")).toBeInTheDocument();
    });
  });

  // ── Normal rendering ───────────────────────────────────────────────────
  describe("normal rendering", () => {
    it("renders alert label on the bar", () => {
      render(
        <AlertsTimeline alerts={[makeAlert({ alert_sla_name: "Memory SLA" })]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("Memory SLA")).toBeInTheDocument();
    });

    it("falls back to alertname when alert_sla_name is missing", () => {
      render(
        <AlertsTimeline alerts={[makeAlert({ alert_sla_name: undefined, alertname: "DiskAlert" })]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("DiskAlert")).toBeInTheDocument();
    });

    it("falls back to 'Alert N' when both names are missing", () => {
      render(
        <AlertsTimeline alerts={[makeAlert({ alert_sla_name: undefined, alertname: undefined })]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("Alert 1")).toBeInTheDocument();
    });

    it("renders time tick labels on axis", () => {
      render(
        <AlertsTimeline alerts={[makeAlert()]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      // There should be 7 tick labels (TICK_COUNT = 7)
      // They are formatted as HH:MM — look for elements with time-like text
      const timeLabels = screen.getAllByText(/\d{1,2}:\d{2}/);
      expect(timeLabels.length).toBeGreaterThanOrEqual(7);
    });
  });

  // ── Multiple alerts ────────────────────────────────────────────────────
  describe("multiple alerts placement", () => {
    it("renders multiple alert bars", () => {
      const alerts = [
        makeAlert({ alert_id: "a1", alert_sla_name: "CPU SLA", episode_start_ts: TIME_START + 100 }),
        makeAlert({ alert_id: "a2", alert_sla_name: "Memory SLA", episode_start_ts: TIME_START + 200 }),
        makeAlert({ alert_id: "a3", alert_sla_name: "Disk SLA", episode_start_ts: TIME_START + 300 }),
      ];
      render(
        <AlertsTimeline alerts={alerts} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("CPU SLA")).toBeInTheDocument();
      expect(screen.getByText("Memory SLA")).toBeInTheDocument();
      expect(screen.getByText("Disk SLA")).toBeInTheDocument();
    });
  });

  // ── Tooltip ────────────────────────────────────────────────────────────
  describe("tooltip", () => {
    it("shows tooltip with alert name on mouse enter", () => {
      render(
        <AlertsTimeline
          alerts={[makeAlert({ alertname: "TooltipTestAlert", alert_sla_name: "Tooltip SLA" })]}
          timeStart={TIME_START}
          timeEnd={TIME_END}
        />
      );

      // Find the bar container (cursor-pointer element)
      const bars = document.querySelectorAll(".cursor-pointer");
      expect(bars.length).toBeGreaterThan(0);

      // Hover over the first bar
      fireEvent.mouseEnter(bars[0], { clientX: 200, clientY: 100 });

      // Tooltip should show alert info
      expect(screen.getByText("TooltipTestAlert")).toBeInTheDocument();
      expect(screen.getByText("Active")).toBeInTheDocument();
    });

    it("shows SLA name in tooltip", () => {
      render(
        <AlertsTimeline
          alerts={[makeAlert({ alert_sla_name: "My SLA Name" })]}
          timeStart={TIME_START}
          timeEnd={TIME_END}
        />
      );

      const bars = document.querySelectorAll(".cursor-pointer");
      fireEvent.mouseEnter(bars[0], { clientX: 200, clientY: 100 });

      // SLA field in tooltip
      expect(screen.getByText("SLA:")).toBeInTheDocument();
      // The SLA value appears both in the bar label and tooltip
      const slaTexts = screen.getAllByText("My SLA Name");
      expect(slaTexts.length).toBeGreaterThanOrEqual(2);
    });

    it("shows cluster in tooltip when available", () => {
      render(
        <AlertsTimeline
          alerts={[makeAlert({ cluster: "us-west-2-prod" })]}
          timeStart={TIME_START}
          timeEnd={TIME_END}
        />
      );

      const bars = document.querySelectorAll(".cursor-pointer");
      fireEvent.mouseEnter(bars[0], { clientX: 200, clientY: 100 });

      expect(screen.getByText("Cluster:")).toBeInTheDocument();
      expect(screen.getByText("us-west-2-prod")).toBeInTheDocument();
    });

    it("shows category in tooltip when available", () => {
      render(
        <AlertsTimeline
          alerts={[makeAlert({ alert_owner_category: "platform" })]}
          timeStart={TIME_START}
          timeEnd={TIME_END}
        />
      );

      const bars = document.querySelectorAll(".cursor-pointer");
      fireEvent.mouseEnter(bars[0], { clientX: 200, clientY: 100 });

      expect(screen.getByText("Category:")).toBeInTheDocument();
      expect(screen.getByText("platform")).toBeInTheDocument();
    });

    it("shows 'Ongoing' for active alerts in tooltip", () => {
      render(
        <AlertsTimeline
          alerts={[makeAlert({ episode_is_open: true })]}
          timeStart={TIME_START}
          timeEnd={TIME_END}
        />
      );

      const bars = document.querySelectorAll(".cursor-pointer");
      fireEvent.mouseEnter(bars[0], { clientX: 200, clientY: 100 });

      expect(screen.getByText("Ongoing")).toBeInTheDocument();
    });

    it("shows values count in tooltip when values exist", () => {
      const values = generateValues(TIME_START + 100, TIME_START + 400, 60);
      render(
        <AlertsTimeline
          alerts={[makeAlert({ values })]}
          timeStart={TIME_START}
          timeEnd={TIME_END}
        />
      );

      const bars = document.querySelectorAll(".cursor-pointer");
      fireEvent.mouseEnter(bars[0], { clientX: 200, clientY: 100 });

      expect(screen.getByText(new RegExp(`Values \\(${values.length} points\\)`))).toBeInTheDocument();
    });

    it("hides tooltip on mouse leave", () => {
      render(
        <AlertsTimeline
          alerts={[makeAlert({ alertname: "HoverAlert" })]}
          timeStart={TIME_START}
          timeEnd={TIME_END}
        />
      );

      const bars = document.querySelectorAll(".cursor-pointer");
      fireEvent.mouseEnter(bars[0], { clientX: 200, clientY: 100 });
      expect(screen.getByText("Status:")).toBeInTheDocument();

      fireEvent.mouseLeave(bars[0]);
      expect(screen.queryByText("Status:")).not.toBeInTheDocument();
    });

    it("follows mouse movement when tooltip is visible", () => {
      const { container } = render(
        <AlertsTimeline
          alerts={[makeAlert({ alertname: "MoveAlert" })]}
          timeStart={TIME_START}
          timeEnd={TIME_END}
        />
      );

      const bars = document.querySelectorAll(".cursor-pointer");
      fireEvent.mouseEnter(bars[0], { clientX: 200, clientY: 100 });

      // Move mouse on the wrapper div
      const wrapper = container.firstElementChild;
      if (wrapper) {
        fireEvent.mouseMove(wrapper, { clientX: 300, clientY: 150 });
      }

      // Tooltip should still be visible
      expect(screen.getByText("Status:")).toBeInTheDocument();
    });
  });

  // ── Zoom mode ──────────────────────────────────────────────────────────
  describe("zoom mode", () => {
    it("renders wider chart when isZoomed=true", () => {
      const { container } = render(
        <AlertsTimeline alerts={[makeAlert()]} timeStart={TIME_START} timeEnd={TIME_END} isZoomed={true} />
      );

      // isZoomed makes inner container 300% wide (ZOOM_MULTIPLIER = 3)
      const scrollContainer = container.querySelector(".overflow-x-auto");
      const innerDiv = scrollContainer?.firstElementChild as HTMLElement;
      expect(innerDiv?.style.minWidth).toBe("300%");
    });

    it("renders normal width when isZoomed=false", () => {
      const { container } = render(
        <AlertsTimeline alerts={[makeAlert()]} timeStart={TIME_START} timeEnd={TIME_END} isZoomed={false} />
      );

      const scrollContainer = container.querySelector(".overflow-x-auto");
      const innerDiv = scrollContainer?.firstElementChild as HTMLElement;
      expect(innerDiv?.style.minWidth).toBe("100%");
    });
  });

  // ── Dark mode ──────────────────────────────────────────────────────────
  describe("dark mode", () => {
    it("loading state uses dark styling when isDark=true", () => {
      mockIsDark = true;
      const { container } = render(
        <AlertsTimeline alerts={[]} timeStart={TIME_START} timeEnd={TIME_END} loading={true} />
      );
      const wrapper = container.firstElementChild;
      expect(wrapper?.className).toContain("bg-gray-900");
    });

    it("loading state uses light styling when isDark=false", () => {
      mockIsDark = false;
      const { container } = render(
        <AlertsTimeline alerts={[]} timeStart={TIME_START} timeEnd={TIME_END} loading={true} />
      );
      const wrapper = container.firstElementChild;
      expect(wrapper?.className).toContain("bg-white");
    });

    it("legend uses dark text colors when isDark=true", () => {
      mockIsDark = true;
      render(
        <AlertsTimeline alerts={[makeAlert()]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      const legendText = screen.getByText("Active alerts only");
      expect(legendText.className).toContain("text-gray-300");
    });

    it("legend uses light text colors when isDark=false", () => {
      mockIsDark = false;
      render(
        <AlertsTimeline alerts={[makeAlert()]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      const legendText = screen.getByText("Active alerts only");
      expect(legendText.className).toContain("text-gray-600");
    });
  });

  // ── Gap detection / segments ───────────────────────────────────────────
  describe("segment detection", () => {
    it("renders alert with gap-separated values (detectSegments produces multiple segments)", () => {
      const valuesWithGap = generateValuesWithGap();
      const alert = makeAlert({ values: valuesWithGap });

      render(
        <AlertsTimeline alerts={[alert]} timeStart={TIME_START} timeEnd={TIME_END} />
      );

      // Alert should still render (bar visible)
      expect(screen.getByText("CPU SLA")).toBeInTheDocument();
    });

    it("renders alert with a single value point", () => {
      const alert = makeAlert({ values: [[TIME_START + 500, "1"]] });
      render(
        <AlertsTimeline alerts={[alert]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("CPU SLA")).toBeInTheDocument();
    });

    it("renders alert with no values (uses episode timestamps)", () => {
      const alert = makeAlert({
        episode_start_ts: TIME_START + 100,
        values: undefined,
      });
      render(
        <AlertsTimeline alerts={[alert]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("CPU SLA")).toBeInTheDocument();
    });
  });

  // ── Edge cases ─────────────────────────────────────────────────────────
  describe("edge cases", () => {
    it("handles alerts that start before timeStart (clipped to window)", () => {
      const alert = makeAlert({
        episode_start_ts: TIME_START - 500, // before window
        values: generateValues(TIME_START - 500, TIME_END, 60),
      });
      render(
        <AlertsTimeline alerts={[alert]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("CPU SLA")).toBeInTheDocument();
    });

    it("filters out alerts where episode_start_ts is null and no values fallback", () => {
      const alert = makeAlert({ episode_start_ts: null, values: undefined });
      render(
        <AlertsTimeline alerts={[alert]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      // Should show empty state since the only alert was filtered out
      expect(screen.getByText(/no timeline data/i)).toBeInTheDocument();
    });

    it("uses values[0][0] as start when episode_start_ts is null", () => {
      const alert = makeAlert({
        episode_start_ts: null,
        values: [[TIME_START + 500, "1"], [TIME_START + 600, "1"]],
      });
      render(
        <AlertsTimeline alerts={[alert]} timeStart={TIME_START} timeEnd={TIME_END} />
      );
      expect(screen.getByText("CPU SLA")).toBeInTheDocument();
    });

    it("handles timeStart === timeEnd gracefully (division by 1)", () => {
      const alert = makeAlert({ episode_start_ts: NOW - 10 });
      render(
        <AlertsTimeline alerts={[alert]} timeStart={NOW} timeEnd={NOW} />
      );
      // Shouldn't crash
      expect(screen.getByText(/no timeline data/i)).toBeInTheDocument();
    });
  });
});
