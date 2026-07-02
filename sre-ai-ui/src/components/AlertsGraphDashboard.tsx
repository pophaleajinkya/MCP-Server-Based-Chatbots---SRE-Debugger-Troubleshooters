"use client";

import { AlertsGraphSection, type GraphDataPoint } from "@/components/AlertsGraphSection";
import { AlertsMultiLineGraphSection, type MultiSeriesGraphData } from "@/components/AlertsMultiLineGraphSection";

// ─── Types ──────────────────────────────────────────────────────────────────

export type { GraphDataPoint, MultiSeriesGraphData };

export interface GraphSectionData {
  data: GraphDataPoint[];
  loading: boolean;
  error: string | null;
}

export interface MultiSeriesSectionData {
  data: MultiSeriesGraphData;
  loading: boolean;
  error: string | null;
}

interface AlertsGraphDashboardProps {
  section1: GraphSectionData;
  section2: MultiSeriesSectionData;
  section3: MultiSeriesSectionData;
}

// ─── Component ──────────────────────────────────────────────────────────────

export function AlertsGraphDashboard({ section1, section2, section3 }: AlertsGraphDashboardProps) {
  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-auto">
      {/* Row 1: 2 columns */}
      <div className="grid grid-cols-2 gap-4" style={{ minHeight: 320 }}>
        {/* Section 1 — single line: total firing alerts */}
        <div className="min-h-[300px]">
          <AlertsGraphSection
            title="Intl SRE Golden Signals — Firing Alerts"
            data={section1.data}
            loading={section1.loading}
            error={section1.error}
            lineColor="#ef4444"
            yAxisLabel="Count"
          />
        </div>

        {/* Section 2 — multi-line: firing alerts by alert_type */}
        <div className="min-h-[300px]">
          <AlertsMultiLineGraphSection
            title="Firing Alerts by Alert Type"
            data={section2.data}
            loading={section2.loading}
            error={section2.error}
            yAxisLabel="Count"
          />
        </div>
      </div>

      {/* Row 2: full width — multi-line: firing alerts by alert_type + alert_sla_name */}
      <div style={{ minHeight: 520 }}>
        <AlertsMultiLineGraphSection
          title="Firing Alerts by Alert Type & SLA Name"
          data={section3.data}
          loading={section3.loading}
          error={section3.error}
          yAxisLabel="Count"
        />
      </div>
    </div>
  );
}
