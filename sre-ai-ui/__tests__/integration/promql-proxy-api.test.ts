/**
 * Tests for POST /api/promql-proxy
 *
 * The route is a thin proxy: it forwards the request body to the upstream
 * PromQL API and returns the upstream JSON + status to the caller.
 *
 * Coverage targets:
 *  ✓ happy path  (try block)
 *  ✓ error path  (catch block)
 *    - err instanceof Error  → message from error
 *    - err is non-Error      → fallback string "Failed to fetch promql proxy"
 */

// ─── Mock next/server to avoid Web API dependency ────────────────────────────
const mockJsonResponses: Array<{ data: unknown; opts?: { status?: number } }> = [];

jest.mock("next/server", () => ({
  NextResponse: {
    json: (data: unknown, opts?: { status?: number }) => {
      const status = opts?.status ?? 200;
      mockJsonResponses.push({ data, opts });
      return {
        status,
        json: async () => data,
      };
    },
  },
}));

// ─── Mock api-client getPromqlApiUrl ─────────────────────────────────────────
const mockGetPromqlApiUrl = jest.fn();
jest.mock("@/lib/api-client", () => ({
  getPromqlApiUrl: (...args: unknown[]) => mockGetPromqlApiUrl(...args),
}));

import { POST } from "@/app/api/promql-proxy/route";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const PROMQL_API_URL = "http://promql-svc:9090";

function makeReq(body: unknown = {}): any {
  return {
    json: jest.fn().mockResolvedValue(body),
  };
}

function makeUpstream(
  data: unknown,
  status = 200
): Promise<Response> {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: jest.fn().mockResolvedValue(data),
    text: jest.fn().mockResolvedValue(JSON.stringify(data)),
  } as unknown as Response);
}

// ─── Setup / teardown ────────────────────────────────────────────────────────

let mockFetch: jest.Mock;

beforeEach(() => {
  mockFetch = jest.fn();
  (global as unknown as Record<string, unknown>).fetch = mockFetch;
  mockJsonResponses.length = 0;

  jest.spyOn(console, "log").mockImplementation(() => {});
  jest.spyOn(console, "error").mockImplementation(() => {});

  // Default: getPromqlApiUrl returns a valid URL
  mockGetPromqlApiUrl.mockReturnValue(PROMQL_API_URL);
});

afterEach(() => {
  jest.restoreAllMocks();
  mockGetPromqlApiUrl.mockReset();
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("POST /api/promql-proxy", () => {
  // ── Happy path ──────────────────────────────────────────────────────────────

  describe("successful upstream response", () => {
    it("returns 200 and the upstream JSON body", async () => {
      const upstreamData = { status: "success", data: { resultType: "matrix", result: [] } };
      mockFetch.mockReturnValue(makeUpstream(upstreamData, 200));

      const res = await POST(makeReq({ promql: "up", start: "1000", end: "2000", step: "60s" }));

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual(upstreamData);
    });

    it("forwards non-200 upstream status unchanged", async () => {
      const upstreamData = { detail: "Not found" };
      mockFetch.mockReturnValue(makeUpstream(upstreamData, 404));

      const res = await POST(makeReq({}));

      expect(res.status).toBe(404);
      const body = await res.json();
      expect(body).toEqual({ error: JSON.stringify(upstreamData) });
    });

    it("forwards 500 upstream status unchanged", async () => {
      const upstreamData = { detail: "Internal error" };
      mockFetch.mockReturnValue(makeUpstream(upstreamData, 500));

      const res = await POST(makeReq({}));

      expect(res.status).toBe(500);
    });

    it("calls the upstream PromQL API URL with POST method", async () => {
      mockFetch.mockReturnValue(makeUpstream({}, 200));
      await POST(makeReq({ promql: "up" }));

      expect(mockFetch).toHaveBeenCalledWith(
        PROMQL_API_URL,
        expect.objectContaining({ method: "POST" })
      );
    });

    it("sends Content-Type: application/json to upstream", async () => {
      mockFetch.mockReturnValue(makeUpstream({}, 200));
      await POST(makeReq({}));

      const [, options] = mockFetch.mock.calls[0];
      expect((options as RequestInit).headers).toEqual(
        expect.objectContaining({ "Content-Type": "application/json" })
      );
    });

    it("forwards the request body as JSON string to upstream", async () => {
      const requestBody = { promql: "up{job='test'}", start: "100", end: "200", step: "15s" };
      mockFetch.mockReturnValue(makeUpstream({}, 200));
      await POST(makeReq(requestBody));

      const [, options] = mockFetch.mock.calls[0];
      expect((options as RequestInit).body).toBe(JSON.stringify(requestBody));
    });

    it("returns an empty result when upstream returns none", async () => {
      mockFetch.mockReturnValue(makeUpstream({ status: "success", data: { result: [] } }, 200));
      const res = await POST(makeReq({}));

      const body = await res.json();
      expect(body.data.result).toEqual([]);
    });
  });

  // ── Error path ──────────────────────────────────────────────────────────────

  describe("upstream fetch failure", () => {
    it("returns 500 with the Error message when fetch throws an Error", async () => {
      mockFetch.mockRejectedValue(new Error("ECONNREFUSED"));

      const res = await POST(makeReq({}));

      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body).toEqual({ error: "ECONNREFUSED" });
    });

    it("returns 500 with fallback message when fetch throws a non-Error", async () => {
      mockFetch.mockRejectedValue("unexpected string error");

      const res = await POST(makeReq({}));

      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body).toEqual({ error: "Failed to fetch promql proxy" });
    });

    it("returns 500 with fallback message when fetch throws null", async () => {
      mockFetch.mockRejectedValue(null);

      const res = await POST(makeReq({}));

      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body).toEqual({ error: "Failed to fetch promql proxy" });
    });
  });

  // ── Environment ───────────────────────────────────────────────────────────

  describe("environment", () => {
    it("returns 500 when PROMQL_API_URL is not set (getPromqlApiUrl throws)", async () => {
      mockGetPromqlApiUrl
        .mockImplementationOnce(() => {
          throw new Error("PROMQL_API_URL is not set. Configure it in .env.local or via environment variables.");
        })
        .mockReturnValue(""); // Second call in catch block should not throw
      const res = await POST(makeReq({ promql: "up" }));
      expect(res.status).toBe(500);
      const json = await res.json();
      expect(json.error).toMatch(/PROMQL_API_URL/);
    });
  });
});
