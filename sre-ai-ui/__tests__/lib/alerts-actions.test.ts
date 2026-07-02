/**
 * Tests for src/lib/alerts-actions.ts  –  queryAlerts()
 *
 * Coverage targets:
 *  ✓ PROMQL_API_URL env var present / absent (throws when missing)
 *  ✓ /prometheus/query-range endpoint + POST method + JSON body
 *  ✓ PromQL payload wrapping (promql, start, end, step)
 *  ✓ Happy path (response.ok → transforms PromQL result → AlertQueryResult)
 *  ✓ Retry on 502 / 503 / 504 (attempt < MAX_RETRIES)
 *  ✓ Exhausts MAX_RETRIES on persistent 502 → throws
 *  ✓ Non-retryable failure (400, 500) → throws immediately
 *  ✓ fetch() rejects with Error → re-throws
 *  ✓ fetch() rejects with non-Error value → wraps in Error before throwing
 */

import { queryAlerts } from "@/lib/alerts-actions";
import type { AlertQueryPayload } from "@/lib/api-client";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const PAYLOAD: AlertQueryPayload = {
  start: "1704067200",
  end:   "1704070800",
};

/** PromQL response matching the structure returned by /prometheus/query-range */
const PROMQL_RESULT = {
  data: {
    resultType: "matrix",
    result: [
      {
        metric: {
          __name__: "ALERTS",
          alertname: "HighCPU",
          alert_type: "golden_signal",
          alert_sla_name: "cpu_sla",
          severity: "critical",
          alertstate: "firing",
          cluster: "prod-1",
          alert_team: "intl_sre_golden_signals",
          tool: "juno",
          mms_slack_channel: "#sre",
          mms_xmatters_group: "sre-group",
          alert_owner_category: "infra",
        },
        values: [
          [1704067200, "1"],
          [1704067230, "1"],
        ],
      },
      {
        metric: {
          __name__: "ALERTS",
          alertname: "HighMemory",
          alert_type: "golden_signal",
          alert_sla_name: "mem_sla",
          severity: "warning",
          alertstate: "firing",
          cluster: "prod-2",
          alert_team: "intl_sre_golden_signals",
          tool: "juno",
        },
        values: [
          [1704067200, "1"],
        ],
      },
    ],
  },
};

/** Empty PromQL result (no alerts firing) */
const EMPTY_PROMQL_RESULT = {
  data: {
    resultType: "matrix",
    result: [],
  },
};

// ─── Response helpers ─────────────────────────────────────────────────────────

function okResp(data: unknown = PROMQL_RESULT): Promise<Response> {
  return Promise.resolve({
    ok:         true,
    status:     200,
    statusText: "OK",
    json:       jest.fn().mockResolvedValue(data),
  } as unknown as Response);
}

function failResp(status: number, statusText = "Error"): Promise<Response> {
  return Promise.resolve({
    ok:         false,
    status,
    statusText,
    json:       jest.fn().mockResolvedValue({}),
    text:       jest.fn().mockResolvedValue(""),
  } as unknown as Response);
}

// ─── Setup / teardown ────────────────────────────────────────────────────────

let mockFetch: jest.Mock;

beforeEach(() => {
  mockFetch = jest.fn();
  (global as unknown as Record<string, unknown>).fetch = mockFetch;

  // Silence console noise from the implementation
  jest.spyOn(console, "log").mockImplementation(() => {});
  jest.spyOn(console, "error").mockImplementation(() => {});

  // Make retry delays instant so tests complete synchronously
  jest.spyOn(global, "setTimeout").mockImplementation((fn: unknown) => {
    if (typeof fn === "function") fn();
    return 0 as unknown as ReturnType<typeof setTimeout>;
  });

  // Set the required env var (full URL including path, matching .env.local pattern)
  process.env.PROMQL_API_URL = "http://promql-svc:9090/prometheus/query-range";
});

afterEach(() => {
  jest.restoreAllMocks();
  delete process.env.PROMQL_API_URL;
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("queryAlerts", () => {
  // ── Environment / URL construction ─────────────────────────────────────────

  describe("URL construction", () => {
    it("calls the PROMQL_API_URL directly (full URL from env)", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryAlerts(PAYLOAD);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toBe("http://promql-svc:9090/prometheus/query-range");
    });

    it("uses PROMQL_API_URL env variable when set", async () => {
      process.env.PROMQL_API_URL = "http://promql-svc.prod:9090/prometheus/query-range";
      mockFetch.mockReturnValue(okResp());
      await queryAlerts(PAYLOAD);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toBe("http://promql-svc.prod:9090/prometheus/query-range");
    });

    it("throws when PROMQL_API_URL is not set", async () => {
      delete process.env.PROMQL_API_URL;

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow(/PROMQL_API_URL/);
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  // ── Request shape ───────────────────────────────────────────────────────────

  describe("request options", () => {
    it("sends a POST request", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryAlerts(PAYLOAD);

      const [, options] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(options.method).toBe("POST");
    });

    it("sends Content-Type: application/json header", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryAlerts(PAYLOAD);

      const [, options] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect((options.headers as Record<string, string>)["Content-Type"]).toBe(
        "application/json"
      );
    });

    it("wraps the payload in PromQL format with promql, start, end, step", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryAlerts(PAYLOAD);

      const [, options] = mockFetch.mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(options.body as string);
      expect(body.promql).toMatch(/^ALERTS\{/);
      expect(body.start).toBe(PAYLOAD.start);
      expect(body.end).toBe(PAYLOAD.end);
      expect(body.step).toBe("30s"); // default step
    });

    it("uses payload step when provided", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryAlerts({ ...PAYLOAD, step: "60s" });

      const [, options] = mockFetch.mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(options.body as string);
      expect(body.step).toBe("60s");
    });
  });

  // ── Happy path ──────────────────────────────────────────────────────────────

  describe("successful response", () => {
    it("returns a transformed AlertQueryResult on 200", async () => {
      mockFetch.mockReturnValue(okResp(PROMQL_RESULT));
      const result = await queryAlerts(PAYLOAD);

      expect(result.status).toBe("success");
      expect(result.ok).toBe(true);
      expect(result.alerts).toHaveLength(2);
      expect(result.total_count).toBe(2);
      expect(typeof result.query_time_ms).toBe("number");
      expect(result.prometheus_query).toMatch(/^ALERTS\{/);
    });

    it("transforms PromQL metric labels into AlertResultAlert fields", async () => {
      mockFetch.mockReturnValue(okResp(PROMQL_RESULT));
      const result = await queryAlerts(PAYLOAD);

      const alert = result.alerts[0];
      expect(alert.alertname).toBe("HighCPU");
      expect(alert.alert_sla_name).toBe("cpu_sla");
      expect(alert.severity).toBe("critical");
      expect(alert.state).toBe("firing");
      expect(alert.cluster).toBe("prod-1");
      expect(alert.mms_slack_channel).toBe("#sre");
      expect(alert.mms_xmatters_group).toBe("sre-group");
      expect(alert.alert_owner_category).toBe("infra");
    });

    it("derives episode_start_ts from first value timestamp", async () => {
      mockFetch.mockReturnValue(okResp(PROMQL_RESULT));
      const result = await queryAlerts(PAYLOAD);

      expect(result.alerts[0].episode_start_ts).toBe(1704067200);
    });

    it("derives episode_end_ts from last value timestamp", async () => {
      mockFetch.mockReturnValue(okResp(PROMQL_RESULT));
      const result = await queryAlerts(PAYLOAD);

      expect(result.alerts[0].episode_end_ts).toBe(1704067230);
    });

    it("sets episode_is_open to true for firing alerts", async () => {
      mockFetch.mockReturnValue(okResp(PROMQL_RESULT));
      const result = await queryAlerts(PAYLOAD);

      expect(result.alerts[0].episode_is_open).toBe(true);
    });

    it("returns empty alerts array for empty PromQL result", async () => {
      mockFetch.mockReturnValue(okResp(EMPTY_PROMQL_RESULT));
      const result = await queryAlerts(PAYLOAD);

      expect(result.alerts).toHaveLength(0);
      expect(result.total_count).toBe(0);
    });

    it("preserves the raw values array on each alert", async () => {
      mockFetch.mockReturnValue(okResp(PROMQL_RESULT));
      const result = await queryAlerts(PAYLOAD);

      expect(result.alerts[0].values).toEqual([
        [1704067200, "1"],
        [1704067230, "1"],
      ]);
    });

    it("stores raw metric labels on the alert", async () => {
      mockFetch.mockReturnValue(okResp(PROMQL_RESULT));
      const result = await queryAlerts(PAYLOAD);

      expect(result.alerts[0].labels).toBeDefined();
      expect(result.alerts[0].labels!.__name__).toBe("ALERTS");
    });

    it("calls fetch exactly once on a successful first attempt", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryAlerts(PAYLOAD);

      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  // ── Retry behaviour ─────────────────────────────────────────────────────────

  describe("retry on gateway errors", () => {
    it("retries once on 502 and returns data when second attempt succeeds", async () => {
      mockFetch
        .mockReturnValueOnce(failResp(502, "Bad Gateway"))
        .mockReturnValueOnce(okResp(PROMQL_RESULT));

      const result = await queryAlerts(PAYLOAD);

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result.ok).toBe(true);
      expect(result.alerts).toHaveLength(2);
    });

    it("retries once on 503 and returns data when second attempt succeeds", async () => {
      mockFetch
        .mockReturnValueOnce(failResp(503, "Service Unavailable"))
        .mockReturnValueOnce(okResp(PROMQL_RESULT));

      const result = await queryAlerts(PAYLOAD);

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result.ok).toBe(true);
    });

    it("retries once on 504 and returns data when second attempt succeeds", async () => {
      mockFetch
        .mockReturnValueOnce(failResp(504, "Gateway Timeout"))
        .mockReturnValueOnce(okResp(PROMQL_RESULT));

      const result = await queryAlerts(PAYLOAD);

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result.ok).toBe(true);
    });

    it("throws after exhausting all 3 retries on persistent 502", async () => {
      mockFetch.mockReturnValue(failResp(502, "Bad Gateway"));

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow(/502/);
      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it("calls setTimeout once between two attempts (retry delay)", async () => {
      mockFetch
        .mockReturnValueOnce(failResp(502, "Bad Gateway"))
        .mockReturnValueOnce(okResp());

      await queryAlerts(PAYLOAD);

      expect(global.setTimeout).toHaveBeenCalledTimes(1);
    });
  });

  // ── Non-retryable failures ──────────────────────────────────────────────────

  describe("non-retryable HTTP errors", () => {
    it("throws immediately on 400 without retrying", async () => {
      mockFetch.mockReturnValue(failResp(400, "Bad Request"));

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow(/400/);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("retries on 500 (transient server error) and throws after exhausting retries", async () => {
      mockFetch.mockReturnValue(failResp(500, "Internal Server Error"));

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow(/500/);
      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it("throws immediately on 401 without retrying", async () => {
      mockFetch.mockReturnValue(failResp(401, "Unauthorized"));

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow(/401/);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("error message includes the status code", async () => {
      mockFetch.mockReturnValue(failResp(503, "Service Unavailable"));

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow("503");
    });
  });

  // ── fetch() rejection handling ──────────────────────────────────────────────

  describe("fetch() network errors", () => {
    it("re-throws when fetch() rejects with an Error", async () => {
      mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow("ECONNREFUSED");
    });

    it("wraps non-Error thrown values in an Error before re-throwing", async () => {
      mockFetch.mockRejectedValue("plain string rejection");

      await expect(queryAlerts(PAYLOAD)).rejects.toBeInstanceOf(Error);
    });

    it("wraps non-Error thrown values preserving the original message", async () => {
      mockFetch.mockRejectedValue("plain string rejection");

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow("plain string rejection");
    });

    it("does not retry when fetch() itself rejects (no response available)", async () => {
      mockFetch.mockRejectedValue(new Error("network failure"));

      await expect(queryAlerts(PAYLOAD)).rejects.toThrow();
      // No response → catch block skips retry branch → throws immediately
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });
});
