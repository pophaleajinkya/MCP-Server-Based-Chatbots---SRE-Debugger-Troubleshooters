/**
 * Tests for src/lib/promql-actions.ts — queryPromQLRange()
 *
 * Coverage targets:
 *  ✓ PROMQL_API_URL env var present / absent (throws when missing)
 *  ✓ /prometheus/query-range endpoint + POST method + JSON body
 *  ✓ Happy path (response.ok → returns parsed JSON)
 *  ✓ Retry on 502 / 503 / 504
 *  ✓ Exhausts MAX_RETRIES on persistent gateway errors → throws
 *  ✓ Non-retryable failure (400, 500) → throws immediately
 *  ✓ fetch() rejection handling
 */

import { queryPromQLRange } from "@/lib/promql-actions";
import type { PromQLQueryRangePayload } from "@/lib/promql-actions";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const PAYLOAD: PromQLQueryRangePayload = {
  promql: 'ALERTS{tool="juno"}',
  start: "1704067200",
  end: "1704070800",
  step: "60s",
};

const PROMQL_RESULT = {
  status: "success",
  data: {
    resultType: "matrix",
    result: [
      {
        metric: { __name__: "ALERTS", alertname: "HighCPU" },
        values: [[1704067200, "1"], [1704067260, "1"]],
      },
    ],
  },
};

const EMPTY_RESULT = {
  status: "success",
  data: { resultType: "matrix", result: [] },
};

// ─── Response helpers ─────────────────────────────────────────────────────────

function okResp(data: unknown = PROMQL_RESULT): Promise<Response> {
  return Promise.resolve({
    ok: true,
    status: 200,
    statusText: "OK",
    json: jest.fn().mockResolvedValue(data),
  } as unknown as Response);
}

function failResp(status: number, statusText = "Error"): Promise<Response> {
  return Promise.resolve({
    ok: false,
    status,
    statusText,
    json: jest.fn().mockResolvedValue({}),
    text: jest.fn().mockResolvedValue(""),
  } as unknown as Response);
}

// ─── Setup / teardown ────────────────────────────────────────────────────────

let mockFetch: jest.Mock;

beforeEach(() => {
  mockFetch = jest.fn();
  (global as unknown as Record<string, unknown>).fetch = mockFetch;

  jest.spyOn(console, "log").mockImplementation(() => {});
  jest.spyOn(console, "error").mockImplementation(() => {});

  // Make retry delays instant
  jest.spyOn(global, "setTimeout").mockImplementation((fn: unknown) => {
    if (typeof fn === "function") fn();
    return 0 as unknown as ReturnType<typeof setTimeout>;
  });

  process.env.PROMQL_API_URL = "http://promql-svc:9090/prometheus/query-range";
});

afterEach(() => {
  jest.restoreAllMocks();
  delete process.env.PROMQL_API_URL;
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("queryPromQLRange", () => {
  // ── Environment ──────────────────────────────────────────────────────────
  describe("environment", () => {
    it("throws when PROMQL_API_URL is not set", async () => {
      delete process.env.PROMQL_API_URL;
      await expect(queryPromQLRange(PAYLOAD)).rejects.toThrow(/PROMQL_API_URL/);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("uses PROMQL_API_URL directly as the request URL", async () => {
      process.env.PROMQL_API_URL = "http://custom-host:8080/prometheus/query-range";
      mockFetch.mockReturnValue(okResp());
      await queryPromQLRange(PAYLOAD);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toBe("http://custom-host:8080/prometheus/query-range");
    });
  });

  // ── Request shape ──────────────────────────────────────────────────────
  describe("request shape", () => {
    it("calls /prometheus/query-range endpoint", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryPromQLRange(PAYLOAD);

      const [url] = mockFetch.mock.calls[0];
      expect(url).toMatch(/\/prometheus\/query-range$/);
    });

    it("sends a POST request with JSON content type", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryPromQLRange(PAYLOAD);

      const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(opts.method).toBe("POST");
      expect((opts.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    });

    it("serializes payload as JSON body", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryPromQLRange(PAYLOAD);

      const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(opts.body as string);
      expect(body.promql).toBe(PAYLOAD.promql);
      expect(body.start).toBe(PAYLOAD.start);
      expect(body.end).toBe(PAYLOAD.end);
      expect(body.step).toBe(PAYLOAD.step);
    });
  });

  // ── Happy path ─────────────────────────────────────────────────────────
  describe("successful response", () => {
    it("returns parsed JSON on 200", async () => {
      mockFetch.mockReturnValue(okResp(PROMQL_RESULT));
      const result = await queryPromQLRange(PAYLOAD);

      expect(result.status).toBe("success");
      expect(result.data?.result).toHaveLength(1);
      expect(result.data?.result?.[0].metric.alertname).toBe("HighCPU");
    });

    it("returns empty result correctly", async () => {
      mockFetch.mockReturnValue(okResp(EMPTY_RESULT));
      const result = await queryPromQLRange(PAYLOAD);

      expect(result.data?.result).toHaveLength(0);
    });

    it("calls fetch exactly once on success", async () => {
      mockFetch.mockReturnValue(okResp());
      await queryPromQLRange(PAYLOAD);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  // ── Retry behavior ─────────────────────────────────────────────────────
  describe("retry on gateway errors", () => {
    it("retries on 502 and succeeds on second attempt", async () => {
      mockFetch
        .mockReturnValueOnce(failResp(502, "Bad Gateway"))
        .mockReturnValueOnce(okResp());

      const result = await queryPromQLRange(PAYLOAD);

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result.status).toBe("success");
    });

    it("retries on 503 and succeeds on second attempt", async () => {
      mockFetch
        .mockReturnValueOnce(failResp(503, "Service Unavailable"))
        .mockReturnValueOnce(okResp());

      const result = await queryPromQLRange(PAYLOAD);

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result.status).toBe("success");
    });

    it("retries on 504 and succeeds on second attempt", async () => {
      mockFetch
        .mockReturnValueOnce(failResp(504, "Gateway Timeout"))
        .mockReturnValueOnce(okResp());

      const result = await queryPromQLRange(PAYLOAD);
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result.status).toBe("success");
    });

    it("throws after exhausting 3 retries on persistent 502", async () => {
      mockFetch.mockReturnValue(failResp(502, "Bad Gateway"));

      await expect(queryPromQLRange(PAYLOAD)).rejects.toThrow(/502/);
      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it("uses setTimeout for retry delay", async () => {
      mockFetch
        .mockReturnValueOnce(failResp(502, "Bad Gateway"))
        .mockReturnValueOnce(okResp());

      await queryPromQLRange(PAYLOAD);
      expect(global.setTimeout).toHaveBeenCalled();
    });
  });

  // ── Non-retryable errors ───────────────────────────────────────────────
  describe("non-retryable HTTP errors", () => {
    it("throws immediately on 400", async () => {
      mockFetch.mockReturnValue(failResp(400, "Bad Request"));
      await expect(queryPromQLRange(PAYLOAD)).rejects.toThrow(/400/);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("throws immediately on 500", async () => {
      mockFetch.mockReturnValue(failResp(500, "Internal Server Error"));
      await expect(queryPromQLRange(PAYLOAD)).rejects.toThrow(/500/);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("throws immediately on 404", async () => {
      mockFetch.mockReturnValue(failResp(404, "Not Found"));
      await expect(queryPromQLRange(PAYLOAD)).rejects.toThrow(/404/);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  // ── Network errors ─────────────────────────────────────────────────────
  describe("fetch() network errors", () => {
    it("re-throws when fetch() rejects with Error", async () => {
      mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));
      await expect(queryPromQLRange(PAYLOAD)).rejects.toThrow("ECONNREFUSED");
    });

    it("wraps non-Error rejections in Error", async () => {
      mockFetch.mockRejectedValue("network down");
      await expect(queryPromQLRange(PAYLOAD)).rejects.toBeInstanceOf(Error);
    });

    it("does not retry when fetch itself throws (no response status)", async () => {
      mockFetch.mockRejectedValue(new Error("DNS failure"));
      await expect(queryPromQLRange(PAYLOAD)).rejects.toThrow();
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });
});
