import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import HealthReportModal from "@/components/HealthReportModal";

// ─── Mock ThemeContext ────────────────────────────────────────────────────────

jest.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: true, theme: "dark", toggleTheme: jest.fn() }),
}));

// ─── Mock health data (from lib/health-report-mock-data.ts structure) ─────────

const MOCK_HEALTH_DATA = {
  namespace: "intl-sre",
  app_filter: "signal-api-prod",
  checks_requested: ["all"],
  overall_status: "unhealthy",
  results: {
    "signal-api-prod": {
      "eus2-prod-a31": {
        cluster_id: "eus2-prod-a31",
        namespace: "intl-sre",
        app: "signal-api-prod",
        overall_status: "unhealthy",
        deployment_discovery: {
          deployments: ["signal-api-prod"],
          strategy: "standard",
          method: "prometheus",
        },
        checks: {
          cpu: {
            status: "healthy",
            containers: [
              {
                pod: "signal-api-prod-65ff968f9c-z7dvt",
                container: "signal-api-prod",
                cpu_usage_ratio: 0.0015,
                cpu_usage_percent: 0.15,
                status: "healthy",
                is_outlier: false,
              },
              {
                pod: "signal-api-prod-65ff968f9c-hqvh6",
                container: "signal-api-prod",
                cpu_usage_ratio: 0.0014,
                cpu_usage_percent: 0.14,
                status: "healthy",
                is_outlier: false,
              },
            ],
            istio_proxy_containers: [
              {
                pod: "signal-api-prod-65ff968f9c-z7dvt",
                container: "istio-proxy",
                cpu_usage_ratio: 0.0083,
                cpu_usage_percent: 0.83,
                status: "healthy",
              },
            ],
          },
          memory: {
            status: "healthy",
            containers: [
              {
                pod: "signal-api-prod-65ff968f9c-z7dvt",
                container: "signal-api-prod",
                memory_usage_ratio: 0.025,
                memory_usage_percent: 2.5,
                status: "healthy",
                is_outlier: false,
              },
            ],
            istio_proxy_containers: [
              {
                pod: "signal-api-prod-65ff968f9c-z7dvt",
                container: "istio-proxy",
                memory_usage_ratio: 0.225,
                memory_usage_percent: 22.5,
                status: "healthy",
              },
            ],
          },
          restarts: {
            status: "healthy",
            restarts: [],
          },
          node_cpu: {
            status: "healthy",
            nodes: [],
          },
          npd: {
            status: "healthy",
            events: [],
            message: "No NPD events detected",
          },
          scale_events: {
            status: "stable",
            current_pod_count: 2,
            baseline_pod_count: 2.0,
            new_pods: [],
            scale_change: 0.0,
            new_pods_count: 0,
            scale_change_percent: 0.0,
            message: "Pod count stable at 2 pods",
          },
          pod_age: {
            pods: [
              {
                pod: "signal-api-prod-65ff968f9c-hqvh6",
                age_hours: 59.89,
                age_minutes: 3593.2,
                start_time: "2026-03-17 10:03:54 UTC",
              },
            ],
            distribution: { new: 0, recent: 0, mature: 0, old: 2 },
            total_pods: 2,
            average_age_hours: 85.17,
            oldest_pod_age_hours: 110.46,
            newest_pod_age_hours: 59.89,
          },
          pod_rescheduling: {
            status: "stable",
            recently_started_pods: [],
            recently_started_count: 0,
            total_pod_count: 2,
            activity_type: "none",
            diagnosis:
              "No recent pod activity. All 2 pods are stable (started more than 60 minutes ago).",
            signals_detected: [],
            baseline_pod_count: 2.0,
            percentage_recent: 0.0,
            nodes_involved: [],
            nodes_involved_count: 0,
          },
          replica_readiness: {
            status: "healthy",
            desired_replicas: 2,
            ready_replicas: 2,
            unavailable_replicas: 0,
            deployment: "signal-api-prod",
            message: "All 2 replicas ready",
          },
          rollout: {
            rollout_detected: false,
            upgrade_detected: false,
            activity_type: "none",
            message: "No rollout activity detected in last 6.0 hours",
          },
          secrets: {
            status: "healthy",
            failed_secrets: [],
            message: "All external secrets for signal-api-prod are healthy",
          },
          config: {
            status: "healthy",
            ccm_enabled: false,
            configmaps_checked: [],
            anomalies: [],
            message: "CCM not enabled for this app - skipping configmap checks",
          },
          istio_client_success: {
            status: "healthy",
            success_rate: 1.0,
            success_rate_percent: 100.0,
          },
          istio_server_success: {
            status: "healthy",
            success_rate: 1.0,
            success_rate_percent: 100.0,
            error_rate_percent: 0.0,
          },
          istio_traffic_spike: {
            status: "healthy",
            request_rate: 1.4,
            response_code_breakdown_percent: {
              "2xx": 90.48,
              "3xx": 9.52,
              "4xx": 0.0,
              "5xx": 0.0,
            },
            non_2xx_rate: 0.1333,
            non_2xx_percent: 9.52,
            positive_anomaly: true,
            message: "Non-2xx error rate improvement",
            prometheus_url:
              "https://prom-istio.eus2-prod-a31.cluster.k8s.us.walmart.net",
          },
          istio_client_latency: {
            status: "healthy",
            p95_latency_ms: 300.0,
          },
          istio_server_latency: {
            status: "unhealthy",
            p95_latency_ms: 355.0,
            anomaly_detected: true,
            anomaly_details: {
              current_value: 355.0,
              baseline_value: null,
              deviation_percent: null,
              is_anomaly: true,
              day_over_day_result: {
                current_value: 355.0,
                clean_baseline: 86.025028,
                deviation_percent: 312.67,
                is_anomaly: true,
                comparison_type: "multi_day_zscore",
                anomaly_type: "degradation",
                anomaly_reason: "Metric increased by 312.7% vs 2-day clean baseline",
              },
              rolling_result: {
                current_value: 355.0,
                baseline_value: 213.85,
                deviation_percent: 66.01,
                is_anomaly: true,
                anomaly_type: "degradation",
                anomaly_reason: "Metric increased by 66.0% from 6h baseline",
              },
              anomaly_reason:
                "Historical: Metric increased by 312.7% vs 2-day clean baseline | Rolling: Metric increased by 66.0% from 6h baseline",
            },
            issue:
              "Server P95 latency spike detected: 355.0ms - YOUR app is processing requests slower than baseline",
            prometheus_url:
              "https://prom-istio.eus2-prod-a31.cluster.k8s.us.walmart.net",
          },
          istio_retries: {
            status: "healthy",
            retry_rate: 0.0,
            retry_count_5m: 0.0,
            prometheus_url:
              "https://prom-istio.eus2-prod-a31.cluster.k8s.us.walmart.net",
            message: "No client retries",
          },
          istio_rate_limiting: {
            status: "healthy",
            rate_limited: false,
            limited_rate: 0.0,
            passed_rate: 0.0,
            message: "No rate limiting",
          },
        },
        checks_performed: [
          "cpu", "memory", "restarts", "node_cpu", "npd", "scale_events",
          "pod_age", "pod_rescheduling", "replica_readiness", "rollout",
          "secrets", "config", "istio_client_success", "istio_server_success",
          "istio_traffic_spike", "istio_client_latency", "istio_server_latency",
          "istio_retries", "istio_rate_limiting",
        ],
        anomaly_sequence: [{ check: "istio_server_latency", started_at: null }],
      },
      "scus-prod-a74": {
        cluster_id: "scus-prod-a74",
        namespace: "intl-sre",
        app: "signal-api-prod",
        overall_status: "healthy",
        deployment_discovery: {
          deployments: ["signal-api-prod"],
          strategy: "standard",
          method: "prometheus",
        },
        checks: {
          cpu: {
            status: "healthy",
            containers: [
              {
                pod: "signal-api-prod-75d5fdf88c-5d57h",
                container: "signal-api-prod",
                cpu_usage_ratio: 0.0009,
                cpu_usage_percent: 0.09,
                status: "healthy",
                is_outlier: false,
              },
            ],
            istio_proxy_containers: [],
          },
          memory: {
            status: "healthy",
            containers: [
              {
                pod: "signal-api-prod-75d5fdf88c-5d57h",
                container: "signal-api-prod",
                memory_usage_ratio: 0.038,
                memory_usage_percent: 3.8,
                status: "healthy",
                is_outlier: false,
              },
            ],
            istio_proxy_containers: [],
          },
          restarts: { status: "healthy", restarts: [] },
          node_cpu: { status: "healthy", nodes: [] },
          npd: { status: "healthy", events: [], message: "No NPD events detected" },
          scale_events: {
            status: "stable",
            current_pod_count: 2,
            baseline_pod_count: 2.0,
            new_pods: [],
            scale_change: 0.0,
            new_pods_count: 0,
            scale_change_percent: 0.0,
            message: "Pod count stable at 2 pods",
          },
          pod_age: {
            pods: [],
            distribution: { new: 0, recent: 0, mature: 0, old: 2 },
            total_pods: 2,
            average_age_hours: 110.15,
            oldest_pod_age_hours: 110.42,
            newest_pod_age_hours: 109.87,
          },
          pod_rescheduling: {
            status: "stable",
            recently_started_pods: [],
            recently_started_count: 0,
            total_pod_count: 2,
            activity_type: "none",
            diagnosis: "No recent pod activity.",
            signals_detected: [],
            baseline_pod_count: 2.0,
            percentage_recent: 0.0,
            nodes_involved: [],
            nodes_involved_count: 0,
          },
          replica_readiness: {
            status: "healthy",
            desired_replicas: 2,
            ready_replicas: 2,
            unavailable_replicas: 0,
            deployment: "signal-api-prod",
            message: "All 2 replicas ready",
          },
          rollout: {
            rollout_detected: false,
            upgrade_detected: false,
            activity_type: "none",
            message: "No rollout activity detected in last 6.0 hours",
          },
          secrets: {
            status: "healthy",
            failed_secrets: [],
            message: "All external secrets for signal-api-prod are healthy",
          },
          config: {
            status: "healthy",
            ccm_enabled: false,
            configmaps_checked: [],
            anomalies: [],
            message: "CCM not enabled for this app - skipping configmap checks",
          },
          istio_client_success: {
            status: "healthy",
            success_rate: 1.0,
            success_rate_percent: 100.0,
          },
          istio_server_success: {
            status: "healthy",
            success_rate: 1.0,
            success_rate_percent: 100.0,
            error_rate_percent: 0.0,
          },
          istio_traffic_spike: {
            status: "healthy",
            request_rate: 1.27,
            response_code_breakdown_percent: {
              "5xx": 0.0,
              "2xx": 81.58,
              "3xx": 18.42,
              "4xx": 0.0,
            },
            non_2xx_rate: 0.2333,
            non_2xx_percent: 18.42,
            positive_anomaly: true,
            message: "Non-2xx error rate improvement",
            prometheus_url:
              "https://prom-istio.scus-prod-a74.cluster.k8s.us.walmart.net",
          },
          istio_client_latency: {
            status: "healthy",
            p95_latency_ms: 94.17,
          },
          istio_server_latency: {
            status: "healthy",
            p95_latency_ms: 89.58,
          },
          istio_retries: {
            status: "healthy",
            retry_rate: 0.0,
            retry_count_5m: 0.0,
            prometheus_url:
              "https://prom-istio.scus-prod-a74.cluster.k8s.us.walmart.net",
            message: "No client retries",
          },
          istio_rate_limiting: {
            status: "healthy",
            rate_limited: false,
            limited_rate: 0.0,
            passed_rate: 0.0,
            message: "No rate limiting",
          },
        },
        checks_performed: [
          "cpu", "memory", "restarts", "node_cpu", "npd", "scale_events",
          "pod_age", "pod_rescheduling", "replica_readiness", "rollout",
          "secrets", "config", "istio_client_success", "istio_server_success",
          "istio_traffic_spike", "istio_client_latency", "istio_server_latency",
          "istio_retries", "istio_rate_limiting",
        ],
        anomaly_sequence: [],
      },
    },
  },
  summary: { healthy: 1, degraded: 0, partial_error: 0, unhealthy: 1, error: 0 },
  total_checks: 2,
  cluster_scope: {
    total_clusters: 2,
    unhealthy_clusters: ["eus2-prod-a31"],
    healthy_clusters: ["scus-prod-a74"],
    scope: "partial",
  },
  incident_timeline: [
    {
      started_at: null,
      app: "signal-api-prod",
      cluster: "eus2-prod-a31",
      check: "istio_server_latency",
    },
  ],
};

const MOCK_HEALTH_DATA_ALL_HEALTHY = {
  ...MOCK_HEALTH_DATA,
  overall_status: "healthy",
  incident_timeline: [],
  cluster_scope: {
    ...MOCK_HEALTH_DATA.cluster_scope,
    unhealthy_clusters: [],
    healthy_clusters: ["eus2-prod-a31", "scus-prod-a74"],
  },
  results: {
    "signal-api-prod": {
      "eus2-prod-a31": {
        ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
        overall_status: "healthy",
      },
      "scus-prod-a74": {
        ...MOCK_HEALTH_DATA.results["signal-api-prod"]["scus-prod-a74"],
        overall_status: "healthy",
      },
    },
  },
};

// ─── Default app prop ─────────────────────────────────────────────────────────

function makeApp(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: "signal-api-prod",
    namespace: "intl-sre",
    appName: "signal-api-prod",
    slackChannels: [],
    xmattersGroups: [],
    emails: [],
    ...overrides,
  };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function mockFetchSuccess(data: unknown = MOCK_HEALTH_DATA) {
  (global.fetch as jest.Mock).mockResolvedValue({
    ok: true,
    status: 200,
    json: jest.fn().mockResolvedValue(data),
    text: jest.fn().mockResolvedValue(JSON.stringify(data)),
  } as unknown as Response);
}

function mockFetchError(status = 500, statusText = "Internal Server Error") {
  (global.fetch as jest.Mock).mockResolvedValue({
    ok: false,
    status,
    statusText,
    json: jest.fn().mockResolvedValue({}),
    text: jest.fn().mockResolvedValue(""),
  } as unknown as Response);
}

function mockFetchNetworkError() {
  (global.fetch as jest.Mock).mockRejectedValue(new Error("Network failure"));
}

// ─── Setup / Teardown ─────────────────────────────────────────────────────────

beforeAll(() => {
  // Ensure fetch is available as a jest.fn() in jsdom
  global.fetch = jest.fn();
});

beforeEach(() => {
  (global.fetch as jest.Mock).mockReset();
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("HealthReportModal", () => {
  // ── Loading state ────────────────────────────────────────────────────────────

  describe("loading state", () => {
    it("shows loading spinner while fetching", async () => {
      // Keep fetch pending so the component stays in the loading state.
      (global.fetch as jest.Mock).mockReturnValue(new Promise(() => {}));

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      expect(
        screen.getByText(/loading health report for signal-api-prod/i)
      ).toBeInTheDocument();
    });

    it("renders the app name in the loading message", async () => {
      (global.fetch as jest.Mock).mockReturnValue(new Promise(() => {}));

      render(
        <HealthReportModal
          app={makeApp({ appName: "my-special-app", name: "my-special-app" })}
          onClose={jest.fn()}
        />
      );

      expect(
        screen.getByText(/loading health report for my-special-app/i)
      ).toBeInTheDocument();
    });

    it("uses app.name when appName is not provided", async () => {
      (global.fetch as jest.Mock).mockReturnValue(new Promise(() => {}));

      render(
        <HealthReportModal
          app={makeApp({ appName: null, name: "fallback-app" })}
          onClose={jest.fn()}
        />
      );

      expect(
        screen.getByText(/loading health report for fallback-app/i)
      ).toBeInTheDocument();
    });
  });

  // ── Error state ──────────────────────────────────────────────────────────────

  describe("error state", () => {
    it("shows error message when fetch returns non-ok status", async () => {
      mockFetchError(503, "Service Unavailable");

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getByText(/failed to load health report/i)
        ).toBeInTheDocument();
      });
    });

    it("displays the error detail text on fetch failure", async () => {
      mockFetchError(503, "Service Unavailable");

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getByText(/health api error: 503 service unavailable/i)
        ).toBeInTheDocument();
      });
    });

    it("shows error state on network failure", async () => {
      mockFetchNetworkError();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getByText(/failed to load health report/i)
        ).toBeInTheDocument();
      });
    });

    it("shows the network error message text", async () => {
      mockFetchNetworkError();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(/network failure/i)).toBeInTheDocument();
      });
    });

    it("renders a Close button in error state that calls onClose", async () => {
      mockFetchError();
      const onClose = jest.fn();

      render(<HealthReportModal app={makeApp()} onClose={onClose} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /close/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /close/i }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  // ── Successful render ────────────────────────────────────────────────────────

  describe("successful render with data", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders the app name in the modal header", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        // The header renders the app name prominently
        const headings = screen.getAllByText("signal-api-prod");
        expect(headings.length).toBeGreaterThan(0);
      });
    });

    it("renders the namespace in the modal header", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("intl-sre")).toBeInTheDocument();
      });
    });

    it("renders the close button with aria-label in main view", async () => {
      const onClose = jest.fn();
      render(<HealthReportModal app={makeApp()} onClose={onClose} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /close/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /close/i }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("renders cluster tab buttons", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("eus2-prod-a31")).toBeInTheDocument();
        expect(screen.getByText("scus-prod-a74")).toBeInTheDocument();
      });
    });

    it("renders compare button when there are multiple clusters", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });
    });

    it("renders cluster status badges", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        // Status badges appear for each cluster in the tabs
        const unhealthyBadges = screen.getAllByText("unhealthy");
        expect(unhealthyBadges.length).toBeGreaterThan(0);
        const healthyBadges = screen.getAllByText("healthy");
        expect(healthyBadges.length).toBeGreaterThan(0);
      });
    });
  });

  // ── Summary banner ───────────────────────────────────────────────────────────

  describe("summary banner", () => {
    it("shows issue summary when overall status is unhealthy", async () => {
      mockFetchSuccess(MOCK_HEALTH_DATA);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        // The incident timeline has one entry for istio_server_latency in eus2-prod-a31
        expect(
          screen.getByText(/istio server latency issue in eus2-prod-a31/i)
        ).toBeInTheDocument();
      });
    });

    it("shows all-healthy message when overall status is healthy", async () => {
      mockFetchSuccess(MOCK_HEALTH_DATA_ALL_HEALTHY);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getByText(/all clusters healthy/i)
        ).toBeInTheDocument();
      });
    });

    it("shows unhealthy cluster summary when no incident timeline entries", async () => {
      const dataWithNoTimeline = {
        ...MOCK_HEALTH_DATA,
        incident_timeline: [],
        cluster_scope: {
          ...MOCK_HEALTH_DATA.cluster_scope,
          unhealthy_clusters: ["eus2-prod-a31"],
        },
      };
      mockFetchSuccess(dataWithNoTimeline);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getByText(/1 cluster\(s\) unhealthy/i)
        ).toBeInTheDocument();
      });
    });
  });

  // ── Header statistics ────────────────────────────────────────────────────────

  describe("header statistics", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders 'clusters healthy' label", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("clusters healthy")).toBeInTheDocument();
      });
    });

    it("renders 'total pods' label", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("total pods")).toBeInTheDocument();
      });
    });

    it("renders 'req/s combined' label", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("req/s combined")).toBeInTheDocument();
      });
    });

    it("renders the health gauge percentage text", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        // CircularGauge renders a percentage value
        expect(screen.getByText("health")).toBeInTheDocument();
      });
    });
  });

  // ── Section headings ─────────────────────────────────────────────────────────

  describe("check section headings", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders INFRASTRUCTURE section heading", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("INFRASTRUCTURE")).toBeInTheDocument();
      });
    });

    it("renders POD HEALTH section heading", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("POD HEALTH")).toBeInTheDocument();
      });
    });

    it("renders ISTIO / NETWORK section heading", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("ISTIO / NETWORK")).toBeInTheDocument();
      });
    });

    it("renders checks passed counters for sections", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        // e.g. "5/5 checks passed" or similar
        const checkCounters = screen.getAllByText(/checks passed/i);
        expect(checkCounters.length).toBeGreaterThan(0);
      });
    });
  });

  // ── Check cards ──────────────────────────────────────────────────────────────

  describe("check card display names", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders CPU check card title", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("CPU")).toBeInTheDocument();
      });
    });

    it("renders Memory check card title", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Memory")).toBeInTheDocument();
      });
    });

    it("renders Restarts check card title", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Restarts")).toBeInTheDocument();
      });
    });

    it("renders NPD check card title", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("NPD")).toBeInTheDocument();
      });
    });

    it("renders Replica Readiness check card title", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Replica Readiness")).toBeInTheDocument();
      });
    });

    it("renders Rollout check card title", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Rollout")).toBeInTheDocument();
      });
    });

    it("renders Secrets check card title", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Secrets")).toBeInTheDocument();
      });
    });

    it("renders Config check card title", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Config")).toBeInTheDocument();
      });
    });
  });

  // ── CPU card content ─────────────────────────────────────────────────────────

  describe("CPU card content", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders MIN, AVG, MAX stat boxes", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText("MIN").length).toBeGreaterThan(0);
        expect(screen.getAllByText("AVG").length).toBeGreaterThan(0);
        expect(screen.getAllByText("MAX").length).toBeGreaterThan(0);
      });
    });

    it("renders outlier count in CPU card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/outliers/i).length).toBeGreaterThan(0);
      });
    });

    it("renders istio-proxy avg label when istio containers are present", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText("istio-proxy").length).toBeGreaterThan(0);
      });
    });
  });

  // ── Memory card content ──────────────────────────────────────────────────────

  describe("Memory card content", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders Distribution label in memory card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText("Distribution").length).toBeGreaterThan(0);
      });
    });
  });

  // ── Restarts card content ────────────────────────────────────────────────────

  describe("Restarts card content", () => {
    it("shows 'No container restarts' when restarts list is empty", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(/no container restarts/i)).toBeInTheDocument();
      });
    });

    it("shows restart entries when restarts list is non-empty", async () => {
      const dataWithRestarts = {
        ...MOCK_HEALTH_DATA,
        results: {
          "signal-api-prod": {
            "eus2-prod-a31": {
              ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
              checks: {
                ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"].checks,
                restarts: {
                  status: "unhealthy",
                  restarts: [
                    { pod: "signal-api-prod-abc123", container: "signal-api-prod", count: 5 },
                  ],
                },
              },
            },
          },
        },
      };
      mockFetchSuccess(dataWithRestarts);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("signal-api-prod-abc123")).toBeInTheDocument();
        expect(screen.getByText("5 restart(s)")).toBeInTheDocument();
      });
    });
  });

  // ── Node CPU card content ─────────────────────────────────────────────────────

  describe("Node CPU card content", () => {
    it("shows 'No node CPU issues' when nodes list is empty", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(/no node cpu issues/i)).toBeInTheDocument();
      });
    });

    it("shows node entries when nodes list is non-empty", async () => {
      const dataWithNodes = {
        ...MOCK_HEALTH_DATA,
        results: {
          "signal-api-prod": {
            "eus2-prod-a31": {
              ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
              checks: {
                ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"].checks,
                node_cpu: {
                  status: "unhealthy",
                  nodes: [
                    { node: "node-1", cpu_usage_percent: 95.5 },
                  ],
                },
              },
            },
          },
        },
      };
      mockFetchSuccess(dataWithNodes);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("node-1")).toBeInTheDocument();
        expect(screen.getByText(/CPU: 95.5%/)).toBeInTheDocument();
      });
    });
  });

  // ── NPD card content ─────────────────────────────────────────────────────────

  describe("NPD card content", () => {
    it("renders NPD message text", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(/no npd events detected/i)).toBeInTheDocument();
      });
    });
  });

  // ── Scale events card content ─────────────────────────────────────────────────

  describe("Scale Events card content", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders CURRENT, BASELINE, CHANGE stat boxes", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("CURRENT")).toBeInTheDocument();
        expect(screen.getByText("BASELINE")).toBeInTheDocument();
        expect(screen.getByText("CHANGE")).toBeInTheDocument();
      });
    });

    it("renders scale events message", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(/pod count stable at 2 pods/i)).toBeInTheDocument();
      });
    });
  });

  // ── Pod age card content ──────────────────────────────────────────────────────

  describe("Pod Age card content", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders NEW, RECENT, MATURE, OLD stat boxes", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText("NEW").length).toBeGreaterThan(0);
        expect(screen.getAllByText("RECENT").length).toBeGreaterThan(0);
        expect(screen.getAllByText("MATURE").length).toBeGreaterThan(0);
        expect(screen.getAllByText("OLD").length).toBeGreaterThan(0);
      });
    });

    it("renders AVG AGE, OLDEST, NEWEST stat boxes", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText("AVG AGE").length).toBeGreaterThan(0);
        expect(screen.getAllByText("OLDEST").length).toBeGreaterThan(0);
        expect(screen.getAllByText("NEWEST").length).toBeGreaterThan(0);
      });
    });
  });

  // ── Pod rescheduling card content ─────────────────────────────────────────────

  describe("Pod Rescheduling card content", () => {
    it("renders 'No rescheduling activity' when activity_type is none", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/no rescheduling activity/i).length).toBeGreaterThan(0);
      });
    });

    it("renders the diagnosis text", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getAllByText(/no recent pod activity/i).length
        ).toBeGreaterThan(0);
      });
    });
  });

  // ── Replica readiness card content ────────────────────────────────────────────

  describe("Replica Readiness card content", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders 'ready' label", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText("ready").length).toBeGreaterThan(0);
      });
    });

    it("renders the deployment name in replica readiness card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Deployment:")).toBeInTheDocument();
      });
    });

    it("renders the replica readiness message", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/all 2 replicas ready/i).length).toBeGreaterThan(0);
      });
    });
  });

  // ── Rollout card content ──────────────────────────────────────────────────────

  describe("Rollout card content", () => {
    it("shows 'No rollout activity detected' when no rollout is active", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getAllByText(/no rollout activity detected in last/i).length
        ).toBeGreaterThan(0);
      });
    });

    it("shows alert when rollout is detected", async () => {
      const dataWithRollout = {
        ...MOCK_HEALTH_DATA,
        results: {
          "signal-api-prod": {
            "eus2-prod-a31": {
              ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
              checks: {
                ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"].checks,
                rollout: {
                  rollout_detected: true,
                  upgrade_detected: false,
                  activity_type: "rollout",
                  message: "Active rollout detected",
                },
              },
            },
          },
        },
      };
      mockFetchSuccess(dataWithRollout);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Active rollout detected")).toBeInTheDocument();
      });
    });
  });

  // ── Secrets card content ──────────────────────────────────────────────────────

  describe("Secrets card content", () => {
    it("shows healthy secrets message when no failed secrets", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getAllByText(/all external secrets for signal-api-prod are healthy/i).length
        ).toBeGreaterThan(0);
      });
    });

    it("shows failed secrets entries when present", async () => {
      const dataWithFailedSecrets = {
        ...MOCK_HEALTH_DATA,
        results: {
          "signal-api-prod": {
            "eus2-prod-a31": {
              ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
              checks: {
                ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"].checks,
                secrets: {
                  status: "unhealthy",
                  failed_secrets: [{ name: "my-failed-secret" }],
                  message: "Some external secrets failed",
                },
              },
            },
          },
        },
      };
      mockFetchSuccess(dataWithFailedSecrets);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("my-failed-secret")).toBeInTheDocument();
      });
    });
  });

  // ── Config card content ───────────────────────────────────────────────────────

  describe("Config card content", () => {
    it("shows config message when no anomalies", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getAllByText(/ccm not enabled for this app/i).length
        ).toBeGreaterThan(0);
      });
    });

    it("shows config anomalies when present", async () => {
      const dataWithAnomalies = {
        ...MOCK_HEALTH_DATA,
        results: {
          "signal-api-prod": {
            "eus2-prod-a31": {
              ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
              checks: {
                ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"].checks,
                config: {
                  status: "unhealthy",
                  ccm_enabled: true,
                  configmaps_checked: [],
                  anomalies: [{ message: "Config drift detected" }],
                  message: "Config anomalies found",
                },
              },
            },
          },
        },
      };
      mockFetchSuccess(dataWithAnomalies);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Config drift detected")).toBeInTheDocument();
      });
    });
  });

  // ── Istio cards content ───────────────────────────────────────────────────────

  describe("Istio / Network card content", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("renders Success Rate label in istio success card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/success rate/i).length).toBeGreaterThan(0);
      });
    });

    it("renders Request Rate label in istio traffic spike card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/request rate/i).length).toBeGreaterThan(0);
      });
    });

    it("renders P95 Latency label in istio latency card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/p95 latency/i).length).toBeGreaterThan(0);
      });
    });

    it("renders Anomaly label in istio latency card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/anomaly:/i).length).toBeGreaterThan(0);
      });
    });

    it("renders Prometheus link when prometheus_url is present", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        const promLinks = screen.getAllByText("Prometheus");
        expect(promLinks.length).toBeGreaterThan(0);
      });
    });

    it("renders 'Improvement detected' when positive_anomaly is true", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(/improvement detected/i)).toBeInTheDocument();
      });
    });

    it("renders 2xx, 3xx, 4xx, 5xx response code labels", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/2xx/i).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/3xx/i).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/4xx/i).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/5xx/i).length).toBeGreaterThan(0);
      });
    });

    it("renders RETRY RATE and COUNT (5m) stat boxes in retries card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("RETRY RATE")).toBeInTheDocument();
        expect(screen.getByText("COUNT (5m)")).toBeInTheDocument();
      });
    });

    it("renders 'No client retries' message when retry rate is 0", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/no client retries/i).length).toBeGreaterThan(0);
      });
    });

    it("renders 'Not Rate Limited' message when not rate limited", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/not rate limited/i).length).toBeGreaterThan(0);
      });
    });

    it("renders LIMITED and PASSED stat boxes in rate limiting card", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText("LIMITED").length).toBeGreaterThan(0);
        expect(screen.getAllByText("PASSED").length).toBeGreaterThan(0);
      });
    });

    it("shows server latency issue text when anomaly is detected", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(
          screen.getByText(/server p95 latency spike detected/i)
        ).toBeInTheDocument();
      });
    });

    it("renders latency anomaly reason details", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(/rolling:/i)).toBeInTheDocument();
        expect(screen.getByText(/historical:/i)).toBeInTheDocument();
      });
    });

    it("renders 'Rate Limited' when rate_limited is true", async () => {
      const dataRateLimited = {
        ...MOCK_HEALTH_DATA,
        results: {
          "signal-api-prod": {
            "eus2-prod-a31": {
              ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
              checks: {
                ...MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"].checks,
                istio_rate_limiting: {
                  status: "unhealthy",
                  rate_limited: true,
                  limited_rate: 5.1234,
                  passed_rate: 1.5,
                  message: "Rate limiting active",
                },
              },
            },
          },
        },
      };
      mockFetchSuccess(dataRateLimited);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Rate Limited")).toBeInTheDocument();
      });
    });
  });

  // ── Cluster tab switching ─────────────────────────────────────────────────────

  describe("cluster tab switching", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("switches to second cluster when tab is clicked", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("scus-prod-a74")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("scus-prod-a74"));

      // The second cluster tab should now be active (button visible)
      await waitFor(() => {
        expect(screen.getByText("scus-prod-a74")).toBeInTheDocument();
      });
    });
  });

  // ── Compare view ──────────────────────────────────────────────────────────────

  describe("compare view", () => {
    beforeEach(() => {
      mockFetchSuccess();
    });

    it("shows compare table when Compare button is clicked", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        // The compare table header row shows "Check" column
        expect(screen.getByText("Check")).toBeInTheDocument();
      });
    });

    it("renders DEPLOYMENT section in compare table", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        expect(screen.getByText("DEPLOYMENT")).toBeInTheDocument();
      });
    });

    it("renders INFRASTRUCTURE section in compare table", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        // INFRASTRUCTURE appears in both section heading and compare table
        expect(screen.getAllByText("INFRASTRUCTURE").length).toBeGreaterThan(0);
      });
    });

    it("renders Strategy row in compare table", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        expect(screen.getByText("Strategy")).toBeInTheDocument();
      });
    });

    it("renders Request Rate row in compare table", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        expect(screen.getByText("Request Rate")).toBeInTheDocument();
      });
    });

    it("renders Rate Limited row in compare table", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        expect(screen.getByText("Rate Limited")).toBeInTheDocument();
      });
    });

    it("toggles back to card view when Compare is clicked again", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });

      // Enter compare
      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        expect(screen.getByText("Check")).toBeInTheDocument();
      });

      // Exit compare
      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        expect(screen.getByText("INFRASTRUCTURE")).toBeInTheDocument();
      });
    });

    it("exits compare mode when a cluster tab is clicked", async () => {
      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Compare")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Compare"));

      await waitFor(() => {
        expect(screen.getByText("Check")).toBeInTheDocument();
      });

      // The cluster tab buttons are the first two occurrences of the cluster names
      const clusterTabs = screen.getAllByText("eus2-prod-a31");
      // Click the first one (the tab button, not the table column header)
      fireEvent.click(clusterTabs[0]);

      await waitFor(() => {
        expect(screen.getByText("INFRASTRUCTURE")).toBeInTheDocument();
      });
    });
  });

  // ── Team details in header ────────────────────────────────────────────────────

  describe("team details in header", () => {
    it("renders slack channels when provided", async () => {
      mockFetchSuccess();
      const app = makeApp({ slackChannels: ["sre-alerts", "platform-eng"] });

      render(<HealthReportModal app={app} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("#sre-alerts, #platform-eng")).toBeInTheDocument();
      });
    });

    it("renders xmatters groups when provided", async () => {
      mockFetchSuccess();
      const app = makeApp({ xmattersGroups: ["sre-team"] });

      render(<HealthReportModal app={app} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("sre-team")).toBeInTheDocument();
      });
    });

    it("renders email addresses when provided", async () => {
      mockFetchSuccess();
      const app = makeApp({ emails: ["sre@example.com"] });

      render(<HealthReportModal app={app} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("sre@example.com")).toBeInTheDocument();
      });
    });

    it("renders 'Slack' label when slack channels are present", async () => {
      mockFetchSuccess();
      const app = makeApp({ slackChannels: ["sre-alerts"] });

      render(<HealthReportModal app={app} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Slack")).toBeInTheDocument();
      });
    });

    it("renders 'XMatters' label when xmatters groups are present", async () => {
      mockFetchSuccess();
      const app = makeApp({ xmattersGroups: ["sre-team"] });

      render(<HealthReportModal app={app} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("XMatters")).toBeInTheDocument();
      });
    });

    it("renders 'Email' label when emails are present", async () => {
      mockFetchSuccess();
      const app = makeApp({ emails: ["sre@example.com"] });

      render(<HealthReportModal app={app} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Email")).toBeInTheDocument();
      });
    });

    it("does not render team details section when none provided", async () => {
      mockFetchSuccess();
      const app = makeApp({
        slackChannels: [],
        xmattersGroups: [],
        emails: [],
      });

      render(<HealthReportModal app={app} onClose={jest.fn()} />);

      await waitFor(() => {
        // Section headings should not appear
        expect(screen.queryByText("Slack")).not.toBeInTheDocument();
        expect(screen.queryByText("XMatters")).not.toBeInTheDocument();
        expect(screen.queryByText("Email")).not.toBeInTheDocument();
      });
    });
  });

  // ── Fetch URL construction ────────────────────────────────────────────────────

  describe("fetch URL construction", () => {
    it("calls fetch with the correct health-proxy URL", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          expect.stringContaining("/api/health-proxy")
        );
      });
    });

    it("encodes namespace and appName in the fetch URL", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          expect.stringMatching(/namespace=intl-sre/)
        );
        expect(global.fetch).toHaveBeenCalledWith(
          expect.stringMatching(/app=signal-api-prod/)
        );
      });
    });

    it("uses empty string namespace when namespace is not provided", async () => {
      mockFetchSuccess();

      render(
        <HealthReportModal
          app={makeApp({ namespace: null })}
          onClose={jest.fn()}
        />
      );

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          expect.stringContaining("namespace=")
        );
      });
    });
  });

  // ── Single cluster (no compare button) ───────────────────────────────────────

  describe("single cluster scenario", () => {
    it("does not render Compare button when there is only one cluster", async () => {
      const singleClusterData = {
        ...MOCK_HEALTH_DATA,
        results: {
          "signal-api-prod": {
            "eus2-prod-a31":
              MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
          },
        },
      };
      mockFetchSuccess(singleClusterData);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("eus2-prod-a31")).toBeInTheDocument();
      });

      expect(screen.queryByText("Compare")).not.toBeInTheDocument();
    });
  });

  // ── Data using first key fallback when appName doesn't match ─────────────────

  describe("results key fallback", () => {
    it("falls back to the first results key when app name does not match", async () => {
      const differentKeyData = {
        ...MOCK_HEALTH_DATA,
        results: {
          "some-other-key": {
            "eus2-prod-a31":
              MOCK_HEALTH_DATA.results["signal-api-prod"]["eus2-prod-a31"],
          },
        },
      };
      mockFetchSuccess(differentKeyData);

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("eus2-prod-a31")).toBeInTheDocument();
      });
    });
  });

  // ── Error rate display ────────────────────────────────────────────────────────

  describe("error rate display", () => {
    it("renders error rate in istio server success card", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/error rate:/i).length).toBeGreaterThan(0);
      });
    });
  });

  // ── Non-2xx rate display ──────────────────────────────────────────────────────

  describe("non-2xx rate display", () => {
    it("renders 'Non-2xx rate:' text in traffic spike card", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText(/non-2xx rate:/i).length).toBeGreaterThan(0);
      });
    });
  });

  // ── Circular gauge rendering ──────────────────────────────────────────────────

  describe("CircularGauge rendering", () => {
    it("renders the health gauge label", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("health")).toBeInTheDocument();
      });
    });

    it("renders the success gauge label in istio success card", async () => {
      mockFetchSuccess();

      render(<HealthReportModal app={makeApp()} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getAllByText("success").length).toBeGreaterThan(0);
      });
    });
  });
});
